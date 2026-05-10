from django.contrib import admin
from .models import User
from apps.packages.models import UserWallet, CoinTransaction

admin.site.register(User)
admin.site.register(UserWallet)
admin.site.register(CoinTransaction)