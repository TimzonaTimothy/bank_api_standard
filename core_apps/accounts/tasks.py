from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from loguru import logger

from .emails import send_suspicious_activity_email
from .models import BankAccount, Transaction, SuspiciousActivityAlert
from .utils import credit_daily_savings_interest


@shared_task
def daily_savings_interest():
    interest_date = timezone.localdate()
    account_ids = BankAccount.objects.filter(
        account_type=BankAccount.AccountType.SAVINGS,
        account_status=BankAccount.AccountStatus.ACTIVE,
        kyc_verified=True, fully_activated=True, account_balance__gt=0,
    ).values_list("pk", flat=True)
    credited = 0
    for account_id in account_ids.iterator():
        record = credit_daily_savings_interest(account_id, interest_date)
        if record is not None:
            credited += 1
    logger.info(f"Daily savings interest processed for {credited} accounts on {interest_date}")
    return credited


@shared_task
def detect_suspicious_activity():
    now = timezone.now()
    recent = Transaction.objects.filter(
        created_at__gte=now - timedelta(minutes=settings.SUSPICIOUS_ACTIVITY_WINDOW_MINUTES),
        created_at__lte=now, status=Transaction.TransactionStatus.COMPLETED,
        transaction_type__in=[Transaction.TransactionType.WITHDRAWAL, Transaction.TransactionType.TRANSFER],
        sender_account__isnull=False,
    )
    frequent_accounts = set(
        recent.order_by().values("sender_account_id").annotate(total=Count("id"))
        .filter(total__gte=settings.SUSPICIOUS_ACTIVITY_TRANSACTION_COUNT)
        .values_list("sender_account_id", flat=True)
    )
    detected = 0
    for item in recent.select_related("sender_account").iterator():
        account = item.sender_account
        reasons = []
        threshold = settings.SUSPICIOUS_ACTIVITY_AMOUNT_THRESHOLDS.get(account.currency)
        if threshold is not None and item.amount >= Decimal(str(threshold)):
            reasons.append("Unusually large outgoing transaction")
        if account.pk in frequent_accounts:
            reasons.append("Multiple outgoing transactions within a short period")
        if reasons:
            _, created = SuspiciousActivityAlert.objects.get_or_create(
                transaction=item, defaults={"account": account, "reason": "; ".join(reasons)},
            )
            detected += int(created)

    # Include older unsent alerts, so temporary email failures are retried.
    pending_ids = SuspiciousActivityAlert.objects.filter(notified_at__isnull=True).values_list("pk", flat=True)
    for alert_id in pending_ids.iterator():
        try:
            with transaction.atomic():
                alert = SuspiciousActivityAlert.objects.select_for_update().get(pk=alert_id)
                if alert.notified_at is not None:
                    continue
                send_suspicious_activity_email(alert)
                alert.notified_at = timezone.now()
                alert.save(update_fields=["notified_at", "updated_at"])
        except Exception as e:
            logger.error(f"Failed to send suspicious activity alert {alert_id}: {e}")
    return detected
