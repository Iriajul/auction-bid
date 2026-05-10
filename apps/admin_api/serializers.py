from rest_framework import serializers
from django.utils import timezone
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from apps.auction.models import AuctionParticipant
from apps.users.models import User
from apps.packages.models import CoinTransaction
from .models import Category, Auction, AuctionStatus, CoinPackage, AuctionImage, Announcement
from django.utils import timezone
from cloudinary.utils import cloudinary_url 


class AdminLoginSerializer(TokenObtainPairSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        email = attrs.get('email').lower().strip()
        password = attrs.get('password')

        if email and password:
            user = authenticate(
                request=self.context.get('request'),
                username=email,  # since USERNAME_FIELD = 'email'
                password=password
            )

            if not user:
                raise serializers.ValidationError(
                    {"detail": "Invalid email or password."},
                    code='authorization'
                )

            if not user.is_staff:
                raise serializers.ValidationError(
                    {"detail": "This account does not have admin access."},
                    code='permission_denied'
                )

            if not user.is_active:
                raise serializers.ValidationError(
                    {"detail": "Account is inactive."},
                    code='inactive'
                )

        else:
            raise serializers.ValidationError(
                {"detail": "Both email and password are required."},
                code='required'
            )

        # Generate tokens
        refresh = self.get_token(user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': user.id,
                'email': user.email,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }


class CategorySerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = Category
        fields = [
            'category_id',
            'name',
            'category_for',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'category_id',
            'is_active',        # 🔒 admin cannot set this
            'created_at',
            'updated_at'
        ]

    def create(self, validated_data):
        # Force category to be active on creation
        validated_data['is_active'] = True
        return super().create(validated_data)

class CategoryEditSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(required=True)
    name = serializers.CharField(max_length=100, required=False)
    category_for = serializers.ChoiceField(
        choices=[
            ('physical', 'Physical'),
            ('digital', 'Digital'),
            ('auction', 'Auction'),
        ],
        required=False
    )
    is_active = serializers.BooleanField(required=False)

class CategoryDeleteSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(required=True)


class AuctionCreateSerializer(serializers.ModelSerializer):
    product_images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False
    )
    product_image_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Auction
        fields = [
            'id', 'product_name', 'category', 'product_images', 'product_image_url',
            'description', 'market_price', 'auction_price', 'entry_fee_coins',
            'auction_duration', 'winning_claim_window',
            'status', 'scheduled_time'
        ]
        read_only_fields = ['id', 'created_by', 'product_image_url']

    def create(self, validated_data):
        images = validated_data.pop('product_images', [])
        validated_data['created_by'] = self.context['request'].user
        auction = Auction.objects.create(**validated_data)

        for img in images:
            AuctionImage.objects.create(auction=auction, image=img)

        return auction

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        # Auction duration
        if instance.auction_duration:
            total_seconds = int(instance.auction_duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            ret['auction_duration'] = {
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds
            }
        # Winning claim window
        if instance.winning_claim_window:
            total_seconds = int(instance.winning_claim_window.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            ret['winning_claim_window'] = {
                "hours": hours,
                "minutes": minutes,
                "seconds": seconds
            }
        # Rename id to auction_id
        ordered = {'auction_id': ret.pop('id')}
        ordered.update(ret)
        return ordered

    def validate(self, data):
        request = self.context.get('request')
        is_partial = request and request.method == 'PATCH'
        status_val = data.get('status')
        scheduled_time = data.get('scheduled_time')

        if not is_partial:
            if status_val == AuctionStatus.SCHEDULE:
                if not scheduled_time:
                    raise serializers.ValidationError({"scheduled_time": "This field is required when status is 'schedule'."})
                if scheduled_time <= timezone.now():
                    raise serializers.ValidationError({"scheduled_time": "Scheduled time must be in the future."})
            return data

        # PATCH update
        if status_val is not None:
            if status_val == AuctionStatus.SCHEDULE:
                if scheduled_time is None:
                    raise serializers.ValidationError({"scheduled_time": "scheduled_time is required when status is 'schedule'."})
                if scheduled_time <= timezone.now():
                    raise serializers.ValidationError({"scheduled_time": "Scheduled time must be in the future."})
            else:
                data['scheduled_time'] = None

        return data

    def get_product_image_url(self, obj):
    # obj.product_image is a RelatedManager for AuctionImage
        return [
            cloudinary_url(img.image.public_id, secure=True)[0] 
            for img in obj.product_image.all()
        ]

class AuctionListSerializer(serializers.ModelSerializer):
    auction_id = serializers.IntegerField(source='id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    product_image_url = serializers.SerializerMethodField(read_only=True)
    participant_count = serializers.SerializerMethodField(read_only=True)
    remaining_time = serializers.SerializerMethodField()
    auction_duration = serializers.SerializerMethodField()  
    scheduled_time = serializers.DateTimeField(
        read_only=True,
        format='%Y-%m-%dT%H:%M:%S%z'
    )

    class Meta:
        model = Auction
        fields = [
            'auction_id', 'product_name', 'category_name', 'product_image_url',
            'auction_price', 'market_price', 'status', 'created_at',
            'auction_duration', 'entry_fee_coins',
            'participant_count', 'scheduled_time', 'remaining_time'
        ]

    def get_auction_duration(self, obj):
        if not obj.auction_duration:
            return None

        total_seconds = int(obj.auction_duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds
        }

    def get_product_image_url(self, obj):
    # obj.product_image is a RelatedManager for AuctionImage
        return [
            cloudinary_url(img.image.public_id, secure=True)[0] 
            for img in obj.product_image.all()
        ]
    
    def get_remaining_time(self, obj):
        now = timezone.now()

        if obj.status == AuctionStatus.PUBLISH:
            end_time = obj.end_time or (obj.created_at + obj.auction_duration)
            remaining = end_time - now
        elif obj.status == AuctionStatus.SCHEDULE and obj.scheduled_time:
            remaining = obj.scheduled_time - now
        else:
            return "Ended"

        total_seconds = int(remaining.total_seconds())
        if total_seconds <= 0:
            return "Ended"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return f"{hours}h {minutes}m {seconds}s"
    
    # NEW: Get participant count (only for live/ended auctions)
    def get_participant_count(self, obj):
        if obj.status in [AuctionStatus.PUBLISH, AuctionStatus.ENDED]:
            return AuctionParticipant.objects.filter(auction=obj).count()
        return 0  # For upcoming/schedule/invalid
    
class CoinPackageSerializer(serializers.ModelSerializer):
    package_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = CoinPackage
        fields = ['package_id', 'coins', 'price_sar', 'is_active']
        read_only_fields = ['package_id']

class CoinPackageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinPackage
        fields = ['coins', 'price_sar',]

    def to_representation(self, instance):
        # After creation, return full data using CoinPackageSerializer
        return CoinPackageSerializer(instance).data


class CoinPackageEditSerializer(serializers.ModelSerializer):
    package_id = serializers.IntegerField(required=True, write_only=True)

    class Meta:
        model = CoinPackage
        fields = ['package_id', 'coins', 'price_sar']


class AuctionParticipantDetailSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_name = serializers.CharField()
    user_email = serializers.EmailField()
    avatar_url = serializers.CharField(allow_null=True)
    status = serializers.CharField()               # "Winner", "N/A"
    coin_balance = serializers.IntegerField()
    refundable_coin = serializers.IntegerField()
    bids_count = serializers.IntegerField()
    total_coins_spent = serializers.IntegerField()


class AuctionDetailAdminSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField()
    product_name = serializers.CharField()
    category_name = serializers.CharField()
    product_image_url = serializers.CharField()
    auction_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    market_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    auction_duration = serializers.CharField()
    participant_count = serializers.IntegerField()
    remaining_time = serializers.CharField(allow_null=True)
    participants = AuctionParticipantDetailSerializer(many=True)


class AdminUserListSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    status = serializers.BooleanField(source='is_active')

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone_number', 'status', 'is_verified', 'date_joined']

    def get_username(self, obj):
        return obj.get_full_name() or obj.first_name or obj.email.split('@')[0]


class AdminUserAuctionHistorySerializer(serializers.ModelSerializer):
    auction_title = serializers.CharField(source='auction.product_name', read_only=True)
    days_ago = serializers.SerializerMethodField()
    total_bids = serializers.SerializerMethodField()

    class Meta:
        model = AuctionParticipant
        fields = ['auction_title', 'joined_at', 'days_ago', 'total_bids']

    def get_days_ago(self, obj):
        now = timezone.now()
        delta = now - obj.joined_at
        return delta.days

    def get_total_bids(self, obj):
        from apps.auction.models import Bid
        return Bid.objects.filter(auction=obj.auction, user=obj.user).count()


class AdminUserTransactionHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinTransaction
        fields = ['id', 'transaction_type', 'amount', 'description', 'created_at']


class AdminUserDetailsSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    status = serializers.BooleanField(source='is_active')
    wallet_coins = serializers.SerializerMethodField()
    refundable_coins = serializers.SerializerMethodField()
    total_spent_coins = serializers.SerializerMethodField()
    total_wins = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone_number', 'status', 
            'is_verified', 'date_joined', 'wallet_coins', 
            'refundable_coins', 'total_spent_coins', 'total_wins'
        ]

    def get_username(self, obj):
        return obj.get_full_name() or obj.first_name or obj.email.split('@')[0]

    def get_wallet_coins(self, obj):
        from apps.packages.models import UserWallet
        wallet = UserWallet.objects.filter(user=obj).first()
        return wallet.coins if wallet else 0

    def get_refundable_coins(self, obj):
        from apps.auction.models import Bid
        from .models import AuctionStatus
        return Bid.objects.filter(
            user=obj, 
            auction__status=AuctionStatus.PUBLISH
        ).count()

    def get_total_spent_coins(self, obj):
        from django.db.models import Sum
        return obj.coin_transactions.filter(
            transaction_type__in=['bid', 'entry_fee']
        ).aggregate(total=Sum('amount'))['total'] or 0

    def get_total_wins(self, obj):
        from apps.auction.models import AuctionWin
        return AuctionWin.objects.filter(winner=obj).count()


class AdminProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number']

    def validate_email(self, value):
        user = self.context['request'].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

class AdminProfileSerializer(serializers.ModelSerializer):
    status = serializers.BooleanField(source='is_active', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'phone_number', 
            'first_name', 'last_name',
            'status', 'is_verified', 'date_joined'
        ]
        read_only_fields = ['id', 'status', 'is_verified', 'date_joined']

    def validate_username(self, value):
        user = self.instance
        if User.objects.exclude(pk=user.pk).filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        user = self.instance
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate_phone_number(self, value):
        user = self.instance
        if value and User.objects.exclude(pk=user.pk).filter(phone_number=value).exists():
            raise serializers.ValidationError("This phone number is already in use.")
        return value


class AdminChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, data):
        if data['new_password'] != data['new_password_confirm']:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        return data


class CoinStatsSerializer(serializers.Serializer):
    solds_coins = serializers.IntegerField()
    unused_coins = serializers.IntegerField()
    refundable_coins = serializers.IntegerField()
    non_refundable_coins = serializers.IntegerField()
    # Saudi Rial Conversions
    saudi_rial_sold_coins = serializers.DecimalField(max_digits=15, decimal_places=2)
    saudi_rial_unused_coins = serializers.DecimalField(max_digits=15, decimal_places=2)
    saudi_rial_refundable_coins = serializers.DecimalField(max_digits=15, decimal_places=2)
    saudi_rial_non_refundable_coins = serializers.DecimalField(max_digits=15, decimal_places=2)



class AnnouncementSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    recipients_count = serializers.SerializerMethodField()
    send_to = serializers.SerializerMethodField()  
    class Meta:
        model = Announcement
        fields = [
            'id', 'title', 'description', 'image_url',
            'send_to', 'recipients_count', 'created_at'
        ]

    def get_image_url(self, obj):
        if obj.image:
            from cloudinary.utils import cloudinary_url
            url, _ = cloudinary_url(obj.image.public_id, secure=True)
            return url
        return None

    def get_send_to(self, obj):
        if obj.send_to == 'all':
            return 'All Users'

        return ', '.join([
            u.get_full_name() or u.email.split('@')[0]
            for u in obj.recipients.all()
        ])

    def get_recipients_count(self, obj):
        if obj.send_to == 'all':
            from apps.users.models import User
            return User.objects.filter(
                is_superuser=False, is_active=True
            ).count()
        return obj.recipients.count()