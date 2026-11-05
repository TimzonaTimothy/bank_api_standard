import secrets
from decimal import Decimal
from functools import partial

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from core_apps.accounts.models import BankAccount, Transaction
from .emails import send_card_top_up_email
from .models import VirtualCard
from core_apps.accounts.services import validate_outgoing_limit


def generate_card_number() -> str:
    return "9999" + "".join(secrets.choice("0123456789") for _ in range(12))


def generate_expiry_date():
    return timezone.localdate() + relativedelta(years=3)


def validate_card_account(account: BankAccount) -> None:
    if not (account.fully_activated and account.kyc_verified):
        raise serializers.ValidationError({"bank_account": "Your bank account must be fully verified and activated."})
    if account.account_status != BankAccount.AccountStatus.ACTIVE:
        raise serializers.ValidationError({"bank_account": "Your bank account is inactive."})


@transaction.atomic
def create_virtual_card(user, account_number: str) -> VirtualCard:
    try:
        account = BankAccount.objects.select_for_update().get(
            user=user, account_number=account_number,
        )
    except BankAccount.DoesNotExist:
        raise serializers.ValidationError({"bank_account": "Account not found."})
    validate_card_account(account)
    card_number = generate_card_number()
    while VirtualCard.objects.filter(card_number=card_number).exists():
        card_number = generate_card_number()
    return VirtualCard.objects.create(
        bank_account=account, card_number=card_number,
        expiry_date=generate_expiry_date(),
    )


@transaction.atomic
def top_up_card(user, card_id, amount: Decimal) -> VirtualCard:
    # Lock the account first, so top-ups to different cards share the same lock.
    try:
        account_id = VirtualCard.objects.values_list("bank_account_id", flat=True).get(
            pk=card_id, bank_account__user=user,
        )
        account = BankAccount.objects.select_for_update().get(pk=account_id, user=user)
        card = VirtualCard.objects.select_for_update().get(pk=card_id, bank_account=account)
    except (VirtualCard.DoesNotExist, BankAccount.DoesNotExist):
        raise serializers.ValidationError({"card": "Card not found."})
    validate_card_account(account)
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise serializers.ValidationError({"amount": "Enter a positive amount with at most two decimal places."})
    if not card.is_active or card.expiry_date < timezone.localdate():
        raise serializers.ValidationError({"card": "This card is frozen or expired."})
    if account.account_balance < amount:
        raise serializers.ValidationError({"amount": "Insufficient funds for card top-up."})
    validate_outgoing_limit(account, amount)
    if card.balance + amount > Decimal("9999999999.99"):
        raise serializers.ValidationError({"amount": "The card balance limit would be exceeded."})
    account.account_balance -= amount
    card.balance += amount
    account.save(update_fields=["account_balance", "updated_at"])
    card.save(update_fields=["balance", "updated_at"])
    Transaction.objects.create(
        user=user, performed_by=user, sender=user, sender_account=account, amount=amount,
        description=f"Top-up to card ending {card.card_number[-4:]}",
        transaction_type=Transaction.TransactionType.WITHDRAWAL,
        status=Transaction.TransactionStatus.COMPLETED,
    )
    transaction.on_commit(partial(
        send_card_top_up_email, user=user, amount=amount,
        currency=account.get_currency_display(), card_number=card.masked_card_number,
        new_balance=card.balance,
    ))
    return card
