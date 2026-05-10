from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from apps.admin_api.models import Category
from .models import Product, ProductImage
from rest_framework.filters import SearchFilter
from .serializers import ProductSerializer, ProductCreateSerializer, UserCategorySerializer, UserProductDetailSerializer, UserProductListSerializer
from apps.common.pagination import AdminParticipantPagination
from cloudinary.utils import cloudinary_url 



class ProductListCreateView(generics.ListCreateAPIView):
    """
    GET /api/products/        → List all products
    POST /api/products/       → Create new product
    
    Response on create includes "product_id"
    """
    queryset = Product.objects.all().order_by('-created_at')
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['product_type']
    pagination_class = AdminParticipantPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['name', 'brand', 'region', 'category__name'] 

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProductCreateSerializer
        return ProductSerializer

    def perform_create(self, serializer):
        # Set created_by here
        serializer.save(created_by=self.request.user)


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/products/<product_id>/   → Get single product
    PATCH  /api/products/<product_id>/   → Edit product
    DELETE /api/products/<product_id>/   → Delete product
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'id'           # internal lookup still uses id
    lookup_url_kwarg = 'product_id'  # URL uses product_id

    def get_serializer_class(self):
        if self.request.method in ['PATCH', 'PUT']:
            return ProductCreateSerializer
        return ProductSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        # Rename id to product_id in response
        data = serializer.data
        data['product_id'] = data.pop('id')
        return Response(data)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        product_name = instance.name
        self.perform_destroy(instance)
        return Response(
            {'message': f'Product "{product_name}" has been deleted successfully.'},
            status=status.HTTP_200_OK
        )
    


class UserProductListView(generics.ListAPIView):
    """
    GET /api/products/store/          → All products
    GET /api/products/store/?category=Phone    → Filter by category name
    GET /api/products/store/?search=iphone     → Search by name
    GET /api/products/store/?category=Phone&search=iphone → Both
    """
    serializer_class = UserProductListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['name']

    def get_queryset(self):
        queryset = Product.objects.all().order_by('-created_at')
        category = self.request.query_params.get('category')
        if category:
            if category.lower() == 'all':
                return queryset
            queryset = queryset.filter(category__name__iexact=category)
        return queryset


class UserProductDetailView(generics.RetrieveAPIView):
    """
    GET /api/products/store/<product_id>/  → Single product detail
    """
    queryset = Product.objects.all()
    serializer_class = UserProductDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'product_id'


class UserCategoryListView(generics.ListAPIView):
    """
    GET /api/products/categories/  → All active physical categories with product count
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserCategorySerializer

    def get_queryset(self):
        return Category.objects.filter(
            is_active=True,
            category_for__in=['physical', 'digital']  # only physical and digital categories for store
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })