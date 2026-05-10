from rest_framework import serializers
from .models import UserWallet, CoinTransaction

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserWallet
        fields = ['coins', 'updated_at']

class CoinPackageListSerializer(serializers.ModelSerializer):
    class Meta:
        from apps.admin_api.models import CoinPackage
        model = CoinPackage
        fields = ['id', 'coins', 'price_sar']

class BuyCoinPackageSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()

class CoinTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinTransaction
        fields = ['id', 'transaction_type', 'amount', 'description', 'created_at']
