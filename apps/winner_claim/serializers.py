from rest_framework import serializers


class ClaimInitiateRequestSerializer(serializers.Serializer):
    auction_id = serializers.IntegerField(required=True)
    address_id = serializers.IntegerField(required=False)


class ClaimInitiateResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    checkout_url = serializers.URLField()
    amount_sar = serializers.DecimalField(max_digits=12, decimal_places=2)