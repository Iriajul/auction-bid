from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from cloudinary.models import CloudinaryField


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    category_for = models.CharField(
        max_length=20,
        choices=[
            ('physical', 'Physical'),
            ('digital', 'Digital'),
            ('auction', 'Auction'),
        ],
        default='physical'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Uncheck to hide this category from users (won't appear in dropdowns or lists)"
    )

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_category_for_display()})"

    def get_category_for_display(self):
        return dict(self._meta.get_field('category_for').choices).get(self.category_for, self.category_for)

class AuctionStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    SCHEDULE = 'schedule', 'Schedule'
    PUBLISH = 'publish', 'Publish'
    ENDED    = "ended",  "Ended"


class Auction(models.Model):
    product_name = models.CharField(max_length=255, verbose_name="Product Name")
    
    category = models.ForeignKey(
        Category, 
        on_delete=models.PROTECT,
        related_name='auctions',
        verbose_name="Category"
    )

    description = models.TextField(blank=True, verbose_name="Description")
    
    market_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Market Price (SAR)"
    )
    
    auction_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Auction Starting Price (SAR)"
    )
    
    entry_fee_coins = models.PositiveIntegerField(
        default=0,
        verbose_name="Entry Fee (coins - non-refundable)"
    )
    
    auction_duration = models.DurationField(
        verbose_name="Auction Duration (e.g. 5 minutes)"
    )
    
    winning_claim_window = models.DurationField(
        verbose_name="Winning Prize Claim Window (time to claim after end)"
    )
    
    status = models.CharField(
        max_length=20,
        choices=AuctionStatus.choices,
        default=AuctionStatus.DRAFT,
        verbose_name="Status"
    )
    
    scheduled_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Scheduled Start Time (required only for Schedule)"
    )
    
    current_bid = models.PositiveIntegerField(
        default=0,
        verbose_name="Current Highest Bid"
    )
    
    last_bid_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Last Bid Time"
    )

    end_time = models.DateTimeField(
    null=True,
    blank=True,
    verbose_name="Auction End Time (updated on bids)"
    )

    created_by = models.ForeignKey(
        (settings.AUTH_USER_MODEL),
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_auctions',
        verbose_name="Created by Admin"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Auction"
        verbose_name_plural = "Auctions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='auction_status_idx'),
            models.Index(fields=['end_time'], name='auction_end_time_idx'),
            models.Index(fields=['scheduled_time'], name='auction_scheduled_idx'),
            models.Index(fields=['status', 'end_time'], name='auction_status_end_idx'),
            models.Index(fields=['-created_at'], name='auction_created_idx'),
    ]
    def __str__(self):
        return f"{self.product_name} ({self.status})"

    def clean(self):
        if self.status == AuctionStatus.SCHEDULE:
            if not self.scheduled_time:
                raise ValidationError("Scheduled time is required when status is 'Schedule'.")
            if self.scheduled_time <= timezone.now():
                raise ValidationError("Scheduled time must be in the future.")
        else:
            self.scheduled_time = None

    def get_user_spent_info(self, user):
        from django.apps import apps
        from django.db.models import Sum

        AuctionParticipant = apps.get_model('auction', 'AuctionParticipant')
        Bid = apps.get_model('auction', 'Bid')

        participant = AuctionParticipant.objects.filter(
            auction=self,
            user=user,
            entry_fee_paid=True
        ).first()

        entry_fee = self.entry_fee_coins if participant else 0

        bid_coins = Bid.objects.filter(
            auction=self,
            user=user
        ).aggregate(total=Sum('coins_deducted'))['total'] or 0

        return {
            "entry_fee": entry_fee,
            "bid_coins": bid_coins,
            "total_spent": entry_fee + bid_coins
        }

class AuctionImage(models.Model):
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name='product_image',  # same name for serializer compatibility
        verbose_name="Auction"
    )
    image = CloudinaryField(resource_type='image', verbose_name="Auction Image")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Auction Image"
        verbose_name_plural = "Auction Images"

    def __str__(self):
        return f"{self.auction.product_name} - Image {self.id}"       


class CoinPackage(models.Model):
    coins = models.PositiveIntegerField(verbose_name="Number of Coins")
    price_sar = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Price (SAR)")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Coin Package"
        verbose_name_plural = "Coin Packages"
        ordering = ['price_sar']

    def __str__(self):
        return f"{self.coins} Coins - SAR {self.price_sar}"
    


class Announcement(models.Model):
    SEND_TO_CHOICES = [
        ('all', 'All Users'),
        ('specific', 'Specific Users'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    image = CloudinaryField(
        'announcement_image',
        resource_type='image',
        blank=True,
        null=True
    )
    send_to = models.CharField(
        max_length=10,
        choices=SEND_TO_CHOICES,
        default='all'
    )
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='received_announcements'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_announcements'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


    