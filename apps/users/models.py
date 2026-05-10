from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.conf import settings
import random
from cloudinary.models import CloudinaryField


# --------------------------------------------------
# USER MANAGER
# --------------------------------------------------
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, **extra_fields)


# --------------------------------------------------
# USER MODEL
# --------------------------------------------------
class User(AbstractUser):
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)

    email = models.EmailField(unique=True)

    phone_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True
    )

    # FCM
    fcm_token = models.CharField(max_length=255, null=True, blank=True)
    fcm_token_updated_at = models.DateTimeField(null=True, blank=True)

    is_verified = models.BooleanField(default=False)

    # OTP (Signup)
    otp = models.CharField(max_length=6, null=True, blank=True)
    otp_created_at = models.DateTimeField(null=True, blank=True)

    # OTP (Reset)
    reset_otp = models.CharField(max_length=6, null=True, blank=True)
    reset_otp_created_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    # --------------------------------------------------
    # FCM
    # --------------------------------------------------
    def update_fcm_token(self, token):
        self.fcm_token = token
        self.fcm_token_updated_at = timezone.now()
        self.save(update_fields=["fcm_token", "fcm_token_updated_at"])

    # --------------------------------------------------
    # OTP HELPERS (FIXED LOGIC)
    # --------------------------------------------------
    def set_otp(self, length=6, expiry_minutes=10):
        self.otp = "".join(str(random.randint(0, 9)) for _ in range(length))
        self.otp_created_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes)
        self.save(update_fields=["otp", "otp_created_at"])
        return self.otp

    def verify_otp(self, code):
        if not self.otp or not self.otp_created_at:
            return False

        if timezone.now() > self.otp_created_at:
            self.clear_otp()
            return False

        if self.otp != code:
            return False

        self.is_verified = True
        self.clear_otp()
        self.save(update_fields=["is_verified"])
        return True

    def clear_otp(self):
        self.otp = None
        self.otp_created_at = None
        self.save(update_fields=["otp", "otp_created_at"])

    # Reset OTP
    def set_reset_otp(self, length=6, expiry_minutes=10):
        self.reset_otp = "".join(str(random.randint(0, 9)) for _ in range(length))
        self.reset_otp_created_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes)
        self.save(update_fields=["reset_otp", "reset_otp_created_at"])
        return self.reset_otp

    def verify_reset_otp(self, code):
        if not self.reset_otp or not self.reset_otp_created_at:
            return False

        if timezone.now() > self.reset_otp_created_at:
            self.clear_reset_otp()
            return False

        if self.reset_otp != code:
            return False

        self.clear_reset_otp()
        return True

    def clear_reset_otp(self):
        self.reset_otp = None
        self.reset_otp_created_at = None
        self.save(update_fields=["reset_otp", "reset_otp_created_at"])


# --------------------------------------------------
# USER ADDRESS (FIXED - NO AUTO SAVE BUG)
# --------------------------------------------------
class UserAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="addresses"
    )

    full_name = models.CharField(max_length=255)
    phone_or_email = models.CharField(max_length=100)
    street_address = models.CharField(max_length=255)
    apartment = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.full_name} - {self.city}"

    def save(self, *args, **kwargs):
        # FIX: only set default if user has NO other addresses
        if not self.pk and not UserAddress.objects.filter(user=self.user).exists():
            self.is_default = True

        super().save(*args, **kwargs)


# --------------------------------------------------
# NOTIFICATIONS
# --------------------------------------------------
class UserNotification(models.Model):
    NOTIFICATION_TYPES = [
        ("announcement", "Announcement"),
        ("auction_win", "Auction Win"),
        ("coins_added", "Coins Added"),
        ("coins_refunded", "Coins Refunded"),
        ("order_update", "Order Update"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications"
    )

    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        default="announcement"
    )

    title = models.CharField(max_length=255)
    body = models.TextField()

    image = CloudinaryField(
        "notification_image",
        resource_type="image",
        blank=True,
        null=True
    )

    # IMPORTANT: string reference avoids circular import
    announcement = models.ForeignKey(
        "admin_api.Announcement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications"
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.title}"