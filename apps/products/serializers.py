from decimal import Decimal
from rest_framework import serializers
from .models import Product, ProductColor, ProductImage, ProductSize, ProductType
from apps.admin_api.models import Category
from cloudinary.utils import cloudinary_url


class ProductImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ['id', 'image_url']

    def get_image_url(self, obj):
        if obj.image:
            url, _ = cloudinary_url(obj.image.public_id, secure=True)
            return url
        return None


class ProductSizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSize
        fields = ['id', 'name']


class ProductColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductColor
        fields = ['id', 'name']


class ProductSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    code_file_url = serializers.SerializerMethodField()
    sizes = ProductSizeSerializer(many=True, read_only=True)
    colors = ProductColorSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'product_id', 'name', 'product_type', 'category', 'category_name',
            'description', 'price', 'discount_percentage',
            'sizes', 'colors', 'region', 'brand',
            'code_file', 'code_file_url', 'card_expiry_date',
            'images', 'created_at', 'updated_at'
        ]
        read_only_fields = ['product_id', 'created_at', 'updated_at', 'category_name']

    def get_code_file_url(self, obj):
        if obj.code_file:
            url, _ = cloudinary_url(obj.code_file.public_id, resource_type='raw', secure=True)
            return url
        return None

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        if instance.product_type == ProductType.PHYSICAL:
            ret.pop('region', None)
            ret.pop('brand', None)
            ret.pop('code_file', None)
            ret.pop('code_file_url', None)
            ret.pop('card_expiry_date', None)
        else:
            ret.pop('code_file', None)
            ret.pop('sizes', None)
            ret.pop('colors', None)

        return ret


class ProductCreateSerializer(serializers.ModelSerializer):
    images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False
    )
    remove_image_ids = serializers.ListField(
    child=serializers.IntegerField(), write_only=True, required=False
    )
    code_file = serializers.FileField(required=False, allow_null=True)
    sizes = serializers.CharField(required=False, default='', write_only=True)
    colors = serializers.CharField(required=False, default='', write_only=True)

    class Meta:
        model = Product
        fields = [
            'name', 'product_type', 'category', 'description', 'price',
            'discount_percentage', 'sizes', 'colors', 'region', 'brand',
            'code_file', 'card_expiry_date', 'images','remove_image_ids' 
        ]

    def validate(self, data):
        product_type = data.get('product_type')
        category = data.get('category')

        if category and product_type:
            if product_type == ProductType.PHYSICAL and category.category_for != 'physical':
                raise serializers.ValidationError({
                    "category": "Physical products can only use Physical categories"
                })
            if product_type == ProductType.DIGITAL and category.category_for != 'digital':
                raise serializers.ValidationError({
                    "category": "Digital products can only use Digital categories"
                })

        return data

    def create(self, validated_data):
        images_data = validated_data.pop('images', [])
        sizes_data = validated_data.pop('sizes', '')
        colors_data = validated_data.pop('colors', '')

        product = Product.objects.create(**validated_data)

        if sizes_data:
            for size_name in sizes_data.split(','):
                size_obj, _ = ProductSize.objects.get_or_create(name=size_name.strip())
                product.sizes.add(size_obj)

        if colors_data:
            for color_name in colors_data.split(','):
                color_obj, _ = ProductColor.objects.get_or_create(name=color_name.strip())
                product.colors.add(color_obj)

        for image_file in images_data:
            img = ProductImage.objects.create(image=image_file)
            product.images.add(img)

        return product

    def update(self, instance, validated_data):
        images_data = validated_data.pop('images', [])
        remove_image_ids = validated_data.pop('remove_image_ids', [])
        sizes_data = validated_data.pop('sizes', None)
        colors_data = validated_data.pop('colors', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if sizes_data is not None:
            instance.sizes.clear()
            for size_name in sizes_data.split(','):
                size_obj, _ = ProductSize.objects.get_or_create(name=size_name.strip())
                instance.sizes.add(size_obj)

        if colors_data is not None:
            instance.colors.clear()
            for color_name in colors_data.split(','):
                color_obj, _ = ProductColor.objects.get_or_create(name=color_name.strip())
                instance.colors.add(color_obj)

        if remove_image_ids:
            for image_id in remove_image_ids:
                try:
                    image = ProductImage.objects.get(id=image_id)
                    instance.images.remove(image)
                    image.delete()
                except ProductImage.DoesNotExist:
                    pass

        if images_data:
            for image_file in images_data:
                img = ProductImage.objects.create(image=image_file)
                instance.images.add(img)

        return instance
    def to_representation(self, instance):
        return ProductSerializer(instance, context=self.context).to_representation(instance)
    


class UserProductListSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    thumbnail = serializers.SerializerMethodField()
    discounted_price = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()    
    average_rating = serializers.SerializerMethodField() 

    class Meta:
        model = Product
        fields = [
            'product_id', 'name', 'product_type', 'category_name',
            'price', 'discount_percentage', 'discounted_price', 
            'thumbnail', 'review_count', 'average_rating',  
        ]

    def get_thumbnail(self, obj):
        first_image = obj.images.first()
        if first_image:
            url, _ = cloudinary_url(first_image.image.public_id, secure=True)
            return url
        return None
    
    def get_discounted_price(self, obj): 
        discount = Decimal(obj.discount_percentage) / Decimal(100)
        return float(obj.price * (1 - discount))
    
    def get_review_count(self, obj):                        
        return obj.reviews.count()

    def get_average_rating(self, obj):                     
        from django.db.models import Avg
        avg = obj.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0.0


class UserProductDetailSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source='id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    sizes = ProductSizeSerializer(many=True, read_only=True)       
    colors = ProductColorSerializer(many=True, read_only=True)   
    discounted_price = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()      
    average_rating = serializers.SerializerMethodField() 

    class Meta:
        model = Product
        fields = [
            'product_id', 'name', 'product_type', 'category', 'category_name',
            'description', 'price', 'discount_percentage', 'discounted_price',
            'sizes', 'colors', 'images', 'review_count', 'average_rating',
        ]


    def get_discounted_price(self, obj):
        from decimal import Decimal
        discount = Decimal(obj.discount_percentage) / Decimal(100)
        return float(obj.price * (1 - discount))

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.product_type == ProductType.DIGITAL:
            ret.pop('size', None)
            ret.pop('colors', None)
        return ret
    
    def get_review_count(self, obj):                       
        return obj.reviews.count()

    def get_average_rating(self, obj):                     
        from django.db.models import Avg
        avg = obj.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0.0


class UserCategorySerializer(serializers.ModelSerializer):
    category_id = serializers.IntegerField(source='id', read_only=True)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['category_id', 'name', 'product_count']

    def get_product_count(self, obj):
        return obj.products.count()
    
    