from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Cart, CartItem
from .serializers import (
    CartSerializer, AddToCartSerializer,
    UpdateCartItemSerializer, CartItemSerializer
)
from apps.products.models import Product, ProductColor, ProductSize


class CartDetailView(generics.RetrieveAPIView):
    """
    GET /api/cart/  → Get current user's cart with all items
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CartSerializer

    def get_object(self):
        cart, _ = Cart.objects.get_or_create(user=self.request.user)
        return cart


class CartCountView(APIView):
    """
    GET /api/cart/count/  → Get cart item count for cart icon
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return Response({
            'count': cart.total_items
        })


class AddToCartView(generics.CreateAPIView):
    """
    POST /api/cart/add/  → Add item to cart
    If same product+color+size exists, increase quantity
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AddToCartSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        cart, _ = Cart.objects.get_or_create(user=request.user)

        product = Product.objects.get(id=data['product_id'])
        color = ProductColor.objects.filter(id=data.get('color_id')).first()
        size = ProductSize.objects.filter(id=data.get('size_id')).first()
        quantity = data.get('quantity', 1)

        # Check if same item already in cart
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            color=color,
            size=size,
            defaults={'quantity': quantity}
        )

        if not created:
            # Item exists — increase quantity
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity'])

        return Response({
            'message': 'Item added to cart successfully',
            'item': CartItemSerializer(cart_item).data,
            'cart_count': cart.total_items
        }, status=status.HTTP_200_OK)


class UpdateCartItemView(generics.UpdateAPIView):
    """
    PATCH /api/cart/item/<item_id>/  → Update quantity or selection
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UpdateCartItemSerializer

    def get_object(self):
        return get_object_or_404(
            CartItem,
            id=self.kwargs['item_id'],
            cart__user=self.request.user
        )

    def patch(self, request, *args, **kwargs):
        cart_item = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        if 'quantity' in data:
            cart_item.quantity = data['quantity']
        if 'is_selected' in data:
            cart_item.is_selected = data['is_selected']

        cart_item.save()

        return Response({
            'message': 'Cart item updated',
            'item': CartItemSerializer(cart_item).data
        })


class RemoveCartItemView(generics.DestroyAPIView):
    """
    DELETE /api/cart/item/<item_id>/  → Remove item from cart
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(
            CartItem,
            id=self.kwargs['item_id'],
            cart__user=self.request.user
        )

    def destroy(self, request, *args, **kwargs):
        cart_item = self.get_object()
        cart_item.delete()
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return Response({
            'message': 'Item removed from cart',
            'cart_count': cart.total_items
        }, status=status.HTTP_200_OK)


class SelectAllCartItemsView(APIView):
    """
    POST /api/cart/select-all/  → Select or deselect all items
    Body: { "is_selected": true/false }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        is_selected = request.data.get('is_selected', True)
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart.items.all().update(is_selected=is_selected)
        return Response({
            'message': f'All items {"selected" if is_selected else "deselected"}'
        })


