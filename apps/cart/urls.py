from django.urls import path
from .views import (
    CartDetailView, CartCountView, AddToCartView,
    UpdateCartItemView, RemoveCartItemView,
    SelectAllCartItemsView
)

app_name = 'cart'

urlpatterns = [
    path('', CartDetailView.as_view(), name='cart-detail'),
    path('count/', CartCountView.as_view(), name='cart-count'),
    path('add/', AddToCartView.as_view(), name='cart-add'),
    path('item/<int:item_id>/', UpdateCartItemView.as_view(), name='cart-item-update'),
    path('item/<int:item_id>/remove/', RemoveCartItemView.as_view(), name='cart-item-remove'),
    path('select-all/', SelectAllCartItemsView.as_view(), name='cart-select-all'),
]