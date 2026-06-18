# Hanilies Cakeshoppe

Hanilies Cakeshoppe is a Django web application for cake ordering and event package booking. It includes customer ordering flows, payment submission, order tracking, profile summaries, notification delivery, and a custom admin panel for managing products, orders, payments, users, and activity logs.

The project is designed to run locally with SQLite and can be deployed on Render.

## Features

### Customer features

- Browse cakes and event packages
- Search and filter catalog pages
- Place customized cake orders
- Book event packages through a multi-step flow
- Review orders before final confirmation
- Submit either a 50% GCash deposit with COD balance or a full GCash payment
- Preview GCash checkout QR details before submitting payment proof
- Track live cake and package orders
- Request order cancellation and follow refund processing from tracking
- Edit profile details, change password, and manage account preferences
- View profile stats and recent notifications
- Receive in-app notifications and optional email updates

### Admin features

- Custom admin dashboard with sales summaries
- Cake and package management
- Cake and package order status management
- Payment verification workflow
- Refund and cancellation request handling
- User management, direct staff account creation, and role updates
- Activity log for staff actions

### Current implementation highlights

- Homepage recommendations are rule-based and use prior customer orders with best-seller fallback
- Cake orders create real `CakeOrder`, `CakeCustomization`, and `Payment` records
- Package bookings use a session-backed draft flow before final payment submission
- Cake and package checkout flows support deposit/full-payment plans and create the related payment records automatically
- Tracking pages expose cancellation quotes, request submission, refund status, and order-linked notifications
- Package catalog entries can render a primary image plus up to 4 ordered thumbnails
- Role handling includes `customer`, `supervisor`, and staff-only admin access paths
- Notifications are stored in the database and can also trigger plain-text email delivery
- The app includes focused automated tests for ordering, tracking, payments, notifications, admin security, and dashboard metrics

## Recent updates

- Profile page now supports editing first name, last name, email, phone number, and address, alongside password and notification-preference management
- Customer tracking now supports cancellation requests with refund estimates and an admin refund-processing workflow
- Checkout flows now include a review-before-confirm step and a GCash QR preview for payment submission
- Admin user management now supports direct staff account creation and the `supervisor` role
- Package media now supports up to four ordered thumbnails in addition to the main package image
- The canonical package-ordering route is `/order-package/`, while `/package-order/` remains as a compatibility alias

## Tech stack

- Python
- Django
- SQLite for local development
- Django templates
- Bootstrap 5
- JavaScript
- Pillow for image handling
- WhiteNoise for static file serving in deployment

## Requirements

- Python 3.13+
- `pip`
- Git

Notes:

- The repository standardizes on a local `venv/` virtual environment
- `runtime.txt` and Render config currently target Python `3.13.1`
- Local development uses SQLite by default and does not require PostgreSQL

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/whiteheadbella/hanilies-cakeshoppe.git
cd hanilies-cakeshoppe
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply migrations

```bash
python manage.py migrate
```

### 5. Create an admin account

```bash
python manage.py createsuperuser
```

### 6. Run the development server

```bash
python manage.py runserver
```

Open the app at:

```text
http://127.0.0.1:8000/
```

## Environment variables

The app loads a root `.env` file through `python-dotenv`. Only `SECRET_KEY` is required in production. Most settings have safe development defaults.

Example `.env`:

```env
DEBUG=True
SECRET_KEY=replace-this-in-production
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000

SQLITE_PATH=db.sqlite3
MEDIA_ROOT=media

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=Hanilies Cakeshoppe <your-email@example.com>
HANILIES_PAYMENT_PROOF_OCR_ENABLED=True

HANILIES_GCASH_ACCOUNT_NAME=Hanilies Cakeshoppe
HANILIES_GCASH_ACCOUNT_NUMBER=
HANILIES_GCASH_PAYMENT_NOTE=Send payment using the account details shown on the checkout page.
DEMO_BOT_REMOTE_ENABLED=False
```

## Email behavior

- In development, email defaults to Django's console backend when no email backend is configured
- In production, email defaults to SMTP unless explicitly overridden
- Order and payment status updates can create both database notifications and email messages
- Gmail SMTP should use an app password instead of the regular account password
- Payment proof OCR can be disabled with `HANILIES_PAYMENT_PROOF_OCR_ENABLED=False` to fall back to manual admin review for uploaded receipts

## Useful commands

Run a Django system check:

```bash
python manage.py check
```

Run the app test suite:

```bash
python manage.py test hanilies.tests -v 2
```

View demo bot help:

```bash
python manage.py demo_bot --help
```

Collect static files for deployment:

```bash
python manage.py collectstatic --no-input
```

## Demo bot

The project includes a Selenium-backed demo command for presentation flows.

Start the app in one terminal:

```bash
python manage.py runserver
```

Then run the demo bot in another terminal:

```bash
python manage.py demo_bot full
```

## Deployment

The repository includes `render.yaml` for Render deployment.

Current Render flow:

- Build command: `pip install -r requirements.txt && python manage.py collectstatic --no-input`
- Start command: `python manage.py migrate && python manage.py sync_repo_media && python manage.py loaddata catalog_seed && gunicorn config.wsgi:application`
- Persistent disk is used for SQLite and uploaded media

Because Render runs `python manage.py migrate` during service startup, newly added data/schema migrations are applied automatically on the deployed environment as part of the next deploy or restart. That includes the corporate package cleanup migration `hanilies.0004_remove_corporate_package_records`.

Render environment variables currently include:

- `PYTHON_VERSION`
- `DEBUG`
- `DEMO_BOT_REMOTE_ENABLED`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SQLITE_PATH`
- `MEDIA_ROOT`
- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USE_TLS`
- `EMAIL_USE_SSL`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

## Project structure

```text
hanilies-cakeshoppe/
|-- config/                 Django project settings and entry points
|-- hanilies/               App models, views, URLs, tests, and management commands
|-- templates/              Custom admin and shared templates
|-- static/                 Source static assets
|-- media/                  Uploaded files during local use
|-- manage.py               Django management entry point
|-- requirements.txt        Python dependencies
|-- render.yaml             Render deployment configuration
`-- runtime.txt             Python runtime target
```

## Core routes

- `/` home page
- `/cakes/` cake catalog
- `/packages/` package catalog
- `/cake-customize/` cake ordering flow
- `/order-package/` package ordering flow
- `/package-payment/` package payment step
- `/order-tracking/` customer order tracking
- `/profile/` customer profile
- `/admin-panel/` custom admin panel

## Validation status

The following project commands have been verified in this workspace:

- `python manage.py check`
- `python manage.py makemigrations --check`
- `python manage.py test hanilies.tests -v 2`

## Repository notes

- Static fallback cake images use `/static/images/bg.png`
- The canonical package-order route is `/order-package/`, with `/package-order/` kept as a compatibility alias
- Customer notifications are backed by the `Notification` model and can also send email through Django mail settings
