from django.contrib import admin
from rest_framework_simplejwt.views import TokenRefreshView
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.urls')),
    path('api/admin/', include('apps.admin_api.urls')), 
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/packages/', include('apps.packages.urls')),
    path('api/auction/', include('apps.auction.urls')),
    path('api/winner-claim/', include('apps.winner_claim.urls')),
    path('api/products/', include('apps.products.urls')),
    path('api/cart/', include('apps.cart.urls')),
    path('api/wishlist/', include('apps.wishlist.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
