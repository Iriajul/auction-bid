from django.urls import path
from .views import (
    UserWalletView, CoinPackagesUserView, CreateCheckoutSessionView, 
    StripeWebhookView, CoinPurchaseHistoryView, CoinExpenseHistoryView,
    CheckoutSuccessView
)

app_name = "packages"

urlpatterns = [
    path('wallet/', UserWalletView.as_view(), name='user_wallet'),
    path('', CoinPackagesUserView.as_view(), name='coin_packages_list'),
    path('buy/', CreateCheckoutSessionView.as_view(), name='buy_coin_package'),
    path('webhook/stripe/', StripeWebhookView.as_view(), name='stripe_webhook'),
    path('purchase-history/', CoinPurchaseHistoryView.as_view(), name='purchase_history'),
    path('expense-history/', CoinExpenseHistoryView.as_view(), name='expense_history'),
    path('checkout-success/', CheckoutSuccessView.as_view(), name='checkout_success'),
]