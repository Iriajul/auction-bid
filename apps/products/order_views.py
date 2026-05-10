from time import timezone

import stripe
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from decimal import Decimal
from django.db.models import Count, Avg
from .models import Order, OrderItem, OrderStatus, Product, ProductColor, ProductSize, ProductReview
from .order_serializers import (
    OrderSerializer, PlaceOrderSerializer, WriteReviewSerializer,
    ReviewSerializer, CheckoutPreviewSerializer, CartCheckoutSerializer
)
from apps.users.models import UserAddress
from apps.cart.models import Cart

stripe.api_key = settings.STRIPE_SECRET_KEY


# ─────────────────────────────────────────
# CHECKOUT PREVIEW
# ─────────────────────────────────────────
class CheckoutPreviewView(generics.GenericAPIView):
    """
    POST /api/products/orders/checkout-preview/
    Shows order summary before payment
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.data.get('is_buy_now'):
            return CheckoutPreviewSerializer
        return CartCheckoutSerializer

    def post(self, request, *args, **kwargs):
        is_buy_now = request.data.get('is_buy_now', False)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if is_buy_now:
            product = Product.objects.get(id=data['product_id'])
            color = ProductColor.objects.filter(id=data.get('color_id')).first()
            size = ProductSize.objects.filter(id=data.get('size_id')).first()
            quantity = data.get('quantity', 1)
            discount = Decimal(product.discount_percentage) / Decimal(100)
            unit_price = product.price * (1 - discount)
            total = unit_price * quantity
            thumbnail = None
            first_image = product.images.first()
            if first_image:
                from cloudinary.utils import cloudinary_url
                thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)
            items = [{
                'product_id': product.id,
                'product_name': product.name,
                'thumbnail': thumbnail, 
                'color': color.name if color else None,
                'size': size.name if size else None,
                'quantity': quantity,
                'unit_price': float(unit_price),
                'total': float(total),
                'discount_percentage': product.discount_percentage,
                'original_price': float(product.price),
            }]
        else:
            cart, _ = Cart.objects.get_or_create(user=request.user)
            selected_items = cart.items.filter(
                is_selected=True
            ).select_related('product', 'color', 'size')

            if not selected_items.exists():
                return Response(
                    {'error': 'No items selected in cart'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            items = []
            for item in selected_items:
                discount = Decimal(item.product.discount_percentage) / Decimal(100)
                unit_price = item.product.price * (1 - discount)
                item_total = unit_price * item.quantity
                thumbnail = None
                first_image = item.product.images.first()
                if first_image:
                    from cloudinary.utils import cloudinary_url
                    thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)

                items.append({
                    'product_id': item.product.id,
                    'product_name': item.product.name,
                    'thumbnail': thumbnail,  
                    'color': item.color.name if item.color else None,
                    'size': item.size.name if item.size else None,
                    'quantity': item.quantity,
                    'unit_price': float(unit_price),
                    'total': float(item_total),
                    'discount_percentage': item.product.discount_percentage,
                    'original_price': float(item.product.price),
                })

        address_id = request.data.get('address_id')
        address = get_object_or_404(UserAddress, id=address_id, user=request.user)

        return Response({
            'address': {
                'id': address.id,
                'full_name': address.full_name,
                'phone_or_email': address.phone_or_email,
                'street_address': address.street_address,
                'city': address.city,
                'zip_code': address.zip_code,
            },
            'items': items,
            'total': float(sum(i['total'] for i in items))
        })


# ─────────────────────────────────────────
# PLACE ORDER
# ─────────────────────────────────────────
class PlaceOrderView(generics.CreateAPIView):
    """
    POST /api/products/orders/place/
    Creates order and returns Stripe checkout URL
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PlaceOrderSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        address = get_object_or_404(
            UserAddress,
            id=data['address_id'],
            user=request.user
        )

        is_buy_now = data.get('is_buy_now', False)
        order_items_data = []
        total = Decimal(0)

        if is_buy_now:
            product = get_object_or_404(Product, id=data['product_id'])
            color = ProductColor.objects.filter(id=data.get('color_id')).first()
            size = ProductSize.objects.filter(id=data.get('size_id')).first()
            quantity = data.get('quantity', 1)

            discount = Decimal(product.discount_percentage) / Decimal(100)
            unit_price = product.price * (1 - discount)
            total = unit_price * quantity

            order_items_data.append({
                'product': product,
                'color': color,
                'size': size,
                'quantity': quantity,
                'price': product.price,
                'discount_percentage': product.discount_percentage,
            })
        else:
            cart, _ = Cart.objects.get_or_create(user=request.user)
            selected_items = cart.items.filter(
                is_selected=True
            ).select_related('product', 'color', 'size')

            if not selected_items.exists():
                return Response(
                    {'error': 'No items selected in cart'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            for item in selected_items:
                discount = Decimal(item.product.discount_percentage) / Decimal(100)
                unit_price = item.product.price * (1 - discount)
                total += unit_price * item.quantity
                order_items_data.append({
                    'product': item.product,
                    'color': item.color,
                    'size': item.size,
                    'quantity': item.quantity,
                    'price': item.product.price,
                    'discount_percentage': item.product.discount_percentage,
                })

        Order.objects.filter(
            user=request.user,
            payment_status='unpaid'
        ).delete()

        # ── Create Order ──
        order = Order.objects.create(
            user=request.user,
            address=address,
            total_amount=total,
            is_buy_now=is_buy_now,
            status=OrderStatus.PENDING,
            payment_status='unpaid'
        )

        for item_data in order_items_data:
            OrderItem.objects.create(order=order, **item_data)

        # ── Stripe Session ──
        try:
            line_items = []
            for item_data in order_items_data:
                discount = Decimal(item_data['discount_percentage']) / Decimal(100)
                unit_price = item_data['price'] * (1 - discount)
                line_items.append({
                    'price_data': {
                        'currency': 'sar',
                        'product_data': {
                            'name': item_data['product'].name,
                        },
                        'unit_amount': int(unit_price * 100),
                    },
                    'quantity': item_data['quantity'],
                })

            # Build base URL separately to avoid encoding {CHECKOUT_SESSION_ID}
            base_success_url = request.build_absolute_uri('/api/packages/checkout-success/')

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=base_success_url + '?session_id={CHECKOUT_SESSION_ID}', 
                cancel_url=request.build_absolute_uri(
                    '/api/products/orders/payment-cancel/'
                ),
                metadata={
                    'payment_type': 'product_order', 
                    'order_id': order.id,
                    'user_id': request.user.id,
                }
            )
            order.stripe_session_id = session.id
            order.save(update_fields=['stripe_session_id'])

            return Response({
                'order_id': order.id,
                'tracking_id': order.tracking_id,
                'total_amount': float(total),
                'stripe_session_id': session.id,
                'checkout_url': session.url,
            }, status=status.HTTP_201_CREATED)

        except stripe.error.StripeError as e:
            order.delete()
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class OrderPaymentCancelView(generics.GenericAPIView):
    """
    GET /api/products/orders/payment-cancel/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response({'message': 'Payment cancelled'})


# ─────────────────────────────────────────
# ORDER LIST
# ─────────────────────────────────────────
class UserOrderListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer  # keep existing serializer

    def get_queryset(self):
        return Order.objects.filter(
            user=self.request.user,
            payment_status='paid'
        ).prefetch_related(
            'items__product__images',
            'items__color',
            'items__size',
        ).select_related('address').order_by('-created_at')

    def list(self, request, *args, **kwargs):
        from decimal import Decimal
        from apps.winner_claim.models import ClaimAttempt
        from cloudinary.utils import cloudinary_url

        combined = []

        # ── Store Orders ──
        for order in self.get_queryset():
            items = []
            for item in order.items.all():
                thumbnail = None
                first_image = item.product.images.first() if item.product else None
                if first_image:
                    thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)

                discount = Decimal(item.discount_percentage) / Decimal(100)
                discounted_price = float(item.price * (1 - discount))

                items.append({
                    'order_item_id': item.id,
                    'product': {
                        'product_id': item.product.id if item.product else None,
                        'name': item.product.name if item.product else None,
                        'thumbnail': thumbnail,
                    },
                    'size_name': item.size.name if item.size else None,
                    'color_name': item.color.name if item.color else None,
                    'quantity': item.quantity,
                    'price': str(item.price),
                    'discount_percentage': item.discount_percentage,
                    'discounted_price': discounted_price,
                    'item_total': float(item.item_total),
                })

            combined.append({
                'order_type': 'store',
                'order_id': order.id,
                'tracking_id': order.tracking_id,
                'status': order.status,
                'payment_status': order.payment_status,
                'payment_method': order.payment_method,
                'total_amount': str(order.total_amount),
                'address': {
                    'address_id': order.address.id if order.address else None,
                    'full_name': order.address.full_name if order.address else None,
                    'phone_or_email': order.address.phone_or_email if order.address else None,
                    'street_address': order.address.street_address if order.address else None,
                    'apartment': order.address.apartment if order.address else None,
                    'city': order.address.city if order.address else None,
                    'zip_code': order.address.zip_code if order.address else None,
                } if order.address else None,
                'items': items,
                'can_cancel': order.status == 'processing',
                'can_review': order.status == 'delivered',
                'created_at': order.created_at,
                'updated_at': order.updated_at,
            })

        # ── Auction Claim Orders ──
        claim_orders = ClaimAttempt.objects.filter(
            win_record__winner=request.user,
            payment_completed=True
        ).select_related(
            'win_record__auction',
            'win_record__shipping_address',  
        ).prefetch_related(
            'win_record__auction__product_image'
        ).order_by('-completed_at')

        for claim in claim_orders:
            win = claim.win_record
            auction = win.auction
            shipping = win.shipping_address  

            thumbnail = None
            first_image = auction.product_image.first()
            if first_image:
                thumbnail, _ = cloudinary_url(first_image.image.public_id, secure=True)

            combined.append({
                'order_type': 'auction',
                'order_id': f"AUC-{claim.id}",
                'tracking_id': f"#AUC-{auction.id}",
                'status': claim.delivery_status,
                'payment_status': 'paid',
                'payment_method': 'card',
                'total_amount': str(win.final_bid_amount),
                'address': {                          
                    'address_id': shipping.id,
                    'full_name': shipping.full_name,
                    'phone_or_email': shipping.phone_or_email,
                    'street_address': shipping.street_address,
                    'apartment': shipping.apartment,
                    'city': shipping.city,
                    'zip_code': shipping.zip_code,
                } if shipping else None,
                'items': [{
                    'order_item_id': claim.id,
                    'product': {
                        'product_id': auction.id,
                        'name': auction.product_name,
                        'thumbnail': thumbnail,
                    },
                    'size_name': None,
                    'color_name': None,
                    'quantity': 1,
                    'price': str(win.final_bid_amount),
                    'discount_percentage': 0,
                    'discounted_price': float(win.final_bid_amount),
                    'item_total': float(win.final_bid_amount),
                }],
                'can_cancel': False,
                'can_review': False,
                'created_at': claim.completed_at,
                'updated_at': claim.completed_at,
            })

        # ── Sort by created_at descending ──
        combined.sort(key=lambda x: x['created_at'] or timezone.datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        return Response(combined)

# ─────────────────────────────────────────
# ORDER DETAIL / TRACKING
# ─────────────────────────────────────────
class UserOrderDetailView(generics.RetrieveAPIView):
    """
    GET /api/products/orders/<order_id>/
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_object(self):
        return get_object_or_404(
            Order,
            id=self.kwargs['order_id'],
            user=self.request.user,
            payment_status='paid'  
        )

# ─────────────────────────────────────────
# CANCEL ORDER
# ─────────────────────────────────────────
class CancelOrderView(generics.UpdateAPIView):
    """
    POST /api/products/orders/<order_id>/cancel/
    Only when status is pending
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_object(self):
        return get_object_or_404(
            Order,
            id=self.kwargs['order_id'],
            user=self.request.user
        )

    def update(self, request, *args, **kwargs):
        order = self.get_object()

        if order.status != OrderStatus.PROCESSING:
            return Response(
                {'error': 'Order can only be cancelled when status is processing'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = OrderStatus.CANCELLED
        order.save(update_fields=['status'])

        return Response({
            'message': f'Order {order.tracking_id} cancelled successfully'
        })


# ─────────────────────────────────────────
# ORDER AGAIN
# ─────────────────────────────────────────
class OrderAgainView(generics.GenericAPIView):
    """
    POST /api/products/orders/<order_id>/order-again/
    Adds items back to cart
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from apps.cart.models import Cart, CartItem

        order = get_object_or_404(
            Order,
            id=self.kwargs['order_id'],
            user=request.user
        )
        cart, _ = Cart.objects.get_or_create(user=request.user)

        for item in order.items.select_related('product', 'color', 'size'):
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=item.product,
                color=item.color,
                size=item.size,
                defaults={'quantity': item.quantity}
            )
            if not created:
                cart_item.quantity += item.quantity
                cart_item.save(update_fields=['quantity'])

        return Response({
            'message': 'Items added to cart successfully',
            'cart_count': cart.total_items
        })


# ─────────────────────────────────────────
# WRITE REVIEW
# ─────────────────────────────────────────
class WriteReviewView(generics.CreateAPIView):
    """
    POST /api/products/orders/<order_id>/review/<product_id>/
    Only after delivery
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WriteReviewSerializer

    def create(self, request, *args, **kwargs):
        order = get_object_or_404(
            Order,
            id=self.kwargs['order_id'],
            user=request.user
        )

        if order.status != OrderStatus.DELIVERED:
            return Response(
                {'error': 'You can only review after order is delivered'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not order.items.filter(product_id=self.kwargs['product_id']).exists():
            return Response(
                {'error': 'Product not found in this order'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if ProductReview.objects.filter(
            user=request.user,
            product_id=self.kwargs['product_id'],
            order=order
        ).exists():
            return Response(
                {'error': 'You already reviewed this product'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = ProductReview.objects.create(
            user=request.user,
            product_id=self.kwargs['product_id'],
            order=order,
            **serializer.validated_data
        )

        return Response({
            'message': 'Review submitted successfully',
            'review': ReviewSerializer(review).data
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────
# GET PRODUCT REVIEWS
# ─────────────────────────────────────────
class ProductReviewsView(generics.ListAPIView):
    """
    GET /api/products/store/<product_id>/reviews/
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ReviewSerializer

    def get_queryset(self):
        return ProductReview.objects.filter(
            product_id=self.kwargs['product_id']
        ).select_related('user')

    def list(self, request, *args, **kwargs):
        from django.db.models import Avg

        queryset = self.get_queryset()
        total_reviews = queryset.count()
        avg = queryset.aggregate(avg=Avg('rating'))['avg']
        average_rating = round(avg, 1) if avg else 0.0

        # ── Breakdown per star ──
        breakdown = []
        for star in [5, 4, 3, 2, 1]:
            count = queryset.filter(rating=star).count()
            breakdown.append({
                'star': star,
                'count': count,
            })

        # ── Reviews list ──
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'average_rating': average_rating,
            'total_reviews': total_reviews,
            'breakdown': breakdown,
            'reviews': serializer.data
        })