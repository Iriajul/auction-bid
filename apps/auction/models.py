from django.db import models
from django.utils import timezone
from django.conf import settings


class AuctionParticipant(models.Model):
    auction = models.ForeignKey(
        'admin_api.Auction',
        on_delete=models.CASCADE,
        related_name='participants'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joined_auctions'
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    entry_fee_paid = models.BooleanField(default=True)

    class Meta:
        unique_together = ('auction', 'user')
        verbose_name = "Auction Participant"
        verbose_name_plural = "Auction Participants"

    def __str__(self):
        return f"{self.user.email} joined {self.auction.product_name}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new and self.entry_fee_paid:
            from apps.packages.models import CoinTransaction

            CoinTransaction.objects.get_or_create(
                user=self.user,
                transaction_type='entry_fee',
                reference_id=self.id,
                reference_type='participant',
                defaults={
                    'amount': self.auction.entry_fee_coins,
                    'description': f"Entry fee for Auction #{self.auction.id} ({self.auction.product_name})"
                }
            )


class Bid(models.Model):
    auction = models.ForeignKey(
        'admin_api.Auction',
        on_delete=models.CASCADE,
        related_name='bids'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    bid_number = models.PositiveIntegerField()
    bid_at = models.DateTimeField(auto_now_add=True)
    coins_deducted = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-bid_at']
        unique_together = ('auction', 'bid_number')
        indexes = [
            models.Index(fields=['auction', 'user'], name='bid_auction_user_idx'),
            models.Index(fields=['auction', '-bid_number'], name='bid_auction_number_idx'),
            models.Index(fields=['auction', '-bid_at'], name='bid_auction_time_idx'),
            models.Index(fields=['user'], name='bid_user_idx'),
        ]

    def __str__(self):
        return f"Bid {self.bid_number} by {self.user.email}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            from apps.packages.models import CoinTransaction

            CoinTransaction.objects.get_or_create(
                user=self.user,
                transaction_type='bid',
                reference_id=self.id,
                reference_type='bid',
                defaults={
                    'amount': self.coins_deducted,
                    'description': f"Bid #{self.bid_number} on Auction #{self.auction.id}"
                }
            )


class AuctionWin(models.Model):
    auction = models.ForeignKey(
        'admin_api.Auction',
        on_delete=models.CASCADE,
        related_name='wins'
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='auction_wins'
    )
    won_at = models.DateTimeField(auto_now_add=True)
    final_bid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )
    claim_window_end = models.DateTimeField()
    claimed = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(null=True, blank=True)

    shipping_address = models.ForeignKey(
        'users.UserAddress',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='auction_claims'
    )

    class Meta:
        unique_together = ('auction', 'winner')
        ordering = ['-won_at']

    def __str__(self):
        return f"Win: {self.winner.email} - Auction {self.auction.id}"

    def is_claim_window_open(self):
        return timezone.now() <= self.claim_window_end and not self.claimed


class AuctionNotificationSubscription(models.Model):
    auction = models.ForeignKey(
        'admin_api.Auction',
        on_delete=models.CASCADE,
        related_name='notification_subscriptions'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='auction_notifications'
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)
    notified = models.BooleanField(default=False)

    class Meta:
        unique_together = ('auction', 'user')