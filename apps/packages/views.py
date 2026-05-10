import stripe
from django.db import models
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from django.shortcuts import get_object_or_404
from .models import UserWallet
from apps.admin_api.models import CoinPackage
from apps.winner_claim.models import ClaimAttempt, PaymentLog
from django.utils import timezone

from .serializers import WalletSerializer, CoinPackageListSerializer, BuyCoinPackageSerializer

stripe.api_key = settings.STRIPE_SECRET_KEY

class UserWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet, created = UserWallet.objects.get_or_create(user=request.user)
        serializer = WalletSerializer(wallet)
        return Response(serializer.data)
    

class CoinPackagesUserView(APIView):
    """
    GET: List all active coin packages for user to buy
    """
    def get(self, request):
        packages = CoinPackage.objects.filter(is_active=True)
        serializer = CoinPackageListSerializer(packages, many=True)
        return Response(serializer.data)


class CreateCheckoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = BuyCoinPackageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        package_id = serializer.validated_data['package_id']
        package = get_object_or_404(CoinPackage, id=package_id, is_active=True)

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price_data': {
                            'currency': 'sar',
                            'product_data': {'name': f"{package.coins} Coins"},
                            'unit_amount': int(package.price_sar * 100),
                        },
                        'quantity': 1,
                    }
                ],
                mode='payment',
                success_url=f"{request.build_absolute_uri('/api/packages/checkout-success/')}?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=request.build_absolute_uri('/api/packages/'),
                metadata={
                    'payment_type': 'coin_package', 
                    'user_id': str(request.user.id),
                    'package_id': str(package.id),
                    'coins_to_add': package.coins,
                }
            )

            return Response({
                'session_id': session.id,
                'checkout_url': session.url
            }, status=status.HTTP_200_OK)

        except stripe.error.StripeError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


def fulfill_coin_purchase(session_id, user_id, coins_to_add, price_sar=0):
    from .models import CoinTransaction, UserWallet
    from django.db import transaction

    with transaction.atomic():
        if CoinTransaction.objects.filter(reference_id=session_id, reference_type='stripe_session').exists():
            return False

        wallet, _ = UserWallet.objects.get_or_create(user_id=user_id)
        wallet.coins += coins_to_add
        wallet.save(update_fields=['coins'])

        CoinTransaction.objects.create(
            user_id=user_id,
            transaction_type='purchase',
            amount=coins_to_add,
            price_sar=price_sar,
            description=f"Purchased {coins_to_add} coins via Stripe",
            reference_id=session_id,
            reference_type='stripe_session'
        )
        return True


class StripeWebhookView(APIView):
    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            return Response(status=400)

        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            metadata = session.get('metadata', {})

            # ── Check what type of payment this is ──
            order_id = metadata.get('order_id')
            user_id = metadata.get('user_id')
            coins_to_add = int(metadata.get('coins_to_add', 0))
            payment_type = metadata.get('payment_type') 
            if order_id:
                try:
                    from apps.products.models import Order, OrderStatus
                    from apps.cart.models import Cart

                    order = Order.objects.get(id=order_id)
                    order.payment_status = 'paid'
                    order.status = OrderStatus.PROCESSING
                    order.payment_method = session.get(
                        'payment_method_types', ['card']
                    )[0]
                    order.save(update_fields=[
                        'payment_status', 'status', 'payment_method'
                    ])

                    # Clear cart only after successful payment
                    if not order.is_buy_now:
                        try:
                            cart = Cart.objects.get(user=order.user)
                            cart.items.filter(is_selected=True).delete()
                        except Cart.DoesNotExist:
                            pass

                except Order.DoesNotExist:
                    pass

            #  COIN PACKAGE PAYMENT
            elif user_id and coins_to_add > 0:
                amount_sar = session.get('amount_total', 0) / 100.0
                fulfill_coin_purchase(
                    session.id, user_id, coins_to_add, price_sar=amount_sar
                )

            # WINNER CLAIM PAYMENT
            elif payment_type == 'winner_claim':
                win_id = metadata.get('win_id')
                auction_id = metadata.get('auction_id')
                amount_paid = session['amount_total'] / 100
                currency = session['currency'].upper()

                try:
                    claim_attempt = ClaimAttempt.objects.get(
                        win_record__id=win_id,
                        win_record__auction_id=auction_id
                    )
                    if not claim_attempt.payment_completed:
                        claim_attempt.payment_completed = True
                        claim_attempt.completed_at = timezone.now()
                        claim_attempt.save()

                        claim_attempt.win_record.claimed = True
                        claim_attempt.win_record.claimed_at = timezone.now()
                        claim_attempt.win_record.save()

                        PaymentLog.objects.create(
                            claim_attempt=claim_attempt,
                            stripe_event_type=event['type'],
                            stripe_session_id=session['id'],
                            amount_paid=amount_paid,
                            currency=currency,
                            status='succeeded',
                            message=f"Payment succeeded via Stripe. Amount: {amount_paid} {currency}",
                        )
                except ClaimAttempt.DoesNotExist:
                    pass

            # COIN PACKAGE PAYMENT
            elif user_id and coins_to_add > 0:
                amount_sar = session.get('amount_total', 0) / 100.0
                fulfill_coin_purchase(
                    session.id, user_id, coins_to_add, price_sar=amount_sar
                )    

        return Response(status=200)

class CoinPurchaseHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import CoinTransaction
        from .serializers import CoinTransactionSerializer
        
        transactions = CoinTransaction.objects.filter(
            user=request.user,
            transaction_type='purchase'
        )
        serializer = CoinTransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class CoinExpenseHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import CoinTransaction
        from .serializers import CoinTransactionSerializer
        
        transactions = CoinTransaction.objects.filter(
            user=request.user,
            transaction_type__in=['bid', 'entry_fee']
        )
        serializer = CoinTransactionSerializer(transactions, many=True)
        
        total_in = request.user.coin_transactions.filter(
            transaction_type__in=['purchase', 'refund']
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        total_out = request.user.coin_transactions.filter(
            transaction_type__in=['bid', 'entry_fee']
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        return Response({
            "transactions": serializer.data,
            "total_in": total_in,
            "total_out": total_out
        })


class CheckoutSuccessView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        session_id = request.query_params.get('session_id')
        if not session_id:
            return Response(
                {"detail": "session_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = session.get('metadata', {})
            order_id = metadata.get('order_id')
            user_id = metadata.get('user_id')
            coins_to_add = int(metadata.get('coins_to_add', 0))

            if session.payment_status == 'paid':

               
                if order_id:
                    from apps.products.models import Order, OrderStatus
                    from apps.cart.models import Cart

                    try:
                        order = Order.objects.get(id=order_id)

                        if order.payment_status != 'paid':
                            order.payment_status = 'paid'
                            order.status = OrderStatus.PROCESSING
                            order.save(update_fields=['payment_status', 'status'])

                            if not order.is_buy_now:
                                try:
                                    cart = Cart.objects.get(user=order.user)
                                    cart.items.filter(is_selected=True).delete()
                                except Cart.DoesNotExist:
                                    pass

                        return Response({
                            'payment_status': 'paid',
                            'order_id': order.id,
                            'tracking_id': order.tracking_id,
                            'status': order.status,
                            'total_amount': float(order.total_amount),
                        })

                    except Order.DoesNotExist:
                        return Response(
                            {'error': 'Order not found'},
                            status=status.HTTP_404_NOT_FOUND
                        )

                elif user_id and coins_to_add > 0:
                    amount_sar = session.get('amount_total', 0) / 100.0
                    fulfilled = fulfill_coin_purchase(
                        session.id, user_id, coins_to_add, price_sar=amount_sar
                    )
                    status_msg = "Coins fulfilled successfully" if fulfilled else "Coins already fulfilled"

                    return Response({
                        "status": session.status,
                        "payment_status": session.payment_status,
                        "fulfillment_status": status_msg,
                        "coins_added": coins_to_add
                    })

            return Response({
                "payment_status": session.payment_status,
                "message": "Payment not completed"
            })

        except stripe.error.StripeError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )