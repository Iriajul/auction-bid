from asyncio.log import logger
from apps.products.models import Order  
from django.db.models import F, ExpressionWrapper, DateTimeField, Sum, Q, Count  
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.generics import GenericAPIView, UpdateAPIView
from apps.common.pagination import AdminParticipantPagination
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from apps.users.models import UserNotification
from cloudinary.utils import cloudinary_url
from dateutil.relativedelta import relativedelta
from django.db.models import F, Sum              
from asgiref.sync import async_to_sync
from apps.auction.models import AuctionNotificationSubscription, AuctionParticipant, AuctionWin, Bid
from apps.auction.socket import User, end_auction_and_refund
#from apps.packages import serializers
from rest_framework.exceptions import ValidationError
from apps.packages import models
from apps.packages.models import UserWallet
from .models import AuctionImage, Category, Auction, AuctionStatus, CoinPackage, Announcement
from .serializers import (
    AdminLoginSerializer,
    CategorySerializer,
    CategoryEditSerializer,
    CategoryDeleteSerializer,
    AuctionCreateSerializer,
    AuctionListSerializer,
    CoinPackageSerializer, 
    CoinPackageCreateSerializer,
    CoinPackageEditSerializer,
    AdminUserListSerializer,
    AdminUserAuctionHistorySerializer,
    AdminUserTransactionHistorySerializer,
    AdminUserDetailsSerializer,
    AdminProfileUpdateSerializer,
    AdminProfileSerializer,
    AdminChangePasswordSerializer,
    CoinStatsSerializer,
    AnnouncementSerializer
)
from rest_framework.generics import ListAPIView
from apps.users.models import User
from .models import Category, Auction, AuctionStatus, CoinPackage
from apps.packages.models import CoinTransaction
from django.db.models import Sum, F


class AdminLoginView(GenericAPIView):
    """
    Admin sign-in endpoint
    - Uses email + password
    - Only allows users with is_staff=True
    - Returns JWT access & refresh tokens
    """
    serializer_class = AdminLoginSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = AdminParticipantPagination

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()] 
        return [IsAdminUser()] 

    def get_queryset(self):
        queryset = Category.objects.all()

        # 🔍 Filter by category_for
        category_for = self.request.query_params.get('category_for')
        if category_for in ['physical', 'digital', 'auction']:
            queryset = queryset.filter(category_for=category_for)

        # 🔍 Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(
                is_active=is_active.lower() == 'true'
            )

        # 🔍 Optional search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset.order_by('name')

class CategoryEditView(generics.GenericAPIView):
    """
    PATCH: Edit category
    Body: {"category_id": 5, "name": "New Name", "category_for": "digital"}
    """
    permission_classes = [IsAdminUser]

    def patch(self, request):
        serializer = CategoryEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        category = get_object_or_404(Category, id=serializer.validated_data['category_id'])

        # Update allowed fields only
        if 'name' in serializer.validated_data:
            category.name = serializer.validated_data['name']

        if 'category_for' in serializer.validated_data:
            category.category_for = serializer.validated_data['category_for']

        category.save()

        return Response(CategorySerializer(category).data, status=200)
    
class CategoryToggleActiveView(APIView):
    """
    POST /api/admin/categories/toggle-active/
    Body: {"category_id": 5, "is_active": true/false}
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        category_id = request.data.get('category_id')
        is_active = request.data.get('is_active')

        if category_id is None or is_active is None:
            return Response({"error": "category_id and is_active are required"}, status=400)

        category = get_object_or_404(Category, id=category_id)
        category.is_active = bool(is_active)
        category.save(update_fields=['is_active'])

        return Response({
            "message": f"Category '{category.name}' is now {'active' if is_active else 'inactive'}",
            "is_active": category.is_active
        }, status=200)


class CategoryDeleteView(generics.GenericAPIView):
    """
    DELETE: Delete category
    Body: {"category_id": 5}
    Returns success message with deleted category name
    """
    permission_classes = [IsAdminUser]
    serializer_class = CategoryDeleteSerializer

    def delete(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        category_id = serializer.validated_data['category_id']
        category = get_object_or_404(Category, id=category_id)

        deleted_name = category.name

        category.delete()

        return Response(
            {
                "message": f"{deleted_name} Category deleted successfully"
            },
            status=status.HTTP_200_OK
        )


class AuctionListCreateView(generics.ListCreateAPIView):
    """
    GET: List auctions (filtered or all)
    POST: Create auction
    """
    queryset = Auction.objects.all().prefetch_related('product_image')
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AuctionCreateSerializer
        return AuctionListSerializer

    def get_queryset(self):
        queryset = Auction.objects.all()
        self.filter_type = self.request.query_params.get('filter')
        now = timezone.now()
        
        # Annotate calculated_end_time
        queryset = queryset.annotate(
            calculated_end_time=ExpressionWrapper(
                F('created_at') + F('auction_duration'),
                output_field=DateTimeField()
            )
        )

        if self.filter_type in ['live', 'publish']:
            # Filter live auctions based on calculated end time
            queryset = queryset.filter(
                status=AuctionStatus.PUBLISH,
                calculated_end_time__gt=now
            )

        elif self.filter_type in ['upcoming', 'schedule']:
            queryset = queryset.filter(
                status=AuctionStatus.SCHEDULE
            )
        elif self.filter_type == 'ended':
            queryset = queryset.filter(
                status=AuctionStatus.ENDED
            )
        elif self.filter_type == 'invalid':
            queryset = queryset.filter(
                wins__claimed=False,
                wins__claim_window_end__lt=now
            ).distinct()

        return queryset.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        response = {
            "filter": self.filter_type or "all",
            "count": queryset.count(),
            "results": serializer.data
        }

        return Response(response, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        auction = serializer.save(created_by=self.request.user)

        if auction.status == AuctionStatus.PUBLISH and not auction.end_time:
            auction.end_time = timezone.now() + auction.auction_duration
            auction.save(update_fields=['end_time'])

class AuctionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET: Get single auction
    PATCH: Update auction (e.g. continue draft)
    DELETE: Delete auction
    """
    queryset = Auction.objects.all()
    serializer_class = AuctionCreateSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'id'


class CoinPackageListCreateView(generics.ListCreateAPIView):
    """
    GET: List all coin packages (for admin)
    POST: Create new coin package
    """
    queryset = CoinPackage.objects.all()
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CoinPackageCreateSerializer
        return CoinPackageSerializer


class CoinPackageToggleActiveView(generics.GenericAPIView):
    """
    PATCH: Toggle active/paused status
    Body: {"package_id": 1, "is_active": true/false}
    """
    permission_classes = [IsAdminUser]

    def patch(self, request):
        package_id = request.data.get('package_id')
        is_active = request.data.get('is_active')

        if package_id is None or is_active is None:
            return Response({"error": "package_id and is_active are required"}, status=status.HTTP_400_BAD_REQUEST)

        package = get_object_or_404(CoinPackage, id=package_id)
        package.is_active = bool(is_active)
        package.save(update_fields=['is_active'])

        return Response(CoinPackageSerializer(package).data, status=status.HTTP_200_OK)



class CoinPackageEditView(generics.GenericAPIView):
    """
    PATCH: Edit coin package
    Body: {"package_id": 1, "coins": 150, "price_sar": 150.00}
    """
    permission_classes = [IsAdminUser]

    def patch(self, request):
        serializer = CoinPackageEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        package_id = serializer.validated_data['package_id']
        package = get_object_or_404(CoinPackage, id=package_id)

        # Update only provided fields
        if 'coins' in serializer.validated_data:
            package.coins = serializer.validated_data['coins']
        if 'price_sar' in serializer.validated_data:
            package.price_sar = serializer.validated_data['price_sar']

        package.save()

        return Response(CoinPackageSerializer(package).data, status=status.HTTP_200_OK)
    


class AuctionDetailAdminView(APIView):
    """
    GET /api/admin/auctions/detail/?auction_id=74
    Returns full auction details + paginated participant list + bid leader + winner info
    
    For upcoming auctions: shows "Notify Me" subscribers with coin balance (others N/A)
    For live/ended: shows joined participants + leader/winner
    """
    permission_classes = [IsAdminUser]
    pagination_class = AdminParticipantPagination

    def get(self, request):
        auction_id = request.query_params.get('auction_id')
        if not auction_id:
            return Response({"error": "auction_id is required"}, status=400)

        try:
            auction_id = int(auction_id)
        except ValueError:
            return Response({"error": "auction_id must be integer"}, status=400)

        auction = get_object_or_404(Auction, id=auction_id)

        # ---------------- AUCTION DURATION ----------------
        total_seconds = int(auction.auction_duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        auction_duration = {
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds
        }

        # ---------------- AUCTION INFO ----------------
        auction_data = {
            "auction_id": auction.id,
            "product_name": auction.product_name,
            "category_name": auction.category.name if auction.category else "N/A",
            "product_image_url": [
                cloudinary_url(img.image.public_id, secure=True)[0]
                for img in auction.product_image.all()
            ],
            "auction_price": auction.auction_price,
            "market_price": auction.market_price,
            "status": auction.status,
            "created_at": auction.created_at,
            "auction_duration": auction_duration,
            "participant_count": AuctionParticipant.objects.filter(auction=auction).count(),
            "remaining_time": "Ended"  # will be updated below
        }

        # ---------------- REMAINING TIME (NO DAYS) ----------------
        now = timezone.now()

        def format_remaining(seconds: int) -> str:
            if seconds <= 0:
                return "Ended"
            
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            parts = []
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0:
                parts.append(f"{minutes}m")
            parts.append(f"{seconds}s")  # always show seconds
            
            return " ".join(parts)

        if auction.status == AuctionStatus.PUBLISH:
            end_time = auction.end_time or (auction.created_at + auction.auction_duration)
            remaining_seconds = int((end_time - now).total_seconds())
            auction_data["remaining_time"] = format_remaining(remaining_seconds)
        elif auction.status == AuctionStatus.SCHEDULE:
            if auction.scheduled_time:
                remaining_seconds = int((auction.scheduled_time - now).total_seconds())
                auction_data["remaining_time"] = format_remaining(remaining_seconds)
            else:
                auction_data["remaining_time"] = "Upcoming"
        else:
            auction_data["remaining_time"] = "Ended"
        # ────────────────────────────────────────────────
        # BID LEADER (only for live / PUBLISH auctions)
        # ────────────────────────────────────────────────
        bid_leader = None
        if auction.status == AuctionStatus.PUBLISH and auction.current_bid > 0:
            leader_bid = Bid.objects.filter(
                auction=auction,
                bid_number=auction.current_bid
            ).select_related('user').first()

            if leader_bid:
                bid_leader = {
                    "user_id": leader_bid.user.id,
                    "user_name": leader_bid.user.get_full_name() or leader_bid.user.email.split('@')[0],
                    "user_email": leader_bid.user.email,
                    "bid_number": leader_bid.bid_number,
                    "bid_at": leader_bid.bid_at.isoformat()
                }

        # ────────────────────────────────────────────────
        # WINNER INFO (only for ended auctions)
        # ────────────────────────────────────────────────
        winner_info = None
        if auction.status == AuctionStatus.ENDED:
            win_record = AuctionWin.objects.filter(auction=auction).first()
            if win_record:
                winner_info = {
                    "winner_id": win_record.winner.id,
                    "winner_name": win_record.winner.get_full_name() or win_record.winner.email.split('@')[0],
                    "winner_email": win_record.winner.email,
                    "final_bid_amount": float(win_record.final_bid_amount),
                    "claimed": win_record.claimed,
                    "claimed_at": win_record.claimed_at.isoformat() if win_record.claimed_at else None,
                    "claim_window_end": win_record.claim_window_end.isoformat()
                }

        # ────────────────────────────────────────────────
        # PARTICIPANTS / NOTIFY ME SUBSCRIBERS
        # ────────────────────────────────────────────────
        if auction.status == AuctionStatus.SCHEDULE:
            # Upcoming: show "Notify Me" subscribers (not real participants)
            notify_subscriptions = AuctionNotificationSubscription.objects.filter(
                auction=auction
            ).select_related('user').order_by('-subscribed_at')

            paginator = self.pagination_class()
            page = paginator.paginate_queryset(notify_subscriptions, request)

            participants_data = []

            for sub in page:
                wallet = UserWallet.objects.filter(user=sub.user).first()
                coin_balance = wallet.coins if wallet else 0

                participants_data.append({
                    "user_id": sub.user.id,
                    "user_name": sub.user.get_full_name() or sub.user.email.split('@')[0],
                    "user_email": sub.user.email,
                    "avatar_url": None,
                    "status": "Notify Me Subscriber",
                    "coin_balance": coin_balance,
                    "refundable_coin": "N/A",
                    "bids_count": "N/A",
                    "total_coins_spent": "N/A"
                })

            participants_response = paginator.get_paginated_response(participants_data).data

        else:
            # Live / Ended / Invalid: show real joined participants
            participants_qs = AuctionParticipant.objects.filter(
                auction=auction
            ).select_related('user').order_by('-joined_at')

            paginator = self.pagination_class()
            page = paginator.paginate_queryset(participants_qs, request)

            participants_data = []

            for p in page:
                wallet = UserWallet.objects.filter(user=p.user).first()
                coin_balance = wallet.coins if wallet else 0

                bids = Bid.objects.filter(auction=auction, user=p.user)
                bids_count = bids.count()
                total_coins_spent = bids.aggregate(total=Sum('coins_deducted'))['total'] or 0

                is_winner = AuctionWin.objects.filter(
                    auction=auction,
                    winner=p.user
                ).exists()

                participants_data.append({
                    "user_id": p.user.id,
                    "user_name": p.user.get_full_name() or p.user.email.split('@')[0],
                    "user_email": p.user.email,
                    "avatar_url": None,
                    "status": "Winner" if is_winner else "Participant",
                    "coin_balance": coin_balance,
                    "refundable_coin": 0 if is_winner else total_coins_spent,
                    "bids_count": bids_count,
                    "total_coins_spent": total_coins_spent
                })

            participants_response = paginator.get_paginated_response(participants_data).data

        # ────────────────────────────────────────────────
        # FINAL RESPONSE
        # ────────────────────────────────────────────────
        return Response({
            "auction": auction_data,
            "bid_leader": bid_leader,
            "winner_info": winner_info,
            "participants": participants_response
        }, status=200)
    
class EndAuctionView(APIView):
    """
    POST /api/admin/auctions/end/
    Body: {"auction_id": 74}
    
    Ends a LIVE auction immediately
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        auction_id = request.data.get('auction_id')
        if not auction_id:
            return Response({"error": "auction_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        auction = get_object_or_404(Auction, id=auction_id)

        if auction.status != AuctionStatus.PUBLISH:
            return Response(
                {"error": "Only live (published) auctions can be ended manually"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark as ended immediately
        auction.status = AuctionStatus.ENDED
        auction.end_time = timezone.now()
        auction.save(update_fields=['status', 'end_time'])

        # Run refund + winner logic (same as Celery task)
        try:
            # Find winner
            highest_bid = Bid.objects.filter(auction=auction).order_by('-bid_number').first()
            winner = highest_bid.user if highest_bid else None

            if winner:
                # Create win record if not exists
                AuctionWin.objects.get_or_create(
                    auction=auction,
                    winner=winner,
                    defaults={
                        'final_bid_amount': auction.current_bid,
                        'claim_window_end': timezone.now() + auction.winning_claim_window
                    }
                )

            # Refund bidders (properly aggregate all bids)
            # 1. Get total coins per user for this auction
            bidders_query = Bid.objects.filter(auction=auction)
            if winner:
                bidders_query = bidders_query.exclude(user=winner)
            
            # Aggregate total coins to refund per user
            refund_stats = bidders_query.values('user').annotate(total_refund=Sum('coins_deducted'))
            
            for entry in refund_stats:
                user_id = entry['user']
                refund_amount = entry['total_refund']
                
                if refund_amount > 0:
                    # Update Wallet
                    UserWallet.objects.filter(user_id=user_id).update(
                        coins=F('coins') + refund_amount
                    )
                    
                    # Create Transaction Log
                    CoinTransaction.objects.create(
                        user_id=user_id,
                        transaction_type='refund',
                        amount=refund_amount,
                        reference_id=auction.id,
                        reference_type='auction_refund',
                        description=f"Manual Refund for bids in Auction #{auction.id} ({auction.product_name})"
                    )


            # Emit socket events
            async_to_sync(end_auction_and_refund)(auction.id)

            return Response({
                "message": f"Auction {auction_id} has been ended successfully",
                "status": "ended"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": f"Failed to end auction: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DeleteAuctionView(APIView):
    """
    POST /api/admin/auctions/delete/
    Body: {"auction_id": 74}
    
    Deletes an UPCOMING (scheduled) auction
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        auction_id = request.data.get('auction_id')
        if not auction_id:
            return Response({"error": "auction_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        auction = get_object_or_404(Auction, id=auction_id)

        if auction.status != AuctionStatus.SCHEDULE:
            return Response(
                {"error": "Only upcoming (scheduled) auctions can be deleted"},
                status=status.HTTP_400_BAD_REQUEST
            )

        deleted_name = auction.product_name
        auction.delete()

        return Response({
            "message": f"Auction '{deleted_name}' (ID {auction_id}) has been deleted",
            "status": "deleted"
        }, status=status.HTTP_200_OK)
    

class AuctionUpdateView(UpdateAPIView):
    """
    PATCH /api/admin/auctions/<int:pk>/update/

    Update an upcoming (scheduled) auction.
    - Only allowed if status = SCHEDULE
    - Admin can publish directly (no scheduled_time needed)
    """
    queryset = Auction.objects.filter(status=AuctionStatus.SCHEDULE)
    serializer_class = AuctionCreateSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'id'

    def get_object(self):
        auction = get_object_or_404(Auction, id=self.kwargs['pk'])

        if auction.status != AuctionStatus.SCHEDULE:
            raise ValidationError({
                "detail": "Only upcoming (scheduled) auctions can be edited."
            })

        return auction

    def perform_update(self, serializer):
        auction = self.get_object()
        product_images = self.request.FILES.getlist('product_images')
        new_status = self.request.data.get('status', auction.status)

        #  Admin publishes auction 
        if new_status == AuctionStatus.PUBLISH:
            auction = serializer.save(
                status=AuctionStatus.PUBLISH,
                scheduled_time=None
            )

            # set end_time when publishing
            if not auction.end_time:
                auction.end_time = timezone.now() + auction.auction_duration
                auction.save(update_fields=['end_time'])

        # Still scheduled → scheduled_time REQUIRED
        else:
            scheduled_time = self.request.data.get('scheduled_time')
            if not scheduled_time:
                raise ValidationError({
                    "scheduled_time": "scheduled_time is required for upcoming auctions."
                })

            serializer.save(
                status=AuctionStatus.SCHEDULE,
                scheduled_time=scheduled_time
            )

        if product_images:
        #  delete old images
            auction.product_image.all().delete()

            for img in product_images:
                AuctionImage.objects.create(
                    auction=auction,
                    image=img
                )
                            

        logger.info(
            f"Auction {auction.id} updated by admin {self.request.user.email}"
        )


class AdminUserManagementView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = User.objects.filter(is_superuser=False)
        
        # Search by user name or email
        search = request.query_params.get('search')
        if search:
            users = users.filter(
                Q(first_name__icontains=search) | 
                Q(last_name__icontains=search) | 
                Q(email__icontains=search)
            )
        
        users = users.order_by('-date_joined')
        
        paginator = AdminParticipantPagination()
        paginated_users = paginator.paginate_queryset(users, request)
        
        serializer = AdminUserListSerializer(paginated_users, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        action = request.data.get('action', 'toggle_status')
        
        if action == 'toggle_status':
            user_id = request.data.get('user_id')
            if not user_id:
                return Response(
                    {"detail": "user_id is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                user = User.objects.get(id=user_id, is_superuser=False)
                user.is_active = not user.is_active
                user.save(update_fields=['is_active'])
                
                return Response({
                    "detail": f"User status toggled successfully to {'active' if user.is_active else 'inactive'}",
                    "user_id": user.id,
                    "is_active": user.is_active
                }, status=status.HTTP_200_OK)
                
            except User.DoesNotExist:
                return Response(
                    {"detail": "User not found or is a superuser"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        
        return Response(
            {"detail": f"Invalid action: {action}"}, 
            status=status.HTTP_400_BAD_REQUEST
        )


class AdminOverviewAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        # Your conversion rate: 1 coin = 1 SAR
        COIN_TO_SAR_RATE = 1.0  

        # 1. Entry fees revenue 
        entry_coins = AuctionParticipant.objects.aggregate(
            total=Sum('auction__entry_fee_coins')
        )['total'] or 0
        entry_revenue = entry_coins * COIN_TO_SAR_RATE

        # 2. Winner's bid coins revenue 
        winner_bid_coins = 0
        wins = AuctionWin.objects.select_related('auction', 'winner')

        for win in wins:
            winner_coins = Bid.objects.filter(
                auction=win.auction,
                user=win.winner
            ).aggregate(total=Sum('coins_deducted'))['total'] or 0
            winner_bid_coins += winner_coins

        winner_bid_revenue = winner_bid_coins * COIN_TO_SAR_RATE

        # 3. Claim coin fees (if any extra coins paid during claim — add later if needed)
        claim_revenue = 0.0

        # Total revenue from auctions
        revenue_from_auctions = entry_revenue + winner_bid_revenue + claim_revenue

        # Store revenue
        revenue_from_store = float(Order.objects.filter(
            payment_status='paid'
        ).aggregate(
            total=Sum('total_amount')
        )['total'] or 0.0)

        # Total revenue
        total_revenue = revenue_from_auctions + revenue_from_store

        # Total users
        total_users = User.objects.count()

        data = {
            "total_revenue": round(total_revenue, 2),
            "revenue_from_auctions": round(revenue_from_auctions, 2),
            "revenue_from_store": round(revenue_from_store, 2),
            "total_users": total_users
        }

        return Response(data, status=200)
    

class RevenueAuctionsYearlyChartView(generics.GenericAPIView):
    """
    GET /api/admin/chart/revenue-auctions-yearly/
    
    Returns full current year data for Revenue & Auctions chart:
    - revenue: SAR from entry fees + winners' bid coins (losers refunded)
    - auctions: number of ended auctions per month
    All 12 months shown, 0 if no data.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        current_year = timezone.now().year
        COIN_TO_SAR = 1.0  # 1 coin = 1 SAR (as confirmed)

        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]

        data = []

        for month_num in range(1, 13):
            month_start = timezone.datetime(current_year, month_num, 1)
            if month_num == 12:
                month_end = timezone.datetime(current_year + 1, 1, 1) - timezone.timedelta(seconds=1)
            else:
                month_end = timezone.datetime(current_year, month_num + 1, 1) - timezone.timedelta(seconds=1)

            # Ended auctions in this month
            ended_auctions = Auction.objects.filter(
                status=AuctionStatus.ENDED,
                end_time__range=(month_start, month_end)
            )

            auction_count = ended_auctions.count()

            # 1. Entry fees revenue (all participants)
            entry_coins = AuctionParticipant.objects.filter(
                auction__in=ended_auctions
            ).aggregate(total=Sum('auction__entry_fee_coins'))['total'] or 0

            # 2. Winners' bid coins revenue (only winners' coins kept)
            winner_bid_coins = 0
            wins = AuctionWin.objects.filter(
                auction__in=ended_auctions
            ).select_related('auction', 'winner')

            for win in wins:
                winner_coins = Bid.objects.filter(
                    auction=win.auction,
                    user=win.winner
                ).aggregate(total=Sum('coins_deducted'))['total'] or 0
                winner_bid_coins += winner_coins

            month_revenue = (entry_coins + winner_bid_coins) * COIN_TO_SAR

            data.append({
                "month": month_names[month_num - 1],
                "revenue": round(month_revenue, 2),
                "auctions": auction_count
            })

        return Response({
            "year": current_year,
            "data": data
        })


class UserParticipationYearlyChartView(generics.GenericAPIView):
    """
    GET /api/admin/chart/user-participation-yearly/
    
    Returns full current year user participation per month
    (unique users who joined or bid in ended auctions of that month)
    All 12 months shown, 0 if no data.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        current_year = timezone.now().year

        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]

        data = []

        for month_num in range(1, 13):
            month_start = timezone.datetime(current_year, month_num, 1)
            if month_num == 12:
                month_end = timezone.datetime(current_year + 1, 1, 1) - timezone.timedelta(seconds=1)
            else:
                month_end = timezone.datetime(current_year, month_num + 1, 1) - timezone.timedelta(seconds=1)

            # Unique users who joined OR bid in ended auctions this month
            active_users_count = User.objects.filter(
                Q(joined_auctions__auction__end_time__range=(month_start, month_end)) |
                Q(bids__auction__end_time__range=(month_start, month_end))
            ).distinct().count()

            data.append({
                "month": month_names[month_num - 1],
                "participation": active_users_count
            })

        return Response({
            "year": current_year,
            "data": data
        })
    

class TopPerformanceAuctionsView(generics.GenericAPIView):
    """
    GET /api/admin/top-auctions/
    
    Returns top 5 performing ended auctions:
    - Sorted by participant count descending
    - Only ended auctions with winner
    - Uses auction_price (set by admin at creation) as final_price_sar
    """
    permission_classes = [IsAdminUser]
    top_n = 5  # top 5 auctions

    def get(self, request):
        top_auctions = Auction.objects.filter(
            status=AuctionStatus.ENDED,
            wins__isnull=False  # has winner
        ).annotate(
            participant_count=Count('participants')
        ).order_by('-participant_count')[:self.top_n]

        data = []
        for auction in top_auctions:
            data.append({
                "product_name": auction.product_name,
                "final_price_sar": float(auction.auction_price),
                "participant_count": auction.participant_count
            })

        return Response({
            "top_auctions": data
        })


class AdminUserAuctionHistoryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {"detail": "user_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id, is_superuser=False)
            history = AuctionParticipant.objects.filter(user=user).select_related('auction').order_by('-joined_at')
            
            paginator = AdminParticipantPagination()
            paginated_history = paginator.paginate_queryset(history, request)
            
            serializer = AdminUserAuctionHistorySerializer(paginated_history, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found or is a superuser"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class AdminUserTransactionHistoryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {"detail": "user_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(id=user_id, is_superuser=False)
            transactions = CoinTransaction.objects.filter(user=user).order_by('-created_at')
            
            paginator = AdminParticipantPagination()
            paginated_transactions = paginator.paginate_queryset(transactions, request)
            
            serializer = AdminUserTransactionHistorySerializer(paginated_transactions, many=True)
            return paginator.get_paginated_response(serializer.data)
            
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found or is a superuser"}, 
                status=status.HTTP_404_NOT_FOUND
            )
class AdminUserDetailsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response(
                {"detail": "user_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from apps.users.models import User
            user = User.objects.get(id=user_id, is_superuser=False)
            serializer = AdminUserDetailsSerializer(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found or is a superuser"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class AdminProfileUpdateView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request):
        serializer = AdminProfileUpdateSerializer(
            request.user, 
            data=request.data, 
            partial=True, 
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AdminMyselfView(APIView):
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        serializer = AdminProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = AdminProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdminChangePasswordView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = AdminChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not user.check_password(serializer.validated_data['old_password']):
                return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
            
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            return Response({"detail": "Password updated successfully"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CoinStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.packages.models import UserWallet, CoinTransaction
        from apps.auction.models import Bid
        from .models import AuctionStatus
        from django.db.models import Sum

        # 1. Total Sold (Total In via Purchases)
        sold_stats = CoinTransaction.objects.filter(
            transaction_type='purchase'
        ).aggregate(
            total_coins=Sum('amount'),
            total_sar=Sum('price_sar')
        )
        solds_coins = sold_stats['total_coins'] or 0
        saudi_rial_sold_coins = sold_stats['total_sar'] or 0

        # 2. Unused Coins (Purchased but not spent - currently in wallets)
        unused_coins = UserWallet.objects.aggregate(
            total=Sum('coins')
        )['total'] or 0

        # 3. Refundable Coins (Coins tied up in active bids)
        refundable_coins = Bid.objects.filter(
            auction__status=AuctionStatus.PUBLISH
        ).aggregate(total=Sum('coins_deducted'))['total'] or 0

        # 4. Non-Refundable Coins (Spent on Entry Fees and Winning Bids)
        # Global Balance Identity: Sold = Unused + Refundable + NonRefundable
        # This residual captures all spent coins including:
        # - Entry Fees (explicitly requested)
        # - Winning Bids (which are not refunded)
        non_refundable_coins = max(0, solds_coins - unused_coins - refundable_coins)

        # 5. FIFO Batch Valuation
        # Assume OLDEST coins are spent first (FIFO). 
        # Coins currently "held" (Unused + Refundable) belong to the MOST RECENT batches.
        total_held = unused_coins + refundable_coins
        held_sar = 0.0
        
        if total_held > 0:
            remaining_to_calculate = total_held
            # Walk back through purchase batches (latest first)
            purchases = CoinTransaction.objects.filter(
                transaction_type='purchase'
            ).order_by('-created_at')
            
            for p in purchases:
                if remaining_to_calculate <= 0:
                    break
                
                batch_amount = p.amount
                batch_price = float(p.price_sar)
                
                if remaining_to_calculate >= batch_amount:
                    held_sar += batch_price
                    remaining_to_calculate -= batch_amount
                else:
                    # Partial batch mapping
                    held_sar += (remaining_to_calculate / batch_amount) * batch_price
                    remaining_to_calculate = 0
            
            # Fallback for "overflow" coins (e.g. bonuses)
            if remaining_to_calculate > 0:
                held_sar += float(remaining_to_calculate) * 1.0

        # Allocate held_sar proportionally between Unused and Refundable
        saudi_rial_unused_coins = 0.0
        saudi_rial_refundable_coins = 0.0
        
        if total_held > 0:
            saudi_rial_unused_coins = (unused_coins / total_held) * held_sar
            saudi_rial_refundable_coins = (refundable_coins / total_held) * held_sar

        # Non-Refundable SAR is total revenue collected from coins that are NO LONGER held
        saudi_rial_non_refundable_coins = max(0, float(saudi_rial_sold_coins) - held_sar)

        data = {
            "solds_coins": solds_coins,
            "unused_coins": unused_coins,
            "refundable_coins": refundable_coins,
            "non_refundable_coins": non_refundable_coins,
            "saudi_rial_sold_coins": saudi_rial_sold_coins,
            "saudi_rial_unused_coins": round(saudi_rial_unused_coins, 2),
            "saudi_rial_refundable_coins": round(saudi_rial_refundable_coins, 2),
            "saudi_rial_non_refundable_coins": round(saudi_rial_non_refundable_coins, 2),
        }

        serializer = CoinStatsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)



# ─────────────────────────────────────────
# ADMIN ORDER MANAGEMENT
# ─────────────────────────────────────────
class AdminOrderListView(generics.ListAPIView):
    """
    GET /api/admin/orders/
    GET /api/admin/orders/?search=9563
    GET /api/admin/orders/?status=processing
    """
    permission_classes = [IsAdminUser]
    pagination_class = AdminParticipantPagination

    def get_queryset(self):
        from apps.products.models import OrderItem
        queryset = OrderItem.objects.filter(
            order__payment_status='paid'
        ).select_related(
            'order', 'order__user', 'order__address',
            'product', 'color', 'size'
        ).prefetch_related(
            'product__images'
        ).order_by('-order__created_at')

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(order__status=status_filter)

        # Search by tracking_id or order_id
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(order__tracking_id__icontains=search) |
                Q(order__id__icontains=search)
            )

        return queryset

    def list(self, request, *args, **kwargs):
        from cloudinary.utils import cloudinary_url
        from decimal import Decimal

        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)

        data = []
        for item in page:
            # Thumbnail
            thumbnail = None
            first_image = item.product.images.first() if item.product else None
            if first_image:
                thumbnail, _ = cloudinary_url(
                    first_image.image.public_id, secure=True
                )

            # Discounted price
            discount = Decimal(item.discount_percentage) / Decimal(100)
            discounted_price = float(item.price * (1 - discount))

            data.append({
                'order_item_id': item.id,
                'order_id': item.order.id,
                'tracking_id': item.order.tracking_id,
                'status': item.order.status,
                'payment_method': item.order.payment_method,
                'created_at': item.order.created_at,
                'user': {
                    'user_id': item.order.user.id,
                    'name': item.order.user.get_full_name() or item.order.user.email.split('@')[0],
                    'email': item.order.user.email,
                },
                'product': {
                    'product_id': item.product.id if item.product else None,
                    'product_name': item.product.name if item.product else None,
                    'thumbnail': thumbnail,
                    'color': item.color.name if item.color else None,
                    'size': item.size.name if item.size else None,
                },
                'quantity': item.quantity,
                'original_price': float(item.price),
                'discount_percentage': item.discount_percentage,
                'discounted_price': discounted_price,
                'item_total': float(item.price * (1 - discount) * item.quantity),
            })

        return paginator.get_paginated_response(data)

class AdminOrderDetailView(generics.RetrieveAPIView):
    """
    GET /api/admin/orders/<order_id>/
    Returns full order detail with user info and address
    """
    permission_classes = [IsAdminUser]

    def get(self, request, order_id):
        from apps.products.models import Order
        from cloudinary.utils import cloudinary_url

        order = get_object_or_404(Order, id=order_id, payment_status='paid')

        # Items
        items = []
        for item in order.items.select_related('product', 'color', 'size'):
            thumbnail = None
            first_image = item.product.images.first() if item.product else None
            if first_image:
                thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)

            from decimal import Decimal
            discount = Decimal(item.discount_percentage) / Decimal(100)
            discounted_price = float(item.price * (1 - discount))

            items.append({
                'order_item_id': item.id,
                'product_id': item.product.id if item.product else None,
                'product_name': item.product.name if item.product else None,
                'thumbnail': thumbnail,
                'color': item.color.name if item.color else None,
                'size': item.size.name if item.size else None,
                'quantity': item.quantity,
                'original_price': float(item.price),
                'discount_percentage': item.discount_percentage,
                'discounted_price': discounted_price,
                'item_total': float(item.price * (1 - discount) * item.quantity),
            })

        return Response({
            'order_id': order.id,
            'tracking_id': order.tracking_id,
            'status': order.status,
            'payment_status': order.payment_status,
            'payment_method': order.payment_method,
            'total_amount': float(order.total_amount),
            'created_at': order.created_at,
            'updated_at': order.updated_at,
            'user_information': {
                'user_id': order.user.id,
                'name': order.user.get_full_name() or order.user.email.split('@')[0],
                'email': order.user.email,
                'phone_number': order.user.phone_number,
                'street_address': order.address.street_address if order.address else None,
                'apartment': order.address.apartment if order.address else None,
                'city': order.address.city if order.address else None,
                'zip_code': order.address.zip_code if order.address else None,
            },
            'items': items,
        })


class AdminMarkDeliveredView(generics.UpdateAPIView):
    """
    PATCH /api/admin/orders/<order_id>/mark-delivered/
    Admin marks order as delivered
    """
    permission_classes = [IsAdminUser]

    def patch(self, request, order_id):
        from apps.products.models import Order, OrderStatus

        order = get_object_or_404(Order, id=order_id, payment_status='paid')

        if order.status != OrderStatus.PROCESSING:
            return Response(
                {'error': 'Order must be processing to mark as delivered'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = OrderStatus.DELIVERED
        order.save(update_fields=['status'])

        return Response({
            'message': f'Order {order.tracking_id} marked as delivered successfully',
            'order_id': order.id,
            'tracking_id': order.tracking_id,
            'status': order.status,
        })
    



class AdminReviewListView(generics.ListAPIView):
    """
    GET /api/admin/reviews/
    GET /api/admin/reviews/?search=john
    GET /api/admin/reviews/?product_id=43
    GET /api/admin/reviews/?rating=5
    """
    permission_classes = [IsAdminUser]
    pagination_class = AdminParticipantPagination

    def get_queryset(self):
        from apps.products.models import ProductReview
        queryset = ProductReview.objects.select_related(
            'user', 'product'
        ).order_by('-created_at')

        # Search by user name or email
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        # Filter by product
        product_id = self.request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        # Filter by rating
        rating = self.request.query_params.get('rating')
        if rating:
            queryset = queryset.filter(rating=rating)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)

        data = []
        for review in page:
            user_name = review.user.get_full_name().strip()
            if not user_name:
                user_name = review.user.email.split('@')[0]

            data.append({
                'review_id': review.id,
                'user_name': user_name,
                'user_email': review.user.email,
                'product_id': review.product.id if review.product else None,
                'product_name': review.product.name if review.product else None,
                'rating': review.rating,
                'comment_preview': review.comment[:50] + '...' if len(review.comment) > 50 else review.comment,
                'created_at': review.created_at,
            })

        return paginator.get_paginated_response(data)


class AdminReviewDetailView(generics.RetrieveAPIView):
    """
    GET /api/admin/reviews/<review_id>/
    """
    permission_classes = [IsAdminUser]

    def get(self, request, review_id):
        from apps.products.models import ProductReview
        review = get_object_or_404(
            ProductReview.objects.select_related('user', 'product'),
            id=review_id
        )

        user_name = review.user.get_full_name().strip()
        if not user_name:
            user_name = review.user.email.split('@')[0]

        return Response({
            'review_id': review.id,
            'user': {
                'user_id': review.user.id,
                'user_name': user_name,
                'user_email': review.user.email,
            },
            'product': {
                'product_id': review.product.id if review.product else None,
                'product_name': review.product.name if review.product else None,
            },
            'rating': review.rating,
            'comment': review.comment,
            'created_at': review.created_at,
        })


class AdminReviewDeleteView(generics.DestroyAPIView):
    """
    DELETE /api/admin/reviews/<review_id>/delete/
    """
    permission_classes = [IsAdminUser]

    def delete(self, request, review_id):
        from apps.products.models import ProductReview
        review = get_object_or_404(ProductReview, id=review_id)
        review.delete()
        return Response(
            {'message': 'Review deleted successfully'},
            status=status.HTTP_200_OK
        )


# ─────────────────────────────────────────
# Add these imports at the top of the file
# ─────────────────────────────────────────

def send_fcm_notification(user_ids, title, body, image_url=None, data=None):
    from fcm_django.models import FCMDevice
    from firebase_admin.messaging import Message, Notification

    devices = FCMDevice.objects.filter(user_id__in=user_ids, active=True)
    if not devices.exists():
        return

    message_data = data or {}
    for device in devices:
        try:
            device.send_message(
                Message(
                    notification=Notification(
                        title=title,
                        body=body,
                        image=image_url,
                    ),
                    data={k: str(v) for k, v in message_data.items()},
                )
            )
        except Exception as e:
            print(f"FCM error for user {device.user_id}: {e}")


class AdminUserSearchView(APIView):
    """
    GET /api/admin/users/search/?q=john
    Search users by name or email for announcement targeting
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        query = request.query_params.get('q', '')
        if not query or len(query) < 2:
            return Response(
                {'error': 'Search query must be at least 2 characters'},
                status=status.HTTP_400_BAD_REQUEST
            )

        users = User.objects.filter(
            is_superuser=False,
            is_active=True
        ).filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )[:10]

        data = [{
            'user_id': u.id,
            'name': u.get_full_name() or u.email.split('@')[0],
            'email': u.email,
        } for u in users]

        return Response({'results': data})


class AdminSendAnnouncementView(generics.CreateAPIView):
    """
    POST /api/admin/announcements/
    form-data: title, description, send_to, user_emails (comma separated), image (optional)
    """
    permission_classes = [IsAdminUser]

    def create(self, request, *args, **kwargs):
        title = request.data.get('title')
        description = request.data.get('description')
        send_to = request.data.get('send_to', 'all')
        image = request.FILES.get('image')
        user_emails_raw = request.data.get('user_emails', '')

        if not title or not description:
            return Response(
                {'error': 'title and description are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if send_to not in ['all', 'specific']:
            return Response(
                {'error': 'send_to must be all or specific'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Create Announcement ──
        announcement = Announcement.objects.create(
            title=title,
            description=description,
            send_to=send_to,
            image=image,
            created_by=request.user
        )

        # ── Determine Recipients ──
        if send_to == 'all':
            recipients = User.objects.filter(
                is_superuser=False,
                is_active=True
            )
        else:
            if not user_emails_raw:
                announcement.delete()
                return Response(
                    {'error': 'user_emails is required for specific send'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user_emails = [
                email.strip()
                for email in user_emails_raw.split(',')
                if email.strip()
            ]
            recipients = User.objects.filter(
                email__in=user_emails,
                is_superuser=False,
                is_active=True
            )

            found_emails = set(recipients.values_list('email', flat=True))
            not_found = [e for e in user_emails if e not in found_emails]
            if not_found:
                announcement.delete()
                return Response(
                    {'error': f'Users not found: {", ".join(not_found)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            announcement.recipients.set(recipients)

        # ── Get image URL for FCM ──
        image_url = None
        if announcement.image:
            image_url, _ = cloudinary_url(
                announcement.image.public_id, secure=True
            )

        # ── Create UserNotification for each recipient ──
        notifications = [
            UserNotification(
                user=user,
                notification_type='announcement',
                title=title,
                body=description,
                image=announcement.image,
                announcement=announcement,
            )
            for user in recipients
        ]
        UserNotification.objects.bulk_create(notifications)

        # ── Send FCM Push ──
        recipient_ids = list(recipients.values_list('id', flat=True))
        send_fcm_notification(
            user_ids=recipient_ids,
            title=title,
            body=description,
            image_url=image_url,
            data={
                'type': 'announcement',
                'announcement_id': str(announcement.id),
            }
        )

        return Response({
            'message': f'Announcement sent to {len(recipient_ids)} users',
            'announcement_id': announcement.id,
            'title': announcement.title,
            'recipients_count': len(recipient_ids),
            'send_to': ', '.join([
                u.get_full_name() or u.email.split('@')[0]
                for u in recipients
            ]) if send_to == 'specific' else 'All Users',
        }, status=status.HTTP_201_CREATED)
    
class AdminAnnouncementListView(generics.ListAPIView):
    """
    GET /api/admin/announcements/list/
    """
    permission_classes = [IsAdminUser]
    serializer_class = AnnouncementSerializer
    pagination_class = AdminParticipantPagination

    def get_queryset(self):
        return Announcement.objects.all().order_by('-created_at')


class AdminAnnouncementDeleteView(APIView):
    """
    DELETE /api/admin/announcements/<announcement_id>/delete/
    """
    permission_classes = [IsAdminUser]

    def delete(self, request, announcement_id):
        announcement = get_object_or_404(Announcement, id=announcement_id)
        announcement.delete()
        return Response(
            {'message': 'Announcement deleted successfully'},
            status=status.HTTP_200_OK
        )
    

class AdminProductNamesListView(APIView):
    """
    GET /api/admin/products/names/
    Returns all product names and IDs for review filter dropdown
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.products.models import Product
        products = Product.objects.values('id', 'name').order_by('name')
        return Response({'results': list(products)})    