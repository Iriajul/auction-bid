from django.db import models
from apps.users.models import User


class UserWallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    coins = models.PositiveIntegerField(default=0, verbose_name="Coin Balance")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.coins} coins"


class CoinTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('purchase', 'Purchase'),
        ('bid', 'Bid Expense'),
        ('entry_fee', 'Entry Fee Expense'),
        ('refund', 'Refund'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='coin_transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.PositiveIntegerField()
    price_sar = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Price (SAR)")
    description = models.CharField(max_length=255, blank=True)
    
    # History Chain Fields
    reference_id = models.CharField(max_length=255, null=True, blank=True)
    reference_type = models.CharField(max_length=50, null=True, blank=True) # e.g., 'bid', 'participant', 'purchase'
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Coin Transaction"
        verbose_name_plural = "Coin Transactions"

    def __str__(self):
        return f"{self.user.email} - {self.transaction_type} - {self.amount} coins"