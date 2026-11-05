from django.db import models
from django.contrib.auth import get_user_model 
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP
# Create your models here.

from core_apps.common.models import TimeStampedModel

User = get_user_model()

class BankAccount(TimeStampedModel):
    class AccountType(models.TextChoices):
        CURRENT = "current", _("Current")
        SAVINGS = "savings", _("Savings")
        
    class AccountStatus(models.TextChoices):
        ACTIVE = "active", _("Active")
        INACTIVE = "in-active", _("In-active")
        
    class AccountCurrency(models.TextChoices):
        DOLLAR = ("us_dollar", _("US Dollar"))
        POUND_STERLING = ("pound_sterling", _("Pound Sterling"))
        NAIRA = ("naira", _("Naira"))
        
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bank_accounts")
    account_number = models.CharField(_("Account Number"), max_length=20, unique=True)
    account_balance = models.DecimalField(_("Account Balance"), max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(_("Currency"), max_length=20, choices=AccountCurrency.choices, default=AccountCurrency.NAIRA)
    account_status = models.CharField(_("Account Status"), max_length=10, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    account_type = models.CharField(_("Account Type"), max_length=30, choices=AccountType.choices)
    is_primary = models.BooleanField(_("Primary Account"), default=False)
    kyc_submitted = models.BooleanField(_("KYC Submitted"), default=False)
    kyc_verified = models.BooleanField(_("KYC Verified"), default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_accounts") 
    verification_date = models.DateTimeField(_("Verification Date"), null=True, blank=True)
    verfication_notes = models.TextField(_("Verification Notes"), null=True, blank=True)
    fully_activated = models.BooleanField(_("Fully Activated"), default=False)

    def calculate_interest(self, days: int = 1) -> Decimal:
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise ValueError("Days must be a positive integer.")
        rate = Decimal(str(settings.SAVINGS_ANNUAL_INTEREST_RATE))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise ValueError("Savings annual interest rate must be between 0 and 1.")
        if self.account_type != self.AccountType.SAVINGS or self.account_balance <= 0:
            return Decimal("0.00")
        return (self.account_balance * rate * days / Decimal("365")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    
    def __str__(self) -> str:
        return f"{self.user.full_name}'s - {self.get_currency_display()} {self.get_account_type_display()} Account - {self.account_number}"
    
    class Meta:
        verbose_name = _("Bank Account")
        constraints = [models.CheckConstraint(check=models.Q(account_balance__gte=0), name="bank_balance_nonnegative")]
        verbose_name_plural = _("Bank Accounts")
        ordering = ["-created_at"]
        unique_together = ("user", "account_type", "currency")  # Ensure a user cannot have multiple accounts of the same type and currency
        
    
    def clean(self): 
        if self.account_balance < 0: 
            raise ValidationError(_("Account balance cannot be negative."))
        
    def save(self, *args, **kwargs) -> None:
        if self.is_primary:
            # Ensure only one primary account per user
            BankAccount.objects.filter(user=self.user).update(is_primary=False)
        super().save(*args, **kwargs)
        
        
class Transaction(TimeStampedModel): 
    class TransactionStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        
    class TransactionType(models.TextChoices):
        DEPOSIT = "deposit", _("Deposit")
        WITHDRAWAL = "withdrawal", _("Withdrawal")
        TRANSFER = "transfer", _("Transfer")
        
        
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="performed_transactions")
    amount = models.DecimalField(_("Amount"), max_digits=12, decimal_places=2, default=0.00) 
    description = models.CharField(_("Description"), max_length=500, null=True, blank=True)
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_transactions")
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_transactions")
    receiver_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_transactions")
    sender_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_transactions")
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.PENDING)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    
    def __str__(self) -> str:
        return f"{self.transaction_type} - {self.amount} - {self.status}"
    
    class Meta:
        verbose_name = _("Transaction")
        verbose_name_plural = _("Transactions")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at"])]


class SavingsInterest(TimeStampedModel):
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="interest_credits")
    date = models.DateField(_("Interest Date"))
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2)
    annual_rate = models.DecimalField(max_digits=7, decimal_places=6)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction = models.OneToOneField(
        Transaction, on_delete=models.PROTECT, null=True, blank=True,
        related_name="interest_credit",
    )

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["account", "date"], name="unique_daily_savings_interest"),
        ]


class SuspiciousActivityAlert(TimeStampedModel):
    transaction = models.OneToOneField(
        Transaction, on_delete=models.PROTECT, related_name="suspicious_activity_alert",
    )
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="activity_alerts")
    reason = models.TextField(_("Reason"))
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class IdempotencyRecord(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scope = models.CharField(max_length=80)
    key = models.CharField(max_length=128)
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    status_code = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "scope", "key"], name="unique_user_request_key")]


class StaffAuditLog(TimeStampedModel):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    object_id = models.UUIDField()
    details = models.JSONField(default=dict)
