from rest_framework import serializers
from .models import WishlistItem
from apps.products.models import Product, ProductColor, ProductSize
from cloudinary.utils import cloudinary_url


class AddToWishlistSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    color_id = serializers.IntegerField(required=False, allow_null=True)
    size_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        try:
            product = Product.objects.get(id=data['product_id'])
        except Product.DoesNotExist:
            raise serializers.ValidationError({'product_id': 'Product not found'})

        from apps.products.models import ProductType
        if product.product_type == ProductType.PHYSICAL:
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


class WishlistItemSerializer(serializers.ModelSerializer):
    wishlist_item_id = serializers.IntegerField(source='id', read_only=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    color_id = serializers.IntegerField(source='color.id', read_only=True)
    color_name = serializers.CharField(source='color.name', read_only=True)
    size_id = serializers.IntegerField(source='size.id', read_only=True)
    size_name = serializers.CharField(source='size.name', read_only=True)
    original_price = serializers.DecimalField(
        source='product.price',
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    discount_percentage = serializers.IntegerField(
        source='product.discount_percentage',
        read_only=True
    )
    discounted_price = serializers.SerializerMethodField()
    discount_label = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    is_in_wishlist = serializers.SerializerMethodField()

    class Meta:
        model = WishlistItem
        fields = [
            'wishlist_item_id', 'product_id', 'product_name',
            'color_id', 'color_name', 'size_id', 'size_name',
            'original_price', 'discount_percentage',
            'discounted_price', 'discount_label',
            'thumbnail', 'is_in_wishlist', 'created_at'
        ]

    def get_discounted_price(self, obj):
        from decimal import Decimal
        discount = Decimal(obj.product.discount_percentage) / Decimal(100)
        return float(obj.product.price * (1 - discount))

    def get_discount_label(self, obj):
        if obj.product.discount_percentage > 0:
            return f"upto {obj.product.discount_percentage}% off"
        return None

    def get_thumbnail(self, obj):
        first_image = obj.product.images.first()
        if first_image:
            url, _ = cloudinary_url(first_image.image.public_id, secure=True)
            return url
        return None

    def get_is_in_wishlist(self, obj):
        return True