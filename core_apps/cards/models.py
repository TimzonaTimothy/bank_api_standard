from django.db import models
from django.utils.translation import gettext_lazy as _

from core_apps.accounts.models import BankAccount
from core_apps.common.models import TimeStampedModel


class VirtualCard(TimeStampedModel):
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="virtual_cards",
    )
    # Internal identifier, not a payment-network card number.
    card_number = models.CharField(_("Card Number"), max_length=16, unique=True)
    expiry_date = models.DateField(_("Expiry Date"))
    balance = models.DecimalField(
        _("Balance"), max_digits=12, decimal_places=2, default=0,
    )
    is_active = models.BooleanField(_("Active"), default=True)

    @property
    def masked_card_number(self) -> str:
        return f"**** **** **** {self.card_number[-4:]}"

    def __str__(self) -> str:
        return f"{self.bank_account.user.full_name} - {self.masked_card_number}"

    class Meta:
        verbose_name = _("Virtual Card")
        verbose_name_plural = _("Virtual Cards")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(check=models.Q(balance__gte=0), name="card_balance_nonnegative"),
        ]
