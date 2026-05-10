# apps/winner_claim/views.py
from venv import logger
import stripe
from apps.users.models import UserAddress
from django.db.models import F, ExpressionWrapper, DateTimeField, Sum, Q, Count
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework.permissions import IsAdminUser
from cloudinary.utils import cloudinary_url
from apps.common.pagination import AdminParticipantPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.auction.models import AuctionWin
from .models import ClaimAttempt, PaymentLog
from apps.auction.models import Bid
from .serializers import (
    ClaimInitiateRequestSerializer,
    ClaimInitiateResponseSerializer,
)
stripe.api_key = settings.STRIPE_SECRET_KEY


class ClaimInitiateView(APIView):
    """
    POST body: {"auction_id": 69} or {"auction_id": 69, "address_id": 3}
    Winner initiates claim → creates payment session
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ClaimInitiateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        auction_id = serializer.validated_data['auction_id']
        address_id = serializer.validated_data.get('address_id') 

        win = get_object_or_404(AuctionWin, auction_id=auction_id, winner=request.user)

        if not win.is_claim_window_open():
            return Response({"error": "Claim window has expired"}, status=status.HTTP_403_FORBIDDEN)

       
        if address_id:
            address = get_object_or_404(UserAddress, id=address_id, user=request.user)
        else:
            address = UserAddress.objects.filter(
                user=request.user,
                is_default=True
            ).first() or UserAddress.objects.filter(user=request.user).first()

        if address and not win.shipping_address:
            win.shipping_address = address
            win.save(update_fields=['shipping_address'])

        # Calculate total to pay
        bid_coins_used = Bid.objects.filter(
            auction=win.auction,
            user=request.user
        ).aggregate(total=Sum('coins_deducted'))['total'] or 0

        total_amount = win.auction.auction_price - bid_coins_used
        amount_in_cents = int(total_amount * 100)

        # Create or get claim attempt record
        claim_attempt, created = ClaimAttempt.objects.get_or_create(
            win_record=win,
            defaults={'payment_initiated': False}
        )

        if claim_attempt.payment_completed:
            return Response({"error": "Payment already completed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'sar',
                        'product_data': {
                            'name': f"Winning {win.auction.product_name}",
                        },
                        'unit_amount': amount_in_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=request.build_absolute_uri('/api/winner-claim/payment/success/') + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=request.build_absolute_uri('/api/winner-claim/payment/initiate/'),
                metadata={
                    'payment_type': 'winner_claim',
                    'auction_id': win.auction.id,
                    'win_id': win.id,
                    'user_id': request.user.id,
                    'total_sar': float(total_amount),
                }
            )

            # Update claim attempt
            claim_attempt.payment_initiated = True
            claim_attempt.payment_session_id = session.id
            claim_attempt.save()

            return Response(ClaimInitiateResponseSerializer({
                'session_id': session.id,
                'checkout_url': session.url,
                'amount_sar': total_amount
            }).data)

        except stripe.error.StripeError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class StripeWebhookView(APIView):
    """
    Stripe webhook - confirm payment, log it, and mark claim as completed
    """
    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Webhook payload error: {e}")
            return Response(status=400)
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Webhook signature failed: {e}")
            return Response(status=400)

        # Handle successful checkout
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            # Extract metadata
            auction_id = session['metadata'].get('auction_id')
            win_id = session['metadata'].get('win_id')
            amount_paid = session['amount_total'] / 100  # Stripe amount is in cents
            currency = session['currency'].upper()

            # Find the claim attempt
            try:
                claim_attempt = ClaimAttempt.objects.get(
                    win_record__id=win_id,
                    win_record__auction_id=auction_id
                )

                # Mark payment as completed
                claim_attempt.payment_completed = True
                claim_attempt.completed_at = timezone.now()
                claim_attempt.save()

                # Mark the win as claimed
                claim_attempt.win_record.claimed = True
                claim_attempt.win_record.claimed_at = timezone.now()
                claim_attempt.win_record.save()

                # ────────────────────────────────────────────────
                # CREATE PAYMENT LOG ENTRY
                # ────────────────────────────────────────────────
                PaymentLog.objects.create(
                    claim_attempt=claim_attempt,
                    stripe_event_type=event['type'],
                    stripe_session_id=session['id'],
                    amount_paid=amount_paid,
                    currency=currency,
                    status='succeeded',
                    message=f"Payment succeeded via Stripe. Amount: {amount_paid} {currency}",
                )

                logger.info(f"Payment completed and logged for auction {auction_id}, win {win_id}, amount {amount_paid} {currency}")

            except ClaimAttempt.DoesNotExist:
                logger.error(f"No claim attempt found for win {win_id}, auction {auction_id}")
            except Exception as e:
                logger.error(f"Error processing successful payment: {e}", exc_info=True)

        # Handle other events if needed (optional)
        elif event['type'] == 'checkout.session.expired':
            # Log expired sessions if you want
            session = event['data']['object']
            PaymentLog.objects.create(
                claim_attempt=None,  # may not have claim_attempt yet
                stripe_event_type=event['type'],
                stripe_session_id=session['id'],
                amount_paid=0,
                currency=session['currency'].upper(),
                status='expired',
                message="Checkout session expired without payment"
            )

        return Response(status=200)


class PaymentSuccessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response({"detail": "session_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            win_id = session['metadata'].get('win_id')
            auction_id = session['metadata'].get('auction_id')
            payment_status = session.payment_status

            if payment_status == 'paid':
                try:
                    claim_attempt = ClaimAttempt.objects.select_related('win_record').get(
                        win_record__id=win_id,
                        win_record__auction_id=auction_id
                    )

                    # Update status if not already done (webhook may arrive late)
                    if not claim_attempt.payment_completed:
                        claim_attempt.payment_completed = True
                        claim_attempt.completed_at = timezone.now()
                        claim_attempt.save(update_fields=['payment_completed', 'completed_at'])

                        # Mark the AuctionWin as claimed
                        win = claim_attempt.win_record
                        if not win.claimed:
                            win.claimed = True
                            win.claimed_at = timezone.now()
                            win.save(update_fields=['claimed', 'claimed_at'])

                        # Log the payment (only once – guard against duplicate logs)
                        already_logged = claim_attempt.payment_logs.filter(
                            stripe_session_id=session['id'],
                            status='succeeded'
                        ).exists()
                        if not already_logged:
                            amount_paid = session['amount_total'] / 100
                            currency = session['currency'].upper()
                            PaymentLog.objects.create(
                                claim_attempt=claim_attempt,
                                stripe_event_type='checkout.session.completed',
                                stripe_session_id=session['id'],
                                amount_paid=amount_paid,
                                currency=currency,
                                status='succeeded',
                                message=f"Payment confirmed via success redirect. Amount: {amount_paid} {currency}",
                            )

                        status_msg = "Payment completed and claim updated"
                    else:
                        status_msg = "Payment already confirmed"

                except ClaimAttempt.DoesNotExist:
                    status_msg = "Claim attempt not found"
                except Exception as e:
                    logger.error(f"PaymentSuccessView error updating claim: {e}", exc_info=True)
                    status_msg = "Payment confirmed, but status update failed"
            else:
                status_msg = f"Payment status: {payment_status}"

            return Response({
                "status": session.status,
                "payment_status": payment_status,
                "fulfillment_status": status_msg,
                "auction_id": auction_id
            })
        except stripe.error.StripeError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        



# ─────────────────────────────────────────
# ADMIN AUCTION ORDERS
# ─────────────────────────────────────────
class AdminAuctionOrderListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.winner_claim.models import ClaimAttempt

        queryset = ClaimAttempt.objects.filter(
            payment_completed=True
        ).select_related(
            'win_record__auction',
            'win_record__winner',
        ).prefetch_related(
            'win_record__auction__product_image'
        ).order_by('-completed_at')

        # Filter by delivery status
        status_filter = request.query_params.get('status')
        if status_filter in ['processing', 'delivered']:
            queryset = queryset.filter(delivery_status=status_filter)

        # Search
        search = request.query_params.get('search')
        if search:
            # Strip #ORD- prefix if searching by order_id like "#ORD-5" or "ORD-5" or just "5"
            clean_search = search.strip().lstrip('#').replace('ORD-', '').strip()
            if clean_search.isdigit():
                queryset = queryset.filter(win_record__auction__id=int(clean_search))
            else:
                queryset = queryset.filter(
                    Q(win_record__auction__product_name__icontains=search) |
                    Q(win_record__winner__email__icontains=search) |
                    Q(win_record__winner__first_name__icontains=search) |
                    Q(win_record__winner__last_name__icontains=search)
                )

        data = []
        for claim in queryset:
            win = claim.win_record
            auction = win.auction
            winner = win.winner

            thumbnail = None
            first_image = auction.product_image.first()
            if first_image:
                thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)

            now = timezone.now()
            remaining_seconds = int((win.claim_window_end - now).total_seconds())
            if remaining_seconds > 0:
                hours, remainder = divmod(remaining_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                claiming_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                claiming_time = "Expired"

            winner_name = winner.get_full_name() or winner.email.split('@')[0]

            data.append({
                'claim_id': claim.id,
                'auction_id': auction.id,
                'product_name': auction.product_name,
                'thumbnail': thumbnail,
                'order_id': f"#ORD-{auction.id}",
                'winner_user': winner_name,
                'winner_email': winner.email,
                'current_price': float(win.final_bid_amount),
                'claiming_time': claiming_time,
                'delivery_status': claim.delivery_status,
                'payment_completed': claim.payment_completed,
                'claimed_at': win.claimed_at,
            })

        return Response({'count': len(data), 'results': data})

class AdminAuctionOrderDetailView(APIView):
    """
    GET /api/admin/auction-orders/<claim_id>/
    Returns full auction order detail with user info
    """
    permission_classes = [IsAdminUser]

    def get(self, request, claim_id):
        from apps.winner_claim.models import ClaimAttempt
        from apps.packages.models import CoinTransaction

        claim = get_object_or_404(
            ClaimAttempt.objects.select_related(
                'win_record__auction',
                'win_record__winner',
            ),
            id=claim_id,
            payment_completed=True
        )

        win = claim.win_record
        auction = win.auction
        winner = win.winner

        # ── Product image ──
        images = [
            cloudinary_url(img.image.public_id, secure=True)[0]
            for img in auction.product_image.all()
        ]

        # ── Coin purchase history for this winner ──
        transactions = CoinTransaction.objects.filter(
            user=winner,
            transaction_type='purchase'
        ).order_by('-created_at')

        transaction_data = []
        for i, txn in enumerate(transactions, start=1):
            transaction_data.append({
                'transaction_number': f"#{i * 1000}",
                'amount_sar': float(txn.price_sar),
                'coins_added': txn.amount,
                'date': txn.created_at,
            })

        # ── Claiming time ──
        now = timezone.now()
        remaining_seconds = int((win.claim_window_end - now).total_seconds())
        if remaining_seconds > 0:
            hours, remainder = divmod(remaining_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            claiming_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            claiming_time = "Expired"

        # ── Get winner's default address ──
        address = UserAddress.objects.filter(user=winner).first()

        return Response({
            'claim_id': claim.id,
            'auction_id': auction.id,
            'product_name': auction.product_name,
            'images': images,
            'order_id': f"#ORD-{auction.id}",
            'current_price': float(win.final_bid_amount),
            'claiming_time': claiming_time,
            'delivery_status': claim.delivery_status,
            'claimed_at': win.claimed_at,
            'user_information': {
                'user_id': winner.id,
                'name': winner.get_full_name() or winner.email.split('@')[0],
                'email': winner.email,
                'phone_number': winner.phone_number,
                'street_address': address.street_address if address else None,
                'apartment': address.apartment if address else None,
                'city': address.city if address else None,
                'zip_code': address.zip_code if address else None,
            },
            'transaction_history': transaction_data,
        })


class AdminMarkAuctionDeliveredView(APIView):
    permission_classes = [IsAdminUser]
    """
    PATCH /api/admin/auction-orders/<claim_id>/mark-delivered/
    Admin marks auction order as delivered
    """

    def patch(self, request, claim_id):
        from apps.winner_claim.models import ClaimAttempt

        claim = get_object_or_404(
            ClaimAttempt,
            id=claim_id,
            payment_completed=True
        )

        if claim.delivery_status == 'delivered':
            return Response(
                {'error': 'Order is already delivered'},
                status=status.HTTP_400_BAD_REQUEST
            )

        claim.delivery_status = 'delivered'
        claim.delivery_updated_at = timezone.now()
        claim.save(update_fields=['delivery_status', 'delivery_updated_at'])

        return Response({
            'message': f'Auction order {claim.id} marked as delivered successfully',
            'claim_id': claim.id,
            'delivery_status': claim.delivery_status,
        })
