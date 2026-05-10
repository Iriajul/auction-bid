from django.db import models
from apps.admin_api.models import Category
from cloudinary.models import CloudinaryField
import random
import string


class ProductType(models.TextChoices):
    PHYSICAL = 'physical', 'Physical'
    DIGITAL = 'digital', 'Digital'


class ProductSize(models.Model):
    name = models.CharField(max_length=100, verbose_name="Size")

    def __str__(self):
        return self.name


class ProductColor(models.Model):
    name = models.CharField(max_length=100, verbose_name="Color")

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255, verbose_name="Product Name")
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        verbose_name="Product Type"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name="Category"
    )
    description = models.TextField(blank=True, verbose_name="Description")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Product Price (SAR)")
    discount_percentage = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Discount (%)"
    )
    sizes = models.ManyToManyField(
        ProductSize,
        related_name='products',
        blank=True,
        verbose_name="Sizes"
    )
    colors = models.ManyToManyField(
        ProductColor,
        related_name='products',
        blank=True,
        verbose_name="Colors"
    )
    region = models.CharField(max_length=100, blank=True, verbose_name="Region")
    brand = models.CharField(max_length=100, blank=True, verbose_name="Brand")
    code_file = CloudinaryField(
        'product_codes',
        resource_type='raw',
        blank=True,
        null=True,
    )
    card_expiry_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Card Expiry Date"
    )
    images = models.ManyToManyField('ProductImage', related_name='products', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Created By"
    )

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product_type'], name='product_type_idx'),
            models.Index(fields=['category'], name='product_category_idx'),
            models.Index(fields=['-created_at'], name='product_created_idx'),
            models.Index(fields=['product_type', 'category'], name='product_type_category_idx'),
        ]

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    image = CloudinaryField('product_image', resource_type='image')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for product"


def generate_tracking_id():
    """Generate tracking ID like #4158RTASH"""
    numbers = ''.join(random.choices(string.digits, k=4))
    letters = ''.join(random.choices(string.ascii_uppercase, k=5))
    return f"#{numbers}{letters}"


class OrderStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    DELIVERED = 'delivered', 'Delivered'
    CANCELLED = 'cancelled', 'Cancelled'


class Order(models.Model):
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='orders'
    )
    tracking_id = models.CharField(
        max_length=20,
        unique=True,
        default=generate_tracking_id,
        verbose_name="Tracking ID"
    )
    address = models.ForeignKey(
        'users.UserAddress',
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Delivery Address"
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Total Amount (SAR)"
    )
    stripe_session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )
    payment_status = models.CharField(
        max_length=20,
        default='unpaid'
    )
    payment_method = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Payment Method (visa/applepay etc)"
    )
    is_buy_now = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'payment_status'], name='order_user_payment_idx'),
            models.Index(fields=['payment_status', 'status'], name='order_payment_status_idx'),
            models.Index(fields=['tracking_id'], name='order_tracking_idx'),
            models.Index(fields=['-created_at'], name='order_created_idx'),
            models.Index(fields=['stripe_session_id'], name='order_stripe_idx'),
        ]

    def __str__(self):
        return f"Order {self.tracking_id} by {self.user.email}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        related_name='order_items'
    )
    color = models.ForeignKey(
        ProductColor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    size = models.ForeignKey(
        ProductSize,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Price at time of order"
    )
    discount_percentage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        indexes = [
            models.Index(fields=['order'], name='orderitem_order_idx'),
            models.Index(fields=['product'], name='orderitem_product_idx'),
        ]

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"

    @property
    def item_total(self):
        from decimal import Decimal
        discount = Decimal(self.discount_percentage) / Decimal(100)
        return self.price * (1 - discount) * self.quantity


class ProductReview(models.Model):
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    rating = models.PositiveSmallIntegerField(
        verbose_name="Rating (1-5)"
    )
    comment = models.TextField(blank=True, verbose_name="Review Comment")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Review"
        verbose_name_plural = "Product Reviews"
        unique_together = ['user', 'product', 'order']
        indexes = [
            models.Index(fields=['product'], name='review_product_idx'),
            models.Index(fields=['product', 'rating'], name='review_product_rating_idx'),
            models.Index(fields=['-created_at'], name='review_created_idx'),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.product.name} - {self.rating}★"