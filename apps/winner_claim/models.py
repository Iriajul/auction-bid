# apps/winner_claim/models.py
from django.db import models
from django.utils import timezone
from apps.auction.models import AuctionWin


class ClaimAttempt(models.Model):
    DELIVERY_STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('delivered', 'Delivered'),
    ]

    win_record = models.OneToOneField(
        AuctionWin,
        on_delete=models.CASCADE,
        related_name='claim_attempt'
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    payment_initiated = models.BooleanField(default=False)
    payment_session_id = models.CharField(max_length=255, blank=True, null=True)
    payment_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(         # ✅ new
        max_length=20,
        choices=DELIVERY_STATUS_CHOICES,
        default='processing'
    )
    delivery_updated_at = models.DateTimeField(null=True, blank=True)  # ✅ new

    def __str__(self):
        return f"Claim attempt for {self.win_record.auction} by {self.win_record.winner}"


class PaymentLog(models.Model):
    claim_attempt = models.ForeignKey(
        ClaimAttempt,
        on_delete=models.CASCADE,
        related_name='payment_logs'
    )
    stripe_event_type = models.CharField(max_length=100, blank=True)
    stripe_session_id = models.CharField(max_length=255, blank=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    currency = models.CharField(max_length=3, default='SAR')
    status = models.CharField(max_length=50, default='pending')
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment log for claim {self.claim_attempt.id} - {self.status}"