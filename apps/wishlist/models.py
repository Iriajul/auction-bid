from django.db import models
from apps.users.models import User
from apps.products.models import Product, ProductColor, ProductSize


class WishlistItem(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='wishlist'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='wishlisted_by'
    )
    color = models.ForeignKey(
        ProductColor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Selected Color"
    )
    size = models.ForeignKey(
        ProductSize,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Selected Size"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Wishlist Item"
        verbose_name_plural = "Wishlist Items"
        # same product + color + size = one wishlist item per user
        unique_together = ['user', 'product', 'color', 'size']

    def __str__(self):
        return f"{self.user.email} - {self.product.name}"