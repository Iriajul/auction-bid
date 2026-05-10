from django.urls import path

from apps.products.order_views import CancelOrderView, CheckoutPreviewView, OrderAgainView, OrderPaymentCancelView, PlaceOrderView, ProductReviewsView, UserOrderDetailView, UserOrderListView, WriteReviewView
from .views import ProductListCreateView, ProductDetailView, UserCategoryListView, UserProductDetailView, UserProductListView

app_name = 'products'

urlpatterns = [
    path('prod', ProductListCreateView.as_view(), name='product-list-create'),
    path('<int:product_id>/', ProductDetailView.as_view(), name='product-detail'),
    path('store/', UserProductListView.as_view(), name='user-product-list'),
    path('store/<int:product_id>/', UserProductDetailView.as_view(), name='user-product-detail'),
    path('categories/', UserCategoryListView.as_view(), name='user-category-list'), 
    # ── Reviews ──
    path('store/<int:product_id>/reviews/', ProductReviewsView.as_view(), name='product-reviews'),

    # ── Orders ──
    path('orders/', UserOrderListView.as_view(), name='order-list'),
    path('orders/checkout-preview/', CheckoutPreviewView.as_view(), name='checkout-preview'),
    path('orders/place/', PlaceOrderView.as_view(), name='place-order'),
    path('orders/payment-cancel/', OrderPaymentCancelView.as_view(), name='order-payment-cancel'),
    path('orders/<int:order_id>/', UserOrderDetailView.as_view(), name='order-detail'),
    path('orders/<int:order_id>/cancel/', CancelOrderView.as_view(), name='order-cancel'),
    path('orders/<int:order_id>/order-again/', OrderAgainView.as_view(), name='order-again'),
    path('orders/<int:order_id>/review/<int:product_id>/', WriteReviewView.as_view(), name='write-review'),
]