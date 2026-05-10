from rest_framework import serializers
from .models import Cart, CartItem
from apps.products.models import Product, ProductColor, ProductSize
from cloudinary.utils import cloudinary_url


class CartItemProductSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True) 
    thumbnail = serializers.SerializerMethodField()
    discounted_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['product_id', 'name', 'price', 'discount_percentage', 'thumbnail', 'discounted_price']

    def get_thumbnail(self, obj):
        first_image = obj.images.first()
        if first_image:
            url, _ = cloudinary_url(first_image.image.public_id, secure=True)
            return url
        return None
    
    def get_discounted_price(self, obj):  
        from decimal import Decimal
        discount = Decimal(obj.discount_percentage) / Decimal(100)
        return float(obj.price * (1 - discount))


class CartItemSerializer(serializers.ModelSerializer):
    cart_item_id = serializers.IntegerField(source='id', read_only=True)
    product = CartItemProductSerializer(read_only=True)
    color_name = serializers.CharField(source='color.name', read_only=True)
    size_name = serializers.CharField(source='size.name', read_only=True)
    item_total = serializers.ReadOnlyField()

    class Meta:
        model = CartItem
        fields = [
            'cart_item_id', 'product', 'color', 'color_name',
            'size', 'size_name', 'quantity',
            'is_selected', 'item_total'
        ]


class CartSerializer(serializers.ModelSerializer):
    cart_id = serializers.IntegerField(source='id', read_only=True)
    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.ReadOnlyField()
    selected_total = serializers.ReadOnlyField()
    selected_count = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            'cart_id', 'items', 'total_items',
            'selected_count', 'selected_total'
        ]

    def get_selected_count(self, obj):
        return obj.items.filter(is_selected=True).count()


class AddToCartSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    color_id = serializers.IntegerField(required=False, allow_null=True)
    size_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(default=1, min_value=1)

    def validate(self, data):
        product_id = data.get('product_id')
        color_id = data.get('color_id')
        size_id = data.get('size_id')

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise serializers.ValidationError({'product_id': 'Product not found'})
        if color_id:
            if not product.colors.filter(id=color_id).exists():
                raise serializers.ValidationError({
                    'color_id': f'Color with id {color_id} does not belong to this product'
                })
        if size_id:
            if not product.sizes.filter(id=size_id).exists():
                raise serializers.ValidationError({
                    'size_id': f'Size with id {size_id} does not belong to this product'
                })

        return data

    def validate_product_id(self, value):
        if not Product.objects.filter(id=value).exists():
            raise serializers.ValidationError('Product not found')
        return value


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(required=False, min_value=1)
    is_selected = serializers.BooleanField(required=False)