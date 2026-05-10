from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import WishlistItem
from .serializers import AddToWishlistSerializer, WishlistItemSerializer
from apps.products.models import Product, ProductColor, ProductSize


class WishlistListView(generics.ListAPIView):
    """
    GET /api/wishlist/  → Get all wishlist items
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WishlistItemSerializer

    def get_queryset(self):
        return WishlistItem.objects.filter(
            user=self.request.user
        ).select_related(
            'product', 'color', 'size'
        ).prefetch_related(
            'product__images'
        ).order_by('-created_at')


class WishlistToggleView(generics.GenericAPIView):
    """
    POST /api/wishlist/toggle/
    - If item not in wishlist → add it
    - If item already in wishlist → remove it (toggle)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AddToWishlistSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product = Product.objects.get(id=data['product_id'])
        color = ProductColor.objects.filter(id=data.get('color_id')).first()
        size = ProductSize.objects.filter(id=data.get('size_id')).first()

        # Check if already in wishlist
        existing = WishlistItem.objects.filter(
            user=request.user,
            product=product,
            color=color,
            size=size
        ).first()

        if existing:
            # ✅ Already in wishlist → remove it (toggle off)
            existing.delete()
            return Response({
                'message': f'{product.name} removed from wishlist',
                'is_in_wishlist': False,
                'wishlist_count': WishlistItem.objects.filter(
                    user=request.user
                ).count()
            })
        else:
            # ✅ Not in wishlist → add it (toggle on)
            item = WishlistItem.objects.create(
                user=request.user,
                product=product,
                color=color,
                size=size
            )
            return Response({
                'message': f'{product.name} added to wishlist',
                'is_in_wishlist': True,
                'wishlist_item_id': item.id,
                'wishlist_count': WishlistItem.objects.filter(
                    user=request.user
                ).count()
            }, status=status.HTTP_201_CREATED)


class WishlistAddToCartView(generics.GenericAPIView):
    """
    POST /api/wishlist/<item_id>/add-to-cart/
    Adds wishlist item to cart with quantity 1
    No body needed
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, item_id):
        from apps.cart.models import Cart, CartItem

        wishlist_item = get_object_or_404(
            WishlistItem,
            id=item_id,
            user=request.user
        )

        cart, _ = Cart.objects.get_or_create(user=request.user)

        # ✅ Always add with quantity 1
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=wishlist_item.product,
            color=wishlist_item.color,
            size=wishlist_item.size,
            defaults={'quantity': 1}
        )

        if not created:
            cart_item.quantity += 1
            cart_item.save(update_fields=['quantity'])

        return Response({
            'message': f'{wishlist_item.product.name} added to cart',
            'cart_item_id': cart_item.id,
            'quantity': cart_item.quantity,
            'cart_count': cart.total_items
        })

class WishlistCheckView(generics.GenericAPIView):
    """
    GET /api/wishlist/check/?product_id=2
    Check if product is in wishlist
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        product_id = request.query_params.get('product_id')

        if not product_id:
            return Response(
                {'error': 'product_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        exists = WishlistItem.objects.filter(
            user=request.user,
            product_id=product_id
        ).exists()

        return Response({
            'product_id': int(product_id),
            'is_in_wishlist': exists,
            'wishlist_count': WishlistItem.objects.filter(
                user=request.user
            ).count()
        })
    
class WishlistRemoveView(generics.DestroyAPIView):
    """
    DELETE /api/wishlist/<item_id>/remove/
    Remove specific item from wishlist
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        wishlist_item = get_object_or_404(
            WishlistItem,
            id=item_id,
            user=request.user
        )
        product_name = wishlist_item.product.name
        wishlist_item.delete()

        return Response({
            'message': f'{product_name} removed from wishlist',
            'wishlist_count': WishlistItem.objects.filter(
                user=request.user
            ).count()
        })
