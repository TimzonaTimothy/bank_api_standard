from decimal import Decimal

from rest_framework import serializers

from .models import VirtualCard
from .utils import create_virtual_card


class CardSerializer(serializers.ModelSerializer):
    bank_account = serializers.CharField(source="bank_account.account_number", read_only=True)
    currency = serializers.CharField(source="bank_account.currency", read_only=True)
    card_number = serializers.CharField(source="masked_card_number", read_only=True)

    class Meta:
        model = VirtualCard
        fields = [
            "id", "bank_account", "card_number", "currency", "balance",
            "expiry_date", "is_active", "created_at",
        ]
        read_only_fields = fields


class CreateCardSerializer(serializers.Serializer):
    bank_account = serializers.CharField(max_length=20)

    def create(self, validated_data):
        return create_virtual_card(
            self.context["request"].user, validated_data["bank_account"],
        )

    def to_representation(self, instance):
        return CardSerializer(instance, context=self.context).data


class CardTopUpSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"),
    )


class CardStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = VirtualCard
        fields = ["is_active"]
        extra_kwargs = {"is_active": {"required": True}}
