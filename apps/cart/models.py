from django.db import models
from apps.users.models import User
from apps.products.models import Product, ProductColor, ProductSize


class Cart(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='cart'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart"
        verbose_name_plural = "Carts"

    def __str__(self):
        return f"Cart of {self.user.email}"

    @property
    def total_items(self):
        return self.items.count()

    @property
    def selected_total(self):
        from decimal import Decimal
        total = Decimal('0')
        for item in self.items.filter(is_selected=True): 
            discount = Decimal(item.product.discount_percentage) / Decimal(100)
            discounted_price = item.product.price * (1 - discount)
            total += discounted_price * item.quantity
        return float(total)


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cart_items'
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
    quantity = models.PositiveIntegerField(default=1)
    is_selected = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        # Same product with same color and size = one item
        unique_together = ['cart', 'product', 'color', 'size']

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"

    @property
    def item_total(self):
        from decimal import Decimal
        discount = Decimal(self.product.discount_percentage) / Decimal(100)
        discounted_price = self.product.price * (1 - discount)
        return float(discounted_price * self.quantity) 