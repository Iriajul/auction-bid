from rest_framework import serializers
from django.db import models
from .models import AuctionParticipant
from apps.admin_api.models import Auction, AuctionStatus, Category
from apps.users.models import UserAddress
from .models import Bid
from django.utils import timezone
from cloudinary.utils import cloudinary_url


class JoinAuctionSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField(required=True)

class AuctionCardSerializer(serializers.ModelSerializer):
    auction_id = serializers.IntegerField(source='id', read_only=True)
    product_image_url = serializers.SerializerMethodField()
    remaining_time = serializers.SerializerMethodField()
    entry_fee_coins = serializers.IntegerField()
    auction_price = serializers.DecimalField(max_digits=12, decimal_places=2)  
    market_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    current_bid = serializers.DecimalField(max_digits=12, decimal_places=2) 
    amount_saving = serializers.SerializerMethodField()
    has_participated = serializers.SerializerMethodField()
    can_bid = serializers.SerializerMethodField()
    current_bid_coin_count = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            'auction_id',
            'product_name',
            'product_image_url',
            'auction_price',     # fixed by admin
            'market_price',
            'current_bid',       # live, increases with bids
            'amount_saving',     # market_price - current_bid
            'entry_fee_coins',
            'remaining_time',
            'status',
            'has_participated',  # true if auth user joined this auction
            'can_bid',
            'current_bid_coin_count',
        ]

    def get_amount_saving(self, obj):
        # Dynamic: market_price - current_bid (updates with every bid)
        saving = obj.market_price - obj.current_bid
        return max(float(saving), 0)  # no negative saving

    def get_remaining_time(self, obj):
        # Your existing logic (unchanged)
        if obj.status == 'publish':
            start_time = obj.created_at
            end_time = start_time + obj.auction_duration
            time_left = end_time - timezone.now()
            if time_left.total_seconds() <= 0:
                return "Ended"
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes = remainder // 60
            if days > 0:
                return f"Remaining: {days} Days"
            return f"Remaining: {hours}h {minutes}m"
        elif obj.status == 'schedule':
            time_to_start = obj.scheduled_time - timezone.now()
            if time_to_start.total_seconds() <= 0:
                return "Starting soon"
            days = time_to_start.days
            hours, remainder = divmod(time_to_start.seconds, 3600)
            minutes = remainder // 60
            if days > 0:
                return f"Remaining: {days} Days"
            return f"{hours}h {minutes}m"
        return "N/A"

    def get_product_image_url(self, obj):
    # obj.product_image is a RelatedManager for AuctionImage
        return [
            cloudinary_url(img.image.public_id, secure=True)[0] 
            for img in obj.product_image.all()
        ]

    def get_has_participated(self, obj):
        """
        Returns True if the authenticated user has joined this auction
        (i.e. paid entry fee and is an AuctionParticipant).
        Returns False for unauthenticated users.
        """
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return AuctionParticipant.objects.filter(auction=obj, user=request.user).exists()
        return False
    
    def get_can_bid(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        if obj.status != AuctionStatus.PUBLISH:
            return False
        last_bid = Bid.objects.filter(auction=obj).order_by('-bid_number').first()
        if last_bid and last_bid.user == request.user:
            return False
        return True
    
    def get_current_bid_coin_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return 0
        from django.db.models import Sum
        coins_spent = obj.bids.filter(user=request.user).aggregate(
            total=Sum('coins_deducted')
        )['total'] or 0
        return coins_spent
    

class BidHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()       # username before @
    user_initials = serializers.SerializerMethodField()   # first letter(s) of username
    is_leader = serializers.SerializerMethodField()

    class Meta:
        model = Bid
        fields = ['bid_number', 'user_name', 'user_initials', 'bid_at', 'is_leader']

    def get_user_name(self, obj):
        """
        Return username before @, or full name if available.
        Fallback to email if nothing else works.
        """
        full_name = obj.user.get_full_name().strip()
        email = obj.user.email

        # Prefer full name if it exists and is not empty
        if full_name:
            return full_name

        # Otherwise extract username from email (before @)
        if '@' in email:
            username = email.split('@')[0].strip()
            return username if username else email

        return email  # fallback

    def get_user_initials(self, obj):
        """
        First 1-2 uppercase letters of the processed user_name.
        """
        name = self.get_user_name(obj)

        # Split into words and take first letter of each
        initials = ''.join(word[0].upper() for word in name.split() if word)[:2]

        # Fallback if no initials (very rare)
        return initials if initials else "U"

    def get_is_leader(self, obj):
        return obj.bid_number == obj.auction.current_bid

class AuctionDetailSerializer(serializers.ModelSerializer):
    auction_id = serializers.IntegerField(source='id', read_only=True)
    product_image_url = serializers.SerializerMethodField()
    remaining_time = serializers.SerializerMethodField()
    entry_fee_coins = serializers.IntegerField()
    auction_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    market_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    current_bid = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_saving = serializers.SerializerMethodField()
    bid_history = serializers.SerializerMethodField()
    bid_leader = serializers.SerializerMethodField()
    user_in_bid = serializers.SerializerMethodField()
    can_bid = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            'auction_id', 'product_name', 'product_image_url',
            'auction_price', 'market_price', 'current_bid', 'amount_saving',
            'entry_fee_coins', 'remaining_time', 'status',
            'bid_history', 'bid_leader', 'user_in_bid', 'can_bid'
        ]
    
    def get_product_image_url(self, obj):
        return [
            cloudinary_url(img.image.public_id, secure=True)[0]
            for img in obj.product_image.all()
        ]
    

    def get_remaining_time(self, obj):
        if obj.status == AuctionStatus.PUBLISH:
            start_time = obj.created_at
            end_time = obj.end_time or (start_time + obj.auction_duration)
            time_left = end_time - timezone.now()
            if time_left.total_seconds() <= 0:
                return "Ended"
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes = remainder // 60
            if days > 0:
                return f"Remaining: {days} Days"
            return f"Remaining: {hours}h {minutes}m"
        elif obj.status == AuctionStatus.SCHEDULE:
            time_to_start = obj.scheduled_time - timezone.now()
            if time_to_start.total_seconds() <= 0:
                return "Starting soon"
            days = time_to_start.days
            hours, remainder = divmod(time_to_start.seconds, 3600)
            minutes = remainder // 60
            if days > 0:
                return f"Remaining: {days} Days"
            return f"{hours}h {minutes}m"
        return "N/A"

    def get_amount_saving(self, obj):
        saving = obj.market_price - obj.current_bid
        return float(max(saving, 0))  # no negative saving

    def get_bid_history(self, obj):
        bids = Bid.objects.filter(auction=obj).order_by('-bid_at')[:10]
        return BidHistorySerializer(bids, many=True).data

    def get_bid_leader(self, obj):
        if obj.current_bid == 0:
            return None
        leader_bid = Bid.objects.filter(auction=obj, bid_number=obj.current_bid).first()
        if not leader_bid:
            return None
        name = leader_bid.user.get_full_name() or leader_bid.user.email
        return {
            'name': name,
            'initials': ''.join(w[0].upper() for w in name.split() if w)[:2]
        }

    def get_user_in_bid(self, obj):
        """
        Returns True if the authenticated user has placed at least one bid
        in this auction. Returns False otherwise.
        """
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return Bid.objects.filter(auction=obj, user=request.user).exists()
        return False

    def get_can_bid(self, obj):
        """
        Returns True if the authenticated user is allowed to bid right now.
        Returns False if they were the last person to bid (cannot bid twice in a row)
        or if the auction is not currently active.
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False

        if obj.status != AuctionStatus.PUBLISH:
            return False

        last_bid = Bid.objects.filter(auction=obj).order_by('-bid_number').first()
        if last_bid and last_bid.user == request.user:
            return False

        return True


class UserAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAddress
        fields = [
            'id',
            'full_name',
            'phone_or_email',
            'street_address',
            'apartment',
            'city',
            'zip_code',
            'is_default',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'user']


class WinnerCheckRequestSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField(required=True)


class WinnerCheckResponseSerializer(serializers.Serializer):
    is_winner = serializers.BooleanField()
    auction_id = serializers.IntegerField()
    product_name = serializers.CharField()
    final_bid = serializers.DecimalField(max_digits=12, decimal_places=2)
    bid_coins_used = serializers.IntegerField()  
    has_address = serializers.BooleanField()
    claim_window_end = serializers.DateTimeField()
    claim_window_remaining = serializers.CharField()  # human readable string


class SaveAddressRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAddress
        fields = [
            'full_name',
            'phone_or_email',
            'street_address',
            'apartment',
            'city',
            'zip_code'
        ]


class CheckoutSummaryRequestSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField(required=True)


class CheckoutSummaryResponseSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField()
    product_name = serializers.CharField()
    auction_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    final_bid = serializers.DecimalField(max_digits=12, decimal_places=2)
    bid_coins_used = serializers.IntegerField()          # example: coins spent in bids
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    selected_address = UserAddressSerializer(allow_null=True)
    all_addresses = UserAddressSerializer(many=True)  # ← NEW


class BiddingHistoryItemSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_image_url = serializers.CharField()
    auction_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    market_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    save_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()  # "won", "lost"
    user_bids_count = serializers.IntegerField()
    user_coins_spent = serializers.IntegerField()
    is_winner = serializers.BooleanField()
    claim_window_remaining = serializers.CharField(allow_null=True)
    claim_window_end = serializers.DateTimeField(allow_null=True)
    must_claim_by = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)



class UserCategorySerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(source='id')
    auction_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            'category_id',
            'name',
            'auction_count'
        ]


class UserBidHistoryFormatSerializer(serializers.ModelSerializer):
    """
    Serializer to match the specific JSON format requested by user:
    {
        id: '1',
        title: 'Armchair furniture',
        image: '1.png',
        price: 55.00,
        originalPrice: 75.00,
        currency: 'SAR',
        bids: 5,
        saves: 2500,
        time: 300,
        description: '...',
        status: 'won' | 'lost' | 'active',
        deadline: '59:00'
    }
    """
    id = serializers.CharField()
    title = serializers.CharField(source='product_name')
    image = serializers.SerializerMethodField()
    price = serializers.DecimalField(source='auction_price', max_digits=12, decimal_places=2)
    originalPrice = serializers.DecimalField(source='market_price', max_digits=12, decimal_places=2)
    currency = serializers.SerializerMethodField()
    bids = serializers.SerializerMethodField()
    saves = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
    description = serializers.CharField()
    status = serializers.SerializerMethodField()
    deadline = serializers.SerializerMethodField()
    claim_window_end = serializers.SerializerMethodField()  # ISO string, only set when status='claim_window'
    current_bid_coin_count = serializers.SerializerMethodField()
    joining_bid = serializers.IntegerField(source='entry_fee_coins')
    entry_coin = serializers.IntegerField(source='entry_fee_coins')
    coins_per_bid = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    can_bid = serializers.SerializerMethodField()
    has_participated = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            'id', 'title', 'image', 'price', 'originalPrice', 'currency',
            'bids', 'saves', 'time', 'description', 'status', 'deadline',
            'claim_window_end',
            'current_bid_coin_count', 'joining_bid', 'entry_coin', 'coins_per_bid', 'total_spent', 'can_bid',
            'has_participated'
        ]

    def get_image(self, obj):
        # Return first image URL or placeholder
        if obj.product_image.exists():
            img = obj.product_image.first()
            return cloudinary_url(img.image.public_id, secure=True)[0]
        return ""

    def get_currency(self, obj):
        return "SAR"

    def get_bids(self, obj):
        # Count bids for this auction (total)
        return obj.bids.count()

    def get_saves(self, obj):
        # Mocking saves as notification subscriptions for now, or just 0
        return obj.notification_subscriptions.count()

    def get_time(self, obj):
        # Remaining seconds
        if obj.status == AuctionStatus.PUBLISH:
            end_time = obj.end_time or (obj.created_at + obj.auction_duration)
            remaining = end_time - timezone.now()
            return max(int(remaining.total_seconds()), 0)
        return 0

    def get_status(self, obj):
        """
        Status values returned to frontend:

          'active'        — Auction is still RUNNING (end_time in future)
          'claim_window'  — Auction ENDED, user WON, claim window is OPEN (must pay now)
          'won'           — Auction ended, user paid & claimed successfully
          'lost'          — Auction ended, user was NOT the highest bidder
                            OR user was the winner but claim window EXPIRED without payment
        """
        user = self.context['request'].user
        now = timezone.now()

        # ---------- Auction still running ----------
        if obj.status == AuctionStatus.PUBLISH:
            end_time = obj.end_time or (obj.created_at + obj.auction_duration)
            if now < end_time:
                return 'active'

        # ---------- Auction has ended ----------
        win = obj.wins.filter(winner=user).first()
        if win:
            if win.claimed:
                return 'won'                   # fully paid & claimed
            if now <= win.claim_window_end:
                return 'claim_window'           # winner, claim window is OPEN – must act!
            return 'lost'                      # claim window expired without payment

        # No AuctionWin record — user was NOT the highest bidder
        return 'lost'

    def get_deadline(self, obj):
        """Auction end_time countdown (only relevant while status='active'/running).
        Returns ISO string while the auction is still running, else None.
        """
        user = self.context['request'].user
        now = timezone.now()

        if obj.status == AuctionStatus.PUBLISH:
            end_time = obj.end_time or (obj.created_at + obj.auction_duration)
            if now < end_time:
                return end_time.isoformat()

        return None

    def get_claim_window_end(self, obj):
        """Claim window deadline (only relevant when status='claim_window').
        Returns ISO string if the user is the winner and claim window is still open.
        Frontend should show a countdown + 'Claim Now' CTA when this is not None.
        """
        user = self.context['request'].user
        now = timezone.now()

        win = obj.wins.filter(winner=user).first()
        if win and not win.claimed and now <= win.claim_window_end:
            return win.claim_window_end.isoformat()

        return None

    def get_current_bid_coin_count(self, obj):
        user = self.context['request'].user
        coins_spent = obj.bids.filter(user=user).aggregate(
            total=models.Sum('coins_deducted')
        )['total'] or 0
        return coins_spent

    def get_coins_per_bid(self, obj):
        # Currently hardcoded to 1 in socket logic
        return 1

    def get_total_spent(self, obj):
        user = self.context['request'].user
        bid_coins = self.get_current_bid_coin_count(obj)
        joining_fee = obj.entry_fee_coins or 0
        return bid_coins + joining_fee

    def get_can_bid(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        if obj.status != AuctionStatus.PUBLISH:
            return False
        last_bid = Bid.objects.filter(auction=obj).order_by('-bid_number').first()
        if last_bid and last_bid.user == request.user:
            return False
        return True
    def get_has_participated(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return AuctionParticipant.objects.filter(auction=obj, user=request.user).exists()
        return False

