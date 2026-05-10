from venv import logger
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from django.db import models
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from apps.admin_api.models import Auction, AuctionStatus, Category
from apps.admin_api.serializers import AuctionListSerializer
from apps.packages.models import UserWallet
from apps.users.models import UserAddress
from apps.auction.models import Bid
from apps.users.serializers import AddressListSerializer
from cloudinary.utils import cloudinary_url
import logging
from .models import AuctionNotificationSubscription, AuctionParticipant, AuctionWin
from .serializers import JoinAuctionSerializer, AuctionCardSerializer, AuctionDetailSerializer, UserCategorySerializer, WinnerCheckResponseSerializer, WinnerCheckRequestSerializer, SaveAddressRequestSerializer, CheckoutSummaryRequestSerializer, CheckoutSummaryResponseSerializer, UserAddressSerializer

logger = logging.getLogger(__name__)


class JoinAuctionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = JoinAuctionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        auction_id = serializer.validated_data['auction_id']
        auction = get_object_or_404(Auction, id=auction_id)

        # 1. Must be PUBLISH
        if auction.status != AuctionStatus.PUBLISH:
            return Response({"error": "This auction is not live"}, status=status.HTTP_400_BAD_REQUEST)

        # 2. NEW: Block if auction has ended (time expired)
        start_time = auction.created_at
        end_time = auction.end_time if auction.end_time else (start_time + auction.auction_duration)
        if timezone.now() > end_time:
            # Auto-update status if not already ENDED
            if auction.status != AuctionStatus.ENDED:
                auction.status = AuctionStatus.ENDED
                auction.save(update_fields=['status'])
            return Response({"error": "This auction has ended"}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Already joined check
        if AuctionParticipant.objects.filter(auction=auction, user=request.user).exists():
            return Response({"error": "You already joined this auction"}, status=status.HTTP_400_BAD_REQUEST)

        wallet, _ = UserWallet.objects.get_or_create(user=request.user)

        # 4. Enough coins check
        if wallet.coins < auction.entry_fee_coins:
            return Response({
                "error": f"Not enough coins. Need {auction.entry_fee_coins}, you have {wallet.coins}"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 5. Deduct entry fee
        wallet.coins -= auction.entry_fee_coins
        wallet.save(update_fields=['coins'])

        # 6. Add participant
        AuctionParticipant.objects.create(
            auction=auction,
            user=request.user,
            entry_fee_paid=True
        )

        return Response({
            "message": "Successfully joined the auction",
            "entry_fee_paid": auction.entry_fee_coins,
            "remaining_coins": wallet.coins
        }, status=status.HTTP_201_CREATED)


class LiveAuctionsView(APIView):
    """
    GET: List all truly live (published & not ended) auctions for users
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Only show PUBLISH and not ended
        auctions = Auction.objects.filter(status=AuctionStatus.PUBLISH)

        # Optional: exclude ended by time (extra safety)
        now = timezone.now()
        auctions = auctions.annotate(
            end_time_calc=models.F('created_at') + models.F('auction_duration')
        ).filter(end_time_calc__gt=now)

        # Pass request so has_participated can check authenticated user
        serializer = AuctionCardSerializer(auctions, many=True, context={'request': request})
        return Response({
            "section": "Live Auctions",
            "auctions": serializer.data
        })


class UpcomingAuctionsView(APIView):
    """
    GET: List all upcoming (scheduled) auctions for users
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        auctions = Auction.objects.filter(status=AuctionStatus.SCHEDULE)
        # Pass request so has_participated can check authenticated user
        serializer = AuctionCardSerializer(auctions, many=True, context={'request': request})
        return Response({
            "section": "Upcoming",
            "auctions": serializer.data
        })
    

class AuctionDetailView(APIView):
    """
    POST: Get detailed view of a single auction
    Body: {"auction_id": 33}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        auction_id = request.data.get('auction_id')
        if not auction_id:
            return Response({"error": "auction_id is required in body"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            auction_id = int(auction_id)
        except (ValueError, TypeError):
            return Response({"error": "auction_id must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        auction = get_object_or_404(Auction, id=auction_id)

        serializer = AuctionDetailSerializer(auction, context={'request': request})

        return Response(serializer.data, status=status.HTTP_200_OK)


class UserConcludedAuctionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        now = timezone.now()
        
        auctions = Auction.objects.annotate(
            actual_end_time=models.Case(
                models.When(end_time__isnull=False, then=models.F('end_time')),
                default=models.F('created_at') + models.F('auction_duration'),
                output_field=models.DateTimeField(),
            )
        ).filter(
            Q(status=AuctionStatus.ENDED) |
            Q(status=AuctionStatus.PUBLISH, actual_end_time__lte=now)
        ).distinct().order_by('-actual_end_time')

        from .serializers import UserBidHistoryFormatSerializer
        serializer = UserBidHistoryFormatSerializer(auctions, many=True, context={'request': request})
        
        return Response(serializer.data, status=status.HTTP_200_OK)
    


class WinnerCheckView(APIView):
    """
    POST body: {"auction_id": 68}
    Returns whether current user is winner and if they have saved address
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WinnerCheckRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        auction_id = serializer.validated_data['auction_id']
        auction = Auction.objects.filter(id=auction_id).first()

        if not auction:
            return Response({"error": "Auction not found"}, status=status.HTTP_404_NOT_FOUND)

        win = AuctionWin.objects.filter(auction=auction, winner=request.user).first()

        if not win:
            return Response({"error": "You are not the winner of this auction"}, 
                            status=status.HTTP_403_FORBIDDEN)

        if not win.is_claim_window_open():
            return Response({"error": "Claim window has expired"}, 
                            status=status.HTTP_403_FORBIDDEN)

        has_address = UserAddress.objects.filter(user=request.user).exists()

        bid_coins_used = Bid.objects.filter(
            auction=auction,
            user=request.user
        ).aggregate(total=Sum('coins_deducted'))['total'] or 0

        # Calculate remaining time string
        remaining = win.claim_window_end - timezone.now()
        days, seconds = divmod(remaining.total_seconds(), 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        remaining_str = f"{int(days)} day{'s' if days != 1 else ''} {int(hours)} hour{'s' if hours != 1 else ''} {int(minutes)} min{'s' if minutes != 1 else ''}".strip()

        data = {
            "is_winner": True,
            "auction_id": auction.id,
            "product_name": auction.product_name,
            "final_bid": win.final_bid_amount,
            "bid_coins_used": bid_coins_used,
            "has_address": has_address,
            "claim_window_end": win.claim_window_end,
            "claim_window_remaining": remaining_str or "Less than 1 minute"
        }

        return Response(WinnerCheckResponseSerializer(data).data)


class SaveAddressView(APIView):
    """
    POST: Save new shipping address for current user
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SaveAddressRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        address = serializer.save(user=request.user)

        # If this is the first address → make it default
        if UserAddress.objects.filter(user=request.user).count() == 1:
            address.is_default = True
            address.save()

        return Response(UserAddressSerializer(address).data, status=status.HTTP_201_CREATED)


class CheckoutSummaryView(APIView):
    """
    POST body: {"auction_id": 68}
    Returns checkout summary for winner
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSummaryRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        auction_id = serializer.validated_data['auction_id']
        auction = Auction.objects.filter(id=auction_id).first()

        if not auction:
            return Response({"error": "Auction not found"}, status=status.HTTP_404_NOT_FOUND)

        win = AuctionWin.objects.filter(auction=auction, winner=request.user).first()

        if not win:
            return Response({"error": "You are not the winner of this auction"}, 
                            status=status.HTTP_403_FORBIDDEN)

        if not win.is_claim_window_open():
            return Response({"error": "Claim window has expired"}, 
                            status=status.HTTP_403_FORBIDDEN)

        # Calculate bid coins used
        bid_coins_used = Bid.objects.filter(
            auction=auction,
            user=request.user
        ).aggregate(total=Sum('coins_deducted'))['total'] or 0

        # Example total amount (adjust based on your business logic)
        total_amount = auction.auction_price - bid_coins_used

        # ────────────────────────────────────────────────
        # Get all addresses for the user
        # ────────────────────────────────────────────────
        addresses = UserAddress.objects.filter(user=request.user).order_by('-is_default', '-created_at')
        
        # Get default address (first one with is_default=True, or just the first one)
        default_address = addresses.filter(is_default=True).first() or addresses.first()

        data = {
            "auction_id": auction.id,
            "product_name": auction.product_name,
            "auction_price": auction.auction_price,
            "final_bid": win.final_bid_amount,
            "bid_coins_used": bid_coins_used,
            "total_amount": total_amount,
            "selected_address": UserAddressSerializer(default_address).data if default_address else None,
            "all_addresses": AddressListSerializer(addresses, many=True).data
        }

        return Response(CheckoutSummaryResponseSerializer(data).data)



class BiddingHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get_product_image_url(self, obj):
        if obj.product_image:
            url, _ = cloudinary_url(obj.product_image.public_id, secure=True)
            return url
        return None

    def get(self, request):
        user = request.user

        auctions = Auction.objects.filter(
            bids__user=user
        ).distinct().order_by('-last_bid_time')

        result = []
        now = timezone.now()

        for auction in auctions:
            user_bids = Bid.objects.filter(auction=auction, user=user)
            bids_count = user_bids.count()
            coins_spent = user_bids.aggregate(total=Sum('coins_deducted'))['total'] or 0

            win = AuctionWin.objects.filter(auction=auction, winner=user).first()
            is_winner = bool(win)

            if is_winner:
                status = "won"
                remaining = win.claim_window_end - now
                if remaining.total_seconds() > 0:
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    claim_remaining = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    must_claim_by = claim_remaining
                else:
                    claim_remaining = "Expired"
                    must_claim_by = "Expired"
            else:
                status = "lost"
                claim_remaining = None
                must_claim_by = None

            data = {
                "auction_id": auction.id,
                "product_name": auction.product_name,
                "product_image_url": self.get_product_image_url(auction) or "https://via.placeholder.com/300",
                "auction_price": auction.auction_price,
                "market_price": auction.market_price,
                "save_amount": auction.market_price - auction.auction_price,
                "status": status,
                "user_bids_count": bids_count,
                "user_coins_spent": coins_spent,
                "is_winner": is_winner,
                "claim_window_remaining": claim_remaining,
                "claim_window_end": win.claim_window_end if win else None,
                "must_claim_by": must_claim_by,
                "description": auction.description[:100] + "..." if auction.description else None
            }
            result.append(data)

        return Response({
            "section": "Bidding History",
            "auctions": result
        })
    

class UserCategoryListAPIView(APIView):
    """
    GET /api/auction/categories/
    Returns categories + live auction count
    """
    permission_classes = []

    def get(self, request):
        now = timezone.now()

        categories = Category.objects.filter(
            is_active=True,
            category_for='auction'  # optional but recommended
        ).annotate(
            auction_count=Count(
                'auctions',  
                filter=Q(
                    auctions__status=AuctionStatus.PUBLISH,
                    auctions__end_time__gt=now
                )
            )
        ).order_by('name')

        return Response({
            "count": categories.count(),
            "results": UserCategorySerializer(categories, many=True).data
        }, status=status.HTTP_200_OK)



class UserAuctionListAPIView(APIView):
    """
    GET /api/auctions/
    GET /api/auctions/?category=car
    GET /api/auctions/?category=3
    """
    permission_classes = []  # Public

    def get(self, request):
        now = timezone.now()
        category = request.query_params.get('category')

        auctions = Auction.objects.filter(
            status=AuctionStatus.PUBLISH,
            end_time__gt=now
        ).select_related('category').prefetch_related('product_image')

        if category:
            if category.isdigit():
                auctions = auctions.filter(category_id=category)
            else:
                auctions = auctions.filter(
                    category__name__iexact=category
                )

        serializer = AuctionListSerializer(auctions, many=True)

        return Response({
            "count": auctions.count(),
            "results": serializer.data
        }, status=status.HTTP_200_OK)
    

class AuctionNotifyMeView(APIView):
    """
    POST /api/auction/notify-me/
    
    Body: {"auction_id": 123}
    
    Subscribes authenticated user to get push notification when this upcoming auction starts.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        auction_id = request.data.get('auction_id')

        # Validate input
        if not auction_id:
            return Response(
                {"error": "auction_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            auction_id = int(auction_id)
        except (ValueError, TypeError):
            return Response(
                {"error": "auction_id must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST
            )

        auction = get_object_or_404(Auction, id=auction_id)

        # Only allow for upcoming auctions
        if auction.status != AuctionStatus.SCHEDULE:
            return Response(
                {"error": "You can only subscribe to upcoming (scheduled) auctions"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Subscribe (or skip if already subscribed)
        subscription, created = AuctionNotificationSubscription.objects.get_or_create(
            auction=auction,
            user=request.user
        )

        if created:
            logger.info(f"User {request.user.email} subscribed to auction {auction.id}")
            message = "Successfully subscribed. You will be notified when the auction starts."
            status_code = status.HTTP_201_CREATED
        else:
            message = "You are already subscribed to notifications for this auction."
            status_code = status.HTTP_200_OK

        return Response(
            {
                "message": message,
                "auction_id": auction.id,
                "product_name": auction.product_name,
                "already_subscribed": not created
            },
            status=status_code
        )


class UserBidHistoryListAPIView(APIView):
    """
    GET /api/auction/user-history/
    Returns user's bid history in the requested JSON format.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Get auctions where user has bid
        auctions = Auction.objects.filter(
            bids__user=user
        ).distinct().order_by('-created_at')

        # Use the specific context for status calculation
        from .serializers import UserBidHistoryFormatSerializer
        serializer = UserBidHistoryFormatSerializer(auctions, many=True, context={'request': request})
        
        return Response(serializer.data, status=status.HTTP_200_OK)