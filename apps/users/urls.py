from django.urls import path
from django.urls import path
from .views import (
    SetDefaultAddressView, SignUpView, UpdateFcmTokenView, UserAddressesListView, 
    VerifyOTPView, LoginView, ForgotPasswordView, VerifyResetOTPView, ResetPasswordView, 
    UserProfileView, UserChangePasswordView,  UserNotificationListView,
    UserNotificationDetailView,UserMarkAllReadView,UserUnreadCountView,
)


app_name = "users"

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify_otp'),
    path('login/', LoginView.as_view(), name='login'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('verify-reset-otp/', VerifyResetOTPView.as_view(), name='verify_reset_otp'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
    path('addresses/', UserAddressesListView.as_view(), name='user-addresses-list'),
    path('set-default-address/', SetDefaultAddressView.as_view(), name='set-default-address'),
    path('update-fcm-token/', UpdateFcmTokenView.as_view(), name='update-fcm-token'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('profile/change-password/', UserChangePasswordView.as_view(), name='change-password'),
    # ── Notifications ──
    path('notifications/', UserNotificationListView.as_view(), name='user-notifications'),
    path('notifications/unread-count/', UserUnreadCountView.as_view(), name='unread-count'),
    path('notifications/mark-all-read/', UserMarkAllReadView.as_view(), name='mark-all-read'),
    path('notifications/<int:notification_id>/', UserNotificationDetailView.as_view(), name='notification-detail'),
]