from django.shortcuts import get_object_or_404
from cloudinary.utils import cloudinary_url
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken
from django.core.mail import send_mail
from django.conf import settings
from .serializers import (
    AddressListSerializer, SignUpSerializer, OTPSerializer, LoginSerializer, 
    ForgotPasswordSerializer, VerifyResetOTPSerializer, ResetPasswordSerializer, 
    UserProfileSerializer, UserChangePasswordSerializer, UserNotificationSerializer
)
from .models import User, UserAddress, UserNotification
from datetime import timedelta
from fcm_django.models import FCMDevice




class SignUpView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = SignUpSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            
            # Send OTP via email
            subject = "Luktaa Verification Code"
            message = f"Your verification code is: {user.otp}\n\nThis code expires in 10 minutes."
            
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Email error: {e}")

            # Generate shortlived temp token
            refresh = RefreshToken.for_user(user)
            refresh.access_token.set_exp(lifetime=timedelta(minutes=15))  # short expiry
            
            return Response({
                "message": "Account created. Please verify your email with OTP.",
                "email": user.email,
                "temp_token": str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    """
    Verify OTP using temp_token sent in body
    After success → account is activated, but no tokens are returned
    User must login separately
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        temp_token = request.data.get('temp_token')
        if not temp_token:
            return Response(
                {"error": "temp_token is required in request body"},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Validate the temporary token
        try:
            untyped_token = UntypedToken(temp_token)
            user_id = untyped_token.payload.get('user_id')
            if not user_id:
                raise InvalidToken("Invalid token payload")
            user = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, KeyError):
            return Response(
                {"error": "Invalid or expired temporary token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Validate OTP
        serializer = OTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if user.verify_otp(serializer.validated_data['otp']):
            user.is_active = True
            user.save(update_fields=['is_active'])
            return Response({
                "message": "Email verified successfully. You can now login with your email and password.",
            }, status=status.HTTP_200_OK)
        return Response(
            {"error": "Invalid or expired OTP"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
class LoginView(TokenObtainPairView):
    """
    Login with email and password
    Returns access + refresh tokens + basic user info
    """
    serializer_class = LoginSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class ForgotPasswordView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        user = User.objects.get(email=email)

        # Generate reset OTP
        otp = user.set_reset_otp()

        # Send OTP email
        masked_email = f"{email[0]}{'*' * (len(email.split('@')[0]) - 2)}@{email.split('@')[1]}"
        subject = "Luktaa Password Reset Code"
        message = f"Your reset code is: {otp}\n\nExpires in 10 minutes."

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Email error: {e}")

        # Generate short-lived temp token tied to this user
        refresh = RefreshToken.for_user(user)
        refresh.access_token.set_exp(lifetime=timedelta(minutes=15))

        return Response({
            "message": "Reset code sent to your email.",
            "masked_email": masked_email,
            "temp_token": str(refresh.access_token),
        }, status=status.HTTP_200_OK)


class VerifyResetOTPView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = VerifyResetOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        temp_token = serializer.validated_data['temp_token']

        # Validate token and get user
        try:
            untyped_token = UntypedToken(temp_token)
            user_id = untyped_token.payload.get('user_id')
            if not user_id:
                raise InvalidToken("Invalid token payload")
            user = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, KeyError):
            return Response(
                {"error": "Invalid or expired temporary token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check OTP
        if not user.verify_reset_otp(serializer.validated_data['otp']):
            return Response(
                {"error": "Invalid or expired OTP"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "message": "OTP verified successfully. You can now set a new password."
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        temp_token = serializer.validated_data['temp_token']

        # Validate token and get user
        try:
            untyped_token = UntypedToken(temp_token)
            user_id = untyped_token.payload.get('user_id')
            if not user_id:
                raise InvalidToken("Invalid token payload")
            user = User.objects.get(id=user_id)
        except (InvalidToken, User.DoesNotExist, KeyError):
            return Response(
                {"error": "Invalid or expired temporary token"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])

        return Response({
            "message": "Password reset successfully. Please login with your new password."
        }, status=status.HTTP_200_OK)



class UserAddressesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        addresses = UserAddress.objects.filter(user=request.user).order_by('-is_default', '-created_at')
        serializer = AddressListSerializer(addresses, many=True)
        return Response({
            "addresses": serializer.data,
            "default_address_id": next((a.id for a in addresses if a.is_default), None)
        })
    

class SetDefaultAddressView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        address_id = request.data.get('address_id')
        if not address_id:
            return Response({"error": "address_id is required"}, status=400)

        try:
            address = UserAddress.objects.get(id=address_id, user=request.user)
        except UserAddress.DoesNotExist:
            return Response({"error": "Address not found"}, status=404)

        # Reset all other defaults
        UserAddress.objects.filter(user=request.user).update(is_default=False)
        address.is_default = True
        address.save()

        return Response({"message": "Default address updated", "default_id": address.id})



class UpdateFcmTokenView(APIView):
    """
    POST /api/users/update-fcm-token/
    Body: {"fcm_token": "dABc123...long-token", "device_type": "android"}
    
    Saves or updates the user's FCM device token.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('fcm_token')
        device_type = request.data.get('device_type', 'android')  # default to android

        if not token:
            return Response(
                {"error": "fcm_token is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Save or update the device token
        device, created = FCMDevice.objects.update_or_create(
            user=request.user,
            registration_id=token,
            defaults={
                'type': device_type,
                'active': True,
            }
        )

        return Response(
            {
                "message": "FCM token saved/updated successfully",
                "created": created,
                "device_id": device.id,
                "token": token[:20] + "..." 
            },
            status=status.HTTP_200_OK
        )


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    GET /api/users/profile/ -> Get current user profile
    PATCH /api/users/profile/ -> Update profile (first_name, last_name, phone_number)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


class UserChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UserChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not user.check_password(serializer.validated_data['old_password']):
                return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
            
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            return Response({"detail": "Password updated successfully"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

# ─────────────────────────────────────────
# Add these imports at the top of the file
# ─────────────────────────────────────────

class UserNotificationListView(generics.ListAPIView):
    """
    GET /api/users/notifications/
    Returns all notifications + unread count
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSerializer

    def get_queryset(self):
        return UserNotification.objects.filter(
            user=self.request.user
        ).order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        unread_count = queryset.filter(is_read=False).count()

        return Response({
            'unread_count': unread_count,
            'notifications': serializer.data
        })


class UserNotificationDetailView(generics.RetrieveAPIView):
    """
    GET /api/users/notifications/<notification_id>/
    Marks as read + returns full detail with announcement if applicable
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSerializer

    def get_object(self):
        notification = get_object_or_404(
            UserNotification,
            id=self.kwargs['notification_id'],
            user=self.request.user
        )
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return notification

    def retrieve(self, request, *args, **kwargs):
        notification = self.get_object()
        serializer = self.get_serializer(notification)
        data = serializer.data
        if notification.announcement:
            image_url = None
            if notification.announcement.image:
                image_url, _ = cloudinary_url(
                    notification.announcement.image.public_id, secure=True
                )
            data['announcement'] = {
                'announcement_id': notification.announcement.id,
                'title': notification.announcement.title,
                'description': notification.announcement.description,
                'image_url': image_url,
                'created_at': notification.announcement.created_at,
            }

        return Response(data)


class UserMarkAllReadView(APIView):
    """
    POST /api/users/notifications/mark-all-read/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = UserNotification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True)

        return Response({
            'message': f'{updated} notifications marked as read'
        })


class UserUnreadCountView(APIView):
    """
    GET /api/users/notifications/unread-count/
    For notification bell badge count
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = UserNotification.objects.filter(
            user=request.user,
            is_read=False
        ).count()
        return Response({'unread_count': count})
