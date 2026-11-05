# Scheduled account tasks

Celery discovers the tasks in `accounts/tasks.py`. Beat uses
`django_celery_beat.schedulers:DatabaseScheduler`; the schedules are defined in
`config/settings/base.py` and are available in the Django periodic-task admin.

Apply migrations with `python manage.py migrate`, then run the worker and Beat:

```sh
celery -A config.celery_app worker -l INFO
celery -A config.celery_app beat -l INFO
```

Run one Beat instance. The existing Docker Compose `celeryworker` and
`celerybeat` services also run these tasks.

## Savings interest

At 00:05 in the configured Celery timezone (currently UTC), active, fully verified
savings accounts with positive balances receive daily interest. The initial
annual rate is 3%; set `SAVINGS_ANNUAL_INTEREST_RATE=0.03` to configure the rate as
a fraction. `BankAccount.calculate_interest(days=1)` calculates without saving.

The calculation uses the balance at execution time, annual rate / 365, and
rounds to cents with half-up rounding. Interest compounds when credits are added
to the balance. This does not reconstruct historical balances or backfill missed
days. Review the initial rate against your product rules before enabling Beat.

Each account/date has a unique `SavingsInterest` record, including zero-rounded
credits. A positive credit also creates a completed deposit transaction. Balance,
transaction, and interest record are written together; reruns skip existing dates.

## Suspicious activity

Every 15 minutes, the task reviews completed outgoing transfers and withdrawals
in the previous hour. These configurable rules flag activity for user review;
they do not block transactions or freeze accounts.

| Environment variable | Initial value |
| --- | --- |
| `SUSPICIOUS_ACTIVITY_WINDOW_MINUTES` | `60` |
| `SUSPICIOUS_ACTIVITY_TRANSACTION_COUNT` | `5` |
| `SUSPICIOUS_ACTIVITY_USD_THRESHOLD` | `10000` |
| `SUSPICIOUS_ACTIVITY_GBP_THRESHOLD` | `10000` |
| `SUSPICIOUS_ACTIVITY_NGN_THRESHOLD` | `1000000` |

A transaction is flagged when its amount meets the currency threshold or its
source account reaches the transaction-count threshold within the window.
The account owner receives an email with a masked account number. Each
transaction has one alert record. Unsent alerts are retried on subsequent runs,
even after leaving the detection window. An interruption after email submission
but before recording success can result in a duplicate email.

Run the task tests with `python manage.py test core_apps.accounts.test_tasks`.
