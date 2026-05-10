from django.urls import path
from .views import AdminMarkAuctionDeliveredView, ClaimInitiateView, PaymentSuccessView, AdminAuctionOrderDetailView, AdminAuctionOrderListView

urlpatterns = [
    path('payment/initiate/', ClaimInitiateView.as_view(), name='claim-payment-initiate'),
    path('payment/success/', PaymentSuccessView.as_view(), name='claim-payment-success'),
    path('auction-orders/', AdminAuctionOrderListView.as_view(), name='admin-auction-order-list'),
    path('auction-orders/<int:claim_id>/', AdminAuctionOrderDetailView.as_view(), name='admin-auction-order-detail'),
    path('auction-orders/<int:claim_id>/mark-delivered/', AdminMarkAuctionDeliveredView.as_view(), name='admin-auction-mark-delivered'),
]