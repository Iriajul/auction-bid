from django.urls import path
from .views import (
    WishlistListView,
    WishlistToggleView,
    WishlistAddToCartView,
    WishlistCheckView,
    WishlistRemoveView,
)

app_name = 'wishlist'

urlpatterns = [
    path('', WishlistListView.as_view(), name='wishlist-list'),
    path('toggle/', WishlistToggleView.as_view(), name='wishlist-toggle'),
    path('check/', WishlistCheckView.as_view(), name='wishlist-check'),
    path('<int:item_id>/add-to-cart/', WishlistAddToCartView.as_view(), name='wishlist-add-to-cart'),
     path('<int:item_id>/remove/', WishlistRemoveView.as_view(), name='wishlist-remove'),
]