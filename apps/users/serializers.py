from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import User, UserAddress, UserNotification

User = get_user_model()


class SignUpSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration
    - Creates user with unverified status
    - Password is set but user needs OTP verification
    """
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={'input_type': 'password'},
        error_messages={
            'min_length': 'Password must be at least 8 characters long.'
        }
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )
    phone_number = serializers.CharField(
        required=True,
        allow_blank=True,
        max_length=20
    )

    class Meta:
        model = User
        fields = ['email', 'phone_number', 'password', 'password_confirm']

    def validate_email(self, value):
        """Make email case-insensitive and check uniqueness"""
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate(self, data):
        phone = data.get('phone_number')
        if phone and not phone.isdigit():
            raise serializers.ValidationError({
                "phone_number": "Phone number should contain only digits."
            })
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Passwords do not match."
            })

        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(
            password=password,
            is_active=True,
            **validated_data
        )

        # Generate and send OTP (will be handled in view)
        user.set_otp()
        return user

class OTPSerializer(serializers.Serializer):
    temp_token = serializers.CharField(required=True)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must contain only digits")
        return value
    

class LoginSerializer(TokenObtainPairSerializer):
    """
    Custom login serializer to return extra user info with tokens
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims (optional - you can remove if not needed)
        token['email'] = user.email
        token['is_verified'] = user.is_verified

        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Add extra response fields
        refresh = self.get_token(self.user)
        data["access"] = str(refresh.access_token)
        data["refresh"] = str(refresh)
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "is_verified": self.user.is_verified
        }
        
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No account found with this email.")
        return value


class VerifyResetOTPSerializer(serializers.Serializer):
    temp_token = serializers.CharField(required=True)
    otp = serializers.CharField(max_length=6, min_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    temp_token = serializers.CharField(required=True)
    new_password = serializers.CharField(min_length=8, write_only=True)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['new_password'] != data['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password_confirm": "Passwords do not match."
            })
        return data
    

class AddressListSerializer(serializers.ModelSerializer):
    address_id = serializers.IntegerField(source='id')
    class Meta:
        model = UserAddress
        fields = [
            'address_id',
            'full_name',
            'phone_or_email',
            'street_address',
            'apartment',
            'city',
            'zip_code',
            'is_default'
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'phone_number', 
            'full_name', 'first_name', 'last_name', 
            'is_verified', 'date_joined'
        ]
        read_only_fields = ['id', 'email', 'is_verified', 'date_joined', 'first_name', 'last_name']

    def get_full_name(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        return obj.first_name or obj.last_name or ""

    def validate(self, data):
        # Handle full_name splitting if provided in request
        full_name = self.initial_data.get('full_name')
        if full_name is not None:
            parts = full_name.strip().split(' ', 1)
            data['first_name'] = parts[0]
            data['last_name'] = parts[1] if len(parts) > 1 else ""
        
        # Check username uniqueness if changing
        username = data.get('username')
        if username:
            user = self.instance
            if User.objects.exclude(pk=user.pk).filter(username=username).exists():
                raise serializers.ValidationError({"username": "This username is already taken."})
                
        return data


class UserChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    new_password_confirm = serializers.CharField(required=True)

    def validate(self, data):
        if data['new_password'] != data['new_password_confirm']:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        return data


class UserNotificationSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = UserNotification
        fields = [
            'id', 'notification_type', 'title',
            'body', 'image_url', 'is_read', 'created_at'
        ]

    def get_image_url(self, obj):
        if obj.image:
            from cloudinary.utils import cloudinary_url
            url, _ = cloudinary_url(obj.image.public_id, secure=True)
            return url
        return None