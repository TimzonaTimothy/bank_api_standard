# Flow Bank API

A banking backend built with Django and Django REST Framework. The project contains customer onboarding, KYC verification, bank accounts, money movement, internal virtual cards, and background account monitoring.

## Features

| Area | Features implemented in the codebase |
| --- | --- |
| Authentication | Email registration and activation through Djoser, password reset, password-plus-email-OTP login, cookie-based JWT authentication, token refresh and logout |
| Authentication protection | Hashed OTP challenges, expiration and attempt limits, resend cooldowns, login lockouts, CSRF checks, request throttling, refresh-token rotation and blacklisting |
| Customer profiles | Personal, contact, identification and employment information; next-of-kin management; profile view tracking; asynchronous photo uploads to Cloudinary |
| Account onboarding | Automatic profile creation on registration; account creation when a profile is updated with complete information and next of kin; account-executive KYC verification and activation |
| Bank accounts | Current and savings accounts in US dollars, pounds sterling and naira; unique account numbers; one account per customer/type/currency combination |
| Money movement | Teller deposits, customer withdrawals, same-currency internal transfers, balance validation and configurable daily outgoing limits |
| Transaction authorization | Withdrawal and transfer OTP challenges bound to the stored transaction details; retry protection for completed confirmations |
| Virtual cards | Create, list and retrieve cards, activate/deactivate cards, and fund cards from an owned bank account; masked card numbers in API representations |
| Records and receipts | Paginated customer transaction history, PDF transaction receipts, and staff audit records for deposits and account verification |
| Savings interest | Scheduled daily interest credits for eligible savings accounts, with a unique record per account/date |
| Activity monitoring | Scheduled rules for high-value or frequent outgoing transactions, persisted alerts and email notifications |
| Administration and operations | Role-based staff permissions, Django admin, OpenAPI/Swagger/ReDoc, Flower task monitoring, rotating logs, and PostgreSQL backup/restore scripts |

Virtual cards use internal identifiers. The repository does not integrate a payment-network card issuer, external bank settlement, or foreign-exchange conversion.

## System design

The application is a **modular monolith**: domain-specific Django apps share one PostgreSQL database. API, background workers and the scheduler run as separate processes using the same application code.

```mermaid
flowchart LR
    Client[API client] --> Nginx[Nginx reverse proxy]
    Nginx --> API[Django REST API]
    Nginx --> Static[Static files]
    API --> DB[(PostgreSQL)]
    API --> Broker[RabbitMQ broker]
    Beat[Celery Beat] --> Broker
    Broker --> Worker[Celery worker]
    Worker --> DB
    Worker --> Redis[(Redis result backend)]
    Worker --> Mail[SMTP / local Mailpit]
    Worker --> Cloudinary[Cloudinary image storage]
    Flower[Flower monitoring] --> Broker
```

RabbitMQ and Redis roles above reflect the recommended local environment below; Celery reads its broker and result-backend URLs from environment variables. Production settings also use Redis for shared throttling. Local settings use Django's default cache.

### Design patterns and consistency

| Design | Use in this project |
| --- | --- |
| Layered request handling | URL routes dispatch to DRF views; serializers validate input; service/utility functions execute domain operations; Django models persist state |
| Domain modules | `user_auth`, `user_profile`, `accounts`, `cards` and shared `common` components separate responsibilities |
| Relational data model | Users own profiles and bank accounts; accounts link to transactions, virtual cards and daily interest records; challenges can link to completed transactions |
| Atomic database transactions | Balance changes and their transaction records commit together using `transaction.atomic()` |
| Pessimistic locking | `select_for_update()` serializes competing balance changes; transfers lock participating accounts in primary-key order |
| Database invariants | Constraints prevent negative bank/card balances and duplicate account/type/currency combinations, daily interest records and request keys |
| Idempotent commands | Deposits and card top-ups store a request fingerprint and successful response under an `Idempotency-Key`; matching retries return the saved response |
| Challenge-based authorization | OTP challenges store the purpose and transaction payload; confirmation executes those saved details and links the result for retries |
| Asynchronous work | Celery handles queued email delivery, image uploads and scheduled account tasks; RabbitMQ carries queued work |
| Scheduled processing | Celery Beat uses the database scheduler from `django-celery-beat`, allowing periodic-task administration through Django admin |
| Post-commit notifications | Financial operations use `transaction.on_commit()` to trigger notifications after successful database commits |
| Signals | Django user-save signals create and save customer profiles |
| Access control | Role permissions restrict teller, account-executive and branch-manager operations; customer queries are scoped to the authenticated owner |
| Reverse proxy | Nginx routes API/admin requests and serves collected static files |

Balances use decimal fields. Transactions record money movements, but the schema is not a double-entry accounting ledger. Post-commit callbacks are not a durable outbox; a process failure between committing and queuing a notification can lose that notification.

### Scheduled tasks

- **Daily savings interest:** runs at 00:05 UTC by default. Uses the balance at execution time, annual rate / 365, and half-up rounding to cents. The default annual rate is 3%. Existing account/date records prevent duplicate credits; missed days are not backfilled.
- **Suspicious activity:** runs every 15 minutes and checks the preceding hour by default. Rules flag transaction amounts or frequency and email the owner; they do not block transactions or freeze accounts.

See [scheduled account task documentation](core_apps/accounts/README.md) for configuration, retry behavior and calculation details.

## Technology stack

- Python 3.12, Django 4.2.15 and Django REST Framework 3.15.2.
- PostgreSQL 16, Django ORM and migrations.
- Djoser, Simple JWT and Argon2 password hashing.
- Celery 5.3.6, RabbitMQ, Redis 7, django-celery-beat, django-celery-email and Flower.
- Cloudinary for image storage, ReportLab for PDF generation, and drf-spectacular for OpenAPI documentation.
- Docker Compose, Nginx and Mailpit for local development; Loguru for application logging.

Docker installs dependencies from `requirements/local.txt` and `requirements/base.txt`. A Pipfile and lockfile are also present.

## Project layout

```text
config/                     Settings, root URLs, ASGI/WSGI and Celery configuration
core_apps/
  user_auth/                Custom users, authentication and OTP security
  user_profile/             Profiles, next of kin, signals and photo-upload tasks
  accounts/                 Accounts, transactions, authorization, interest and alerts
  cards/                    Internal virtual cards and top-ups
  common/                   Shared models, permissions, renderers and cookie auth
  templates/                Email templates
docker/local/               Development images, startup scripts and DB maintenance
docker/production/          Production TLS Nginx configuration
requirements/               Base, local and production dependency lists
.envs/.env.example          Environment-variable template
local.yml                   Local Compose services, network and volumes
Makefile                    Development and database-maintenance commands
SECURITY.md                 Authentication and production configuration details
```

## Local setup

Requires Docker with Compose v2; Make is optional. Python 3.12 is needed if running management commands outside Docker.

1. Create `.envs/.env.local` from `.envs/.env.example` **if a local file does not already exist**. Fill in the template values and add the Celery/Flower variables below. The template contains blank placeholders and omits those variables.

   ```dotenv
   DEBUG=True
   SITE_NAME=Flow Bank
   SECRET_KEY=replace-with-a-random-development-secret
   SIGNING_KEY=replace-with-a-separate-random-signing-secret
   ADMIN_URL=supersecret/
   DOMAIN=localhost:8080
   BANK_NAME=Flow Bank

   POSTGRES_HOST=postgres
   POSTGRES_PORT=5432
   POSTGRES_DB=banker
   POSTGRES_USER=alpha
   POSTGRES_PASSWORD=replace-with-a-local-database-password

   EMAIL_HOST=mailpit
   EMAIL_PORT=1025
   DEFAULT_FROM_EMAIL=bank@example.test

   CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
   CELERY_RESULT_BACKEND=redis://redis:6379/0
   CELERY_FLOWER_USER=admin
   CELERY_FLOWER_PASSWORD=replace-with-a-local-monitoring-password
   COOKIE_SECURE=False
   ```

   Set the three `CLOUDINARY_*` variables from the template to use image uploads. `COOKIE_SECURE=False` supports local HTTP; production settings force secure cookies. `ADMIN_URL=supersecret/` matches the local Nginx admin route.

2. Create the external network required by `local.yml`, once:

   ```sh
   docker network create banker_local_nw
   ```

3. Build and start the services:

   ```sh
   make build
   docker compose -f local.yml logs -f api
   ```

   The API startup script runs migrations, collects static files and launches Django's development server. Equivalent startup without Make: `docker compose -f local.yml up --build -d --remove-orphans`.

4. Create an administrator:

   ```sh
   make superuser
   ```

| Service | Local address |
| --- | --- |
| API base | http://localhost:8080/api/v1/ |
| Swagger UI | http://localhost:8080/api/v1/schema/swagger-ui/ |
| ReDoc | http://localhost:8080/api/v1/schema/redoc/ |
| OpenAPI schema | http://localhost:8080/api/v1/schema/ |
| Admin, with the configuration above | http://localhost:8080/supersecret/ |
| Mailpit inbox | http://localhost:8025 |
| Flower | http://localhost:5555 |
| RabbitMQ management | http://localhost:15672 |

The API container's port 8000 is internal; access it through Nginx on port 8080.

## API guide

All routes below are relative to `/api/v1/`. Consult the generated schema for request fields and response formats.

| Routes | Purpose |
| --- | --- |
| `auth/users/` | Djoser user registration and user endpoints |
| `auth/csrf/`, `auth/login/`, `auth/verify-otp/` | CSRF initialization and two-step login |
| `auth/refresh/`, `auth/logout/` | Refresh or revoke authentication |
| `profiles/my-profile/` | Retrieve/update the current customer's profile |
| `profiles/my-profile/next-of-kin/` | List/create next-of-kin records; use `/<uuid>/` for record operations |
| `profiles/all/` | Branch-manager customer profile listing and search |
| `accounts/verify/<uuid>/` | Account-executive verification |
| `accounts/deposit/` | Teller account lookup and deposit |
| `accounts/initiate-transfer/`, `accounts/verify-otp/` | Initiate and confirm a transfer |
| `accounts/initiate-withdrawal/`, `accounts/verify-username-and-wthdraw/` | Initiate and confirm a withdrawal using an OTP challenge; the confirmation URL retains its legacy spelling |
| `accounts/transactions/`, `accounts/transactions/<uuid>/pdf/` | Transaction history and PDF receipt |
| `cards/`, `cards/<uuid>/` | Create/list cards and retrieve a card |
| `cards/<uuid>/status/`, `cards/<uuid>/top-up/` | Update card activation and fund a card |

For browser authentication, get `auth/csrf/`, retain cookies and send `X-CSRFToken` on unsafe requests. Post email/password to `auth/login/`, then submit the returned `challenge_id` with the emailed `otp` to `auth/verify-otp/`. Retain the authentication cookies on subsequent requests.

Deposits and card top-ups require an `Idempotency-Key` header. Reuse it only for the same request and resource. Transfer/withdrawal confirmations require their challenge ID and OTP. Security-question authorization is retired; its legacy endpoint returns HTTP 410. See [SECURITY.md](SECURITY.md) for the full authentication contract and transaction rules.

## Development and verification

```sh
make up                 # Start existing containers
make down               # Stop containers
make migrate            # Apply migrations
make makemigrations     # Generate migrations after model changes
make collectstatic      # Collect static assets

# Run the Django suite against the container's PostgreSQL configuration
docker compose -f local.yml run --rm api python manage.py test

# Run account scheduling tests separately
docker compose -f local.yml run --rm api python manage.py test core_apps.accounts.test_tasks
```

Tests cover authentication, transaction security, concurrent money movement, scheduled account tasks and cards. Use PostgreSQL for concurrency tests to exercise database row locking.

### Current implementation limitations

Profile code needs repairs before relying on the full onboarding/upload flow: `ProfileSerializer` has adjacent `view_count`/`account_currency` strings without a separating comma, a misspelled `neext_of_kin` relation, and an incompatible `update` signature. The file-upload task also expects a `data` key for file payloads while the serializer supplies `path`. These are existing issues; feature descriptions above identify code present in the repository, not a guarantee that every flow currently passes end-to-end checks.

## Backups and deployment

Use `make backup` and `make backups` for PostgreSQL custom-format archives. Follow the [backup and restore guide](docker/local/postgres/README.md) before restoring data. `make down-v` removes named volumes, including the local database and backup volume.

Local Compose runs Django's development server over HTTP. Production configuration is provided separately in `config/settings/production.py` and `docker/production/nginx.conf`; deployment requires HTTPS ingress, certificates, explicit hosts/origins, secrets and shared Redis configuration. Follow [SECURITY.md](SECURITY.md) for the required settings and operational guidance. Run one Celery Beat instance to avoid duplicate scheduling.
