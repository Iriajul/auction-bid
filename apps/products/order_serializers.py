from rest_framework import serializers
from .models import Order, OrderItem, ProductReview, Product, ProductColor, ProductSize
from apps.users.models import UserAddress
from cloudinary.utils import cloudinary_url


class OrderAddressSerializer(serializers.ModelSerializer):
    address_id = serializers.IntegerField(source='id', read_only=True) 

    class Meta:
        model = UserAddress
        fields = [
            'address_id', 'full_name', 'phone_or_email',
            'street_address', 'apartment',
            'city', 'zip_code'
        ]


class OrderItemProductSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True)  
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['product_id', 'name', 'thumbnail']

    def get_thumbnail(self, obj):
        first_image = obj.images.first()
        if first_image:
            url, _ = cloudinary_url(first_image.image.public_id, secure=True)
            return url
        return None


class OrderItemSerializer(serializers.ModelSerializer):
    order_item_id = serializers.IntegerField(source='id', read_only=True)
    product = OrderItemProductSerializer(read_only=True)
    color_name = serializers.CharField(source='color.name', read_only=True)
    size_name = serializers.CharField(source='size.name', read_only=True)
    item_total = serializers.ReadOnlyField()
    discounted_price = serializers.SerializerMethodField()  

    class Meta:
        model = OrderItem
        fields = [
            'order_item_id', 'product', 'color_name', 'size_name',
            'quantity', 'price', 'discount_percentage',
            'discounted_price', 'item_total'  
        ]

    def get_discounted_price(self, obj):
        from decimal import Decimal
        discount = Decimal(obj.discount_percentage) / Decimal(100)
        return float(obj.price * (1 - discount))



class OrderSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='id', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    address = OrderAddressSerializer(read_only=True)
    can_cancel = serializers.SerializerMethodField()
    can_review = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'order_id', 'tracking_id', 'status', 'payment_status',
            'payment_method', 'total_amount', 'address',
            'items', 'can_cancel', 'can_review',
            'created_at', 'updated_at'
        ]

    def get_can_cancel(self, obj):
        return obj.status == 'pending'

    def get_can_review(self, obj):
        return obj.status == 'delivered'


# ── Checkout Preview ──
class CheckoutItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    color_id = serializers.IntegerField(required=False, allow_null=True)
    size_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(default=1, min_value=1)


class CheckoutPreviewSerializer(serializers.Serializer):
    """For Buy Now - single product checkout preview"""
    product_id = serializers.IntegerField()
    color_id = serializers.IntegerField(required=False, allow_null=True)
    size_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(default=1, min_value=1)
    address_id = serializers.IntegerField()

    def validate(self, data):
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError({'product_id': 'Product not found'})

        color_id = data.get('color_id')
        size_id = data.get('size_id')

        if color_id and not product.colors.filter(id=color_id).exists():
            raise serializers.ValidationError({
                'color_id': 'Color does not belong to this product'
            })

        if size_id and not product.sizes.filter(id=size_id).exists():
            raise serializers.ValidationError({
                'size_id': 'Size does not belong to this product'
            })

        return data


class CartCheckoutSerializer(serializers.Serializer):
    """For Cart checkout - uses selected cart items"""
    address_id = serializers.IntegerField()


# ── Place Order ──
class PlaceOrderSerializer(serializers.Serializer):
    address_id = serializers.IntegerField()
    # For Buy Now
    product_id = serializers.IntegerField(required=False)
    color_id = serializers.IntegerField(required=False, allow_null=True)
    size_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(required=False, default=1)
    is_buy_now = serializers.BooleanField(default=False)


# ── Review ──
class WriteReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductReview
        fields = ['rating', 'comment']

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value


class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()  

    class Meta:
        model = ProductReview
        fields = ['id', 'user_name', 'rating', 'comment', 'created_at']

    def get_user_name(self, obj):
        full_name = obj.user.get_full_name()
        if full_name and full_name.strip():
            return full_name
        return obj.user.email.split('@')[0]