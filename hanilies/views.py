import json
import os
import signal
import subprocess
import sys

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.urls import reverse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import UserProfile, Notification, Cake, CakeOrder, CakeCustomization, Package, PackageOrder, PackageThumbnail, Payment, RefundRequest, ActivityLog
from .payment_qr import build_gcash_checkout_details, get_gcash_profile


PACKAGE_ORDER_SESSION_KEY = 'package_order_draft'
DEMO_SCENARIOS = {'login', 'cake', 'package', 'full', 'custom'}
DEMO_SCRIPT_STEPS = [
    ('home', 'Homepage Welcome'),
    ('login', 'Customer Login'),
    ('ai_recommendations', 'AI Recommendation View'),
    ('cakes', 'Cakes Catalog'),
    ('cake_order', 'Cake Customization and Order'),
    ('cake_tracking', 'Cake Order Tracking'),
    ('packages', 'Packages Catalog'),
    ('package_order', 'Package Order and Payment'),
    ('package_tracking', 'Package Order Tracking'),
    ('profile', 'Customer Profile'),
    ('order_tracking', 'Tracking Dashboard'),
    ('about', 'About Page'),
    ('contact', 'Contact Page'),
]
DEMO_SESSION_STATE_KEY = 'active_demo_bot'
DEMO_BROWSER_USERNAME = os.environ.get('DEMO_BOT_USERNAME', 'paneldemo')
DEMO_BROWSER_PASSWORD = os.environ.get('DEMO_BOT_PASSWORD', 'PanelDemo123!')
DEMO_BROWSER_EMAIL = os.environ.get('DEMO_BOT_EMAIL', 'paneldemo@example.com')
DEMO_BROWSER_SCENARIO_STEPS = {
    'login': ['home', 'login', 'profile'],
    'cake': ['home', 'login', 'ai_recommendations', 'cakes', 'cake_order', 'cake_tracking'],
    'package': ['home', 'login', 'packages', 'package_order', 'package_tracking'],
    'full': ['home', 'login', 'ai_recommendations', 'cakes', 'cake_order', 'cake_tracking', 'packages', 'package_order', 'package_tracking', 'profile', 'order_tracking'],
}

CAKE_DECORATION_OPTIONS = {
    'fresh_flowers': {'label': 'Fresh Flowers', 'price': Decimal('300.00')},
    'edible_gold': {'label': 'Edible Gold Leaf', 'price': Decimal('500.00')},
    'cake_topper': {'label': 'Custom Cake Topper', 'price': Decimal('250.00')},
    'sprinkles': {'label': 'Edible Sprinkles', 'price': Decimal('100.00')},
    'fresh_fruits': {'label': 'Fresh Fruit Toppings', 'price': Decimal('200.00')},
}

CAKE_THEME_OPTIONS = [
    'Birthday',
    'Christening',
    'Wedding',
    'Anniversary',
    'Special Occasions',
]

CAKE_CATEGORY_VALUES = {value for value, _ in Cake.CAKE_CATEGORIES}
MAX_PACKAGE_THUMBNAILS = 4

PUBLIC_PACKAGE_TYPES = [
    choice for choice in Package.PACKAGE_TYPES if choice[0] != 'corporate'
]
PUBLIC_PACKAGE_TYPE_VALUES = {value for value, _ in PUBLIC_PACKAGE_TYPES}
PUBLIC_EVENT_TYPES = [
    choice for choice in PackageOrder.EVENT_TYPES if choice[0] != 'corporate'
]
PUBLIC_EVENT_TYPE_VALUES = {value for value, _ in PUBLIC_EVENT_TYPES}

PACKAGE_ADDON_OPTIONS = {
    'brownies': {'label': 'Chocofudge Brownies', 'price': Decimal('300.00')},
    'cupcakes': {'label': 'Themed Cupcakes', 'price': Decimal('350.00')},
    'cookies': {'label': 'Chocochip Cookies', 'price': Decimal('250.00')},
    'marshmallow': {'label': 'Marshmallow on Stick', 'price': Decimal('200.00')},
    'cake_pop': {'label': 'Cake Pop', 'price': Decimal('250.00')},
    'gummies': {'label': 'Assorted Gummies', 'price': Decimal('150.00')},
    'wafer': {'label': 'Wafer Sticks', 'price': Decimal('180.00')},
    'chocolate_fountain': {'label': 'Chocolate Fountain', 'price': Decimal('1500.00')},
    'lolli_balloon': {'label': 'Lolli Balloon with Print', 'price': Decimal('50.00')},
    'pillar_balloon': {'label': 'Pillar Balloon', 'price': Decimal('100.00')},
    'centerpiece': {'label': 'Centerpiece Balloon', 'price': Decimal('150.00')},
}

PACKAGE_CAKE_UPGRADES = {
    'standard': {'label': 'Standard package cake size', 'price': Decimal('0.00')},
    'upgrade_10': {'label': 'Upgrade to 10 inches', 'price': Decimal('500.00')},
    'upgrade_12': {'label': 'Upgrade to 12 inches', 'price': Decimal('900.00')},
    'extra_layer': {'label': 'Add extra layer', 'price': Decimal('1500.00')},
}

PACKAGE_CAKE_DECORATIONS = {
    'edible_gold': {'label': 'Edible Gold Leaf', 'price': Decimal('500.00')},
    'fresh_flowers': {'label': 'Fresh Flowers', 'price': Decimal('300.00')},
    'custom_topper': {'label': 'Custom Cake Topper', 'price': Decimal('250.00')},
    'edible_image': {'label': 'Edible Image Print', 'price': Decimal('200.00')},
    'sprinkles': {'label': 'Edible Sprinkles', 'price': Decimal('100.00')},
    'fresh_fruits': {'label': 'Fresh Fruit Toppings', 'price': Decimal('200.00')},
}

ORDER_STATUS_NOTIFICATION_CONFIG = {
    'cake': {
        'confirmed': {
            'headline': 'Your cake order has been confirmed.',
            'subject': 'Cake order confirmed',
        },
        'preparing': {
            'headline': 'Your cake is now being prepared.',
            'subject': 'Cake order now preparing',
        },
        'out_for_delivery': {
            'headline': 'Your cake order is out for delivery.',
            'subject': 'Cake order out for delivery',
        },
        'delivered': {
            'headline': 'Your cake order has been marked as delivered.',
            'subject': 'Cake order delivered',
        },
    },
    'package': {
        'confirmed': {
            'headline': 'Your package booking has been confirmed.',
            'subject': 'Package booking confirmed',
        },
        'preparing': {
            'headline': 'Your package booking is now being prepared.',
            'subject': 'Package booking now preparing',
        },
        'ready_for_pickup': {
            'headline': 'Your package booking is ready for pickup.',
            'subject': 'Package booking ready for pickup',
        },
        'completed': {
            'headline': 'Your package booking has been completed.',
            'subject': 'Package booking completed',
        },
    },
}

PAYMENT_STATUS_NOTIFICATION_CONFIG = {
    'verifying': {
        'headline': 'Your payment proof is now under verification.',
        'subject': 'Payment under verification',
    },
    'paid': {
        'headline': 'Your payment has been approved and recorded successfully.',
        'subject': 'Payment approved',
    },
    'failed': {
        'headline': 'Your payment could not be verified. Please review your payment details or contact Hanilies Cakeshoppe.',
        'subject': 'Payment verification update',
    },
}

REFUND_STATUS_NOTIFICATION_CONFIG = {
    'requested': {
        'title': 'Cancellation request received',
        'message': 'Your cancellation request has been received and is now waiting for admin review.',
    },
    'approved': {
        'title': 'Cancellation approved',
        'message': 'Your order cancellation was approved. The refundable amount will be processed by the cashier.',
    },
    'rejected': {
        'title': 'Cancellation request rejected',
        'message': 'Your cancellation request was rejected. Please contact Hanilies Cakeshoppe for more details.',
    },
    'processed': {
        'title': 'Refund processed',
        'message': 'Your refund has been marked as processed. Please review the reference number in your tracking page.',
    },
}

DEPOSIT_RATE = Decimal('0.50')
STAFF_ROLE_VALUES = {'owner', 'admin', 'manager', 'supervisor', 'baker', 'packager', 'cashier'}
PAYMENT_PLAN_LABELS = {
    'cod': '50% GCash Deposit + COD Balance',
    'gcash': 'Full GCash Payment',
}
ADMIN_MENU_ITEMS = [
    {'name': 'Dashboard', 'url': 'admin_dashboard', 'icon': 'tachometer-alt', 'roles': STAFF_ROLE_VALUES},
    {'name': 'Cakes', 'url': 'admin_cakes', 'icon': 'birthday-cake', 'roles': {'owner', 'admin', 'supervisor', 'baker'}},
    {'name': 'Cake Orders', 'url': 'admin_cake_orders', 'icon': 'shopping-cart', 'roles': {'owner', 'admin', 'manager', 'supervisor', 'baker'}},
    {'name': 'Packages', 'url': 'admin_packages', 'icon': 'gift', 'roles': {'owner', 'admin', 'supervisor', 'packager'}},
    {'name': 'Package Orders', 'url': 'admin_package_orders', 'icon': 'calendar-check', 'roles': {'owner', 'admin', 'manager', 'supervisor', 'packager'}},
    {'name': 'Payments', 'url': 'admin_payments', 'icon': 'credit-card', 'roles': {'owner', 'admin', 'cashier'}},
    {'name': 'Refunds', 'url': 'admin_refunds', 'icon': 'rotate-left', 'roles': {'owner', 'admin', 'manager', 'supervisor', 'cashier'}},
    {'name': 'Users', 'url': 'admin_users', 'icon': 'users', 'roles': {'owner', 'admin'}},
    {'name': 'Audit Trail', 'url': 'admin_activity_logs', 'icon': 'clipboard-list', 'roles': {'owner', 'admin'}},
]

ROLE_CHOICES = UserProfile.ROLE_CHOICES


def _parse_decimal(value, default='0.00'):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _quantize_amount(value):
    return _parse_decimal(value).quantize(Decimal('0.01'))


def _get_user_role_value(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser:
        return 'owner'
    if hasattr(user, 'profile'):
        return user.profile.role
    return None


def _user_has_any_role(user, allowed_roles):
    role_value = _get_user_role_value(user)
    return role_value in allowed_roles


def _require_admin_roles(request, allowed_roles, redirect_name='admin_dashboard'):
    if _user_has_any_role(request.user, allowed_roles):
        return None
    messages.error(request, 'Permission denied')
    return redirect(redirect_name)


def _sync_user_staff_flags(user, role_value):
    is_staff_user = user.is_superuser or role_value in STAFF_ROLE_VALUES
    if user.is_staff != is_staff_user:
        user.is_staff = is_staff_user
        user.save(update_fields=['is_staff'])


def _ensure_user_profile(user, default_role='customer'):
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'role': default_role},
    )
    if created:
        _sync_user_staff_flags(user, profile.role)
    return profile


def _assign_user_role(user, role_value, phone=None, address=None):
    profile = _ensure_user_profile(user, default_role=role_value)
    profile.role = role_value
    if phone is not None:
        profile.phone = phone
    if address is not None:
        profile.address = address
    profile.save()
    _sync_user_staff_flags(user, role_value)
    return profile


def _get_payment_plan_label(payment_plan):
    return PAYMENT_PLAN_LABELS.get(payment_plan, PAYMENT_PLAN_LABELS['cod'])


def _calculate_deposit_breakdown(total_amount):
    total_amount = _quantize_amount(total_amount)
    deposit_amount = _quantize_amount(total_amount * DEPOSIT_RATE)
    balance_due = _quantize_amount(total_amount - deposit_amount)
    return deposit_amount, balance_due


def _get_order_kind(order):
    return 'cake' if isinstance(order, CakeOrder) else 'package'


def _get_order_label(order):
    order_kind = _get_order_kind(order)
    return 'Cake Order' if order_kind == 'cake' else 'Package Order'


def _get_order_payments_queryset(order):
    return order.payments.order_by('created_at', 'id')


def _get_order_primary_payment(order):
    return _get_order_payments_queryset(order).filter(
        payment_purpose__in=['deposit', 'full'],
    ).order_by('-created_at', '-id').first()


def _get_order_schedule_datetime(order_type, order):
    if order_type == 'cake':
        return order.delivery_date

    event_time = order.event_time or datetime.min.time().replace(hour=10, minute=0)
    event_datetime = datetime.combine(order.event_date, event_time)
    if timezone.is_naive(event_datetime):
        return timezone.make_aware(event_datetime)
    return event_datetime


def _get_paid_or_pending_gcash_total(order):
    total_amount = Decimal('0.00')
    for payment in _get_order_payments_queryset(order).filter(
        payment_method='gcash',
        payment_purpose__in=['deposit', 'full'],
        payment_status__in=['paid', 'verifying'],
    ):
        total_amount += payment.amount
    return _quantize_amount(total_amount)


def _build_cancellation_quote(order_type, order):
    if order.order_status == 'cancelled':
        return {
            'allowed': False,
            'reason': 'This order is already cancelled.',
            'penalty_rate': Decimal('0.00'),
            'penalty_fee': Decimal('0.00'),
            'refundable_amount': Decimal('0.00'),
        }

    schedule_datetime = _get_order_schedule_datetime(order_type, order)
    now = timezone.now()
    hours_until = None
    if schedule_datetime is not None:
        hours_until = (schedule_datetime - now).total_seconds() / 3600

    refundable_base = _get_paid_or_pending_gcash_total(order)
    if refundable_base <= Decimal('0.00'):
        return {
            'allowed': False,
            'reason': 'There is no verified or pending GCash payment available for refund.',
            'penalty_rate': Decimal('0.00'),
            'penalty_fee': Decimal('0.00'),
            'refundable_amount': Decimal('0.00'),
        }

    if order_type == 'cake':
        if order.order_status in ['out_for_delivery', 'delivered']:
            return {
                'allowed': False,
                'reason': 'Cake orders can no longer be cancelled once they are out for delivery or delivered.',
                'penalty_rate': Decimal('1.00'),
                'penalty_fee': refundable_base,
                'refundable_amount': Decimal('0.00'),
            }
        if order.order_status == 'preparing' or (hours_until is not None and hours_until < 24):
            penalty_rate = Decimal('0.50')
            policy_note = '50% of the paid GCash amount is charged because production has started or the delivery date is less than 24 hours away.'
        elif hours_until is not None and hours_until < 48:
            penalty_rate = Decimal('0.20')
            policy_note = '20% of the paid GCash amount is charged because the delivery date is within 48 hours.'
        else:
            penalty_rate = Decimal('0.00')
            policy_note = 'No cancellation fee applies because the request was submitted at least 48 hours before delivery.'
    else:
        if order.order_status in ['ready_for_pickup', 'completed']:
            return {
                'allowed': False,
                'reason': 'Package orders can no longer be cancelled once they are ready for pickup or completed.',
                'penalty_rate': Decimal('1.00'),
                'penalty_fee': refundable_base,
                'refundable_amount': Decimal('0.00'),
            }
        if order.order_status == 'preparing' or (hours_until is not None and hours_until < 72):
            penalty_rate = Decimal('0.50')
            policy_note = '50% of the paid GCash amount is charged because event preparation has started or the booking is less than 72 hours away.'
        elif hours_until is not None and hours_until < (7 * 24):
            penalty_rate = Decimal('0.25')
            policy_note = '25% of the paid GCash amount is charged because the booking is within 7 days.'
        else:
            penalty_rate = Decimal('0.10')
            policy_note = '10% of the paid GCash amount is charged for early package cancellations.'

    penalty_fee = _quantize_amount(refundable_base * penalty_rate)
    refundable_amount = _quantize_amount(max(refundable_base - penalty_fee, Decimal('0.00')))
    return {
        'allowed': True,
        'reason': policy_note,
        'penalty_rate': penalty_rate,
        'penalty_fee': penalty_fee,
        'refundable_amount': refundable_amount,
        'refundable_base': refundable_base,
    }


def _create_refund_status_notification(refund_request):
    order = refund_request.cake_order or refund_request.package_order
    if order is None:
        return None

    notification = REFUND_STATUS_NOTIFICATION_CONFIG.get(refund_request.status)
    if not notification:
        return None

    return _create_customer_notification(
        order.user,
        'refund_status',
        notification['title'],
        (
            f'{notification["message"]} '
            f'Penalty fee: P{refund_request.penalty_fee}. '
            f'Refundable amount: P{refund_request.refundable_amount}.'
        ),
        status_value=refund_request.status,
        cake_order=refund_request.cake_order,
        package_order=refund_request.package_order,
        payment=refund_request.payment,
    )


def _create_order_payment(order, amount, payment_method, payment_purpose, payment_status='pending', reference_number='', proof_image=None, notes=''):
    payment_kwargs = {
        'amount': _quantize_amount(amount),
        'payment_method': payment_method,
        'payment_purpose': payment_purpose,
        'payment_status': payment_status,
        'reference_number': reference_number,
        'proof_image': proof_image,
        'notes': notes,
    }
    if isinstance(order, CakeOrder):
        payment_kwargs['cake_order'] = order
    else:
        payment_kwargs['package_order'] = order
    return Payment.objects.create(**payment_kwargs)


def _cancel_outstanding_balance_payments(order):
    _get_order_payments_queryset(order).filter(
        payment_purpose='balance',
        payment_status='pending',
    ).update(payment_status='cancelled')


def _sync_order_confirmation_from_payment(payment, actor=None):
    if payment.payment_status != 'paid' or payment.payment_purpose not in ['deposit', 'full']:
        return

    if payment.cake_order_id:
        order = payment.cake_order
        order_type = 'cake'
    elif payment.package_order_id:
        order = payment.package_order
        order_type = 'package'
    else:
        return

    if order.order_status != 'pending':
        return

    previous_status = order.order_status
    order.order_status = 'confirmed'
    order.save(update_fields=['order_status', 'updated_at'])
    _create_order_status_notification(order, order_type, previous_status)

    if actor is not None:
        _log_staff_activity(
            actor,
            'order_confirmed_from_payment',
            f'Confirmed {_get_order_label(order)} #{order.id} after approving {payment.payment_purpose} payment #{payment.id}.',
            f'{order_type}_order',
            order.id,
        )


def _create_checkout_payments(order, selected_plan, reference_number, proof_image):
    if selected_plan == 'gcash':
        return [
            _create_order_payment(
                order,
                order.total_price,
                'gcash',
                'full',
                payment_status='verifying',
                reference_number=reference_number,
                proof_image=proof_image,
                notes='Full GCash payment submitted during checkout.',
            )
        ]

    deposit_amount, balance_due = _calculate_deposit_breakdown(order.total_price)
    order.deposit_amount = deposit_amount
    order.balance_due = balance_due
    order.save(update_fields=['deposit_amount', 'balance_due', 'updated_at'])
    return [
        _create_order_payment(
            order,
            deposit_amount,
            'gcash',
            'deposit',
            payment_status='verifying',
            reference_number=reference_number,
            proof_image=proof_image,
            notes='50% GCash deposit submitted during checkout.',
        ),
        _create_order_payment(
            order,
            balance_due,
            'cod',
            'balance',
            payment_status='pending',
            notes='Remaining balance due on pickup or delivery.',
        ),
    ]


def _get_public_package_queryset():
    return Package.objects.filter(
        status='active', package_type__in=PUBLIC_PACKAGE_TYPE_VALUES)


def _parse_delivery_datetime(date_value):
    if not date_value:
        return None
    try:
        delivery_datetime = datetime.strptime(
            date_value, '%Y-%m-%d').replace(hour=10, minute=0)
    except ValueError:
        return None
    if timezone.is_naive(delivery_datetime):
        return timezone.make_aware(delivery_datetime)
    return delivery_datetime


def _get_profile_defaults(user):
    profile = getattr(user, 'profile', None)
    full_name = f'{user.first_name} {user.last_name}'.strip() or user.username
    return {
        'contact_name': full_name,
        'contact_phone': profile.phone if profile else '',
        'contact_email': user.email,
        'delivery_address': profile.address if profile else '',
    }


def _get_selected_option_labels(selected_keys, options):
    labels = []
    total = Decimal('0.00')
    for key in selected_keys:
        option = options.get(key)
        if not option:
            continue
        labels.append(option['label'])
        total += option['price']
    return labels, total


def _build_package_thumbnail_slots(package=None):
    existing = {}
    if package is not None:
        existing = {
            thumbnail.sort_order: thumbnail
            for thumbnail in package.thumbnails.order_by('sort_order')
        }

    return [
        {'order': slot_order, 'thumbnail': existing.get(slot_order)}
        for slot_order in range(1, MAX_PACKAGE_THUMBNAILS + 1)
    ]


def _sync_package_thumbnails(package, files, removals=None):
    removals = removals or set()
    existing = {
        thumbnail.sort_order: thumbnail
        for thumbnail in package.thumbnails.all()
    }

    for slot_order in range(1, MAX_PACKAGE_THUMBNAILS + 1):
        thumbnail = existing.get(slot_order)

        if slot_order in removals and thumbnail is not None:
            if thumbnail.image:
                thumbnail.image.delete(save=False)
            thumbnail.delete()
            thumbnail = None

        uploaded_image = files.get(f'thumbnail_{slot_order}')
        if not uploaded_image:
            continue

        if thumbnail is None:
            PackageThumbnail.objects.create(
                package=package,
                sort_order=slot_order,
                image=uploaded_image,
            )
            continue

        if thumbnail.image:
            thumbnail.image.delete(save=False)
        thumbnail.image = uploaded_image
        thumbnail.save(update_fields=['image', 'updated_at'])


def _get_package_draft(request):
    return request.session.get(PACKAGE_ORDER_SESSION_KEY, {})


def _set_package_draft(request, draft):
    request.session[PACKAGE_ORDER_SESSION_KEY] = draft
    request.session.modified = True


def _clear_package_draft(request):
    if PACKAGE_ORDER_SESSION_KEY in request.session:
        del request.session[PACKAGE_ORDER_SESSION_KEY]
        request.session.modified = True


def _create_customer_notification(user, notification_type, title, message, status_value='', cake_order=None, package_order=None, payment=None):
    notification = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        status_value=status_value,
        cake_order=cake_order,
        package_order=package_order,
        payment=payment,
    )

    if user.email:
        send_mail(
            title,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

    return notification


def _create_order_status_notification(order, order_type, previous_status):
    if previous_status == order.order_status:
        return None

    notification = ORDER_STATUS_NOTIFICATION_CONFIG.get(
        order_type, {}).get(order.order_status)
    if not notification:
        return None

    order_label = 'Cake Order' if order_type == 'cake' else 'Package Booking'
    return _create_customer_notification(
        order.user,
        'order_status',
        f'{order_label} #{order.id} updated',
        (
            f'{notification["headline"]} '
            f'Current status: {order.get_order_status_display()}. '
            'Open your tracking page for the latest details.'
        ),
        status_value=order.order_status,
        cake_order=order if order_type == 'cake' else None,
        package_order=order if order_type == 'package' else None,
    )


def _create_payment_status_notification(payment, previous_status):
    if previous_status == payment.payment_status:
        return None

    notification = PAYMENT_STATUS_NOTIFICATION_CONFIG.get(
        payment.payment_status)
    if not notification:
        return None

    if payment.cake_order_id:
        order = payment.cake_order
        order_label = 'Cake Order'
    elif payment.package_order_id:
        order = payment.package_order
        order_label = 'Package Booking'
    else:
        return None

    return _create_customer_notification(
        order.user,
        'payment_status',
        f'Payment #{payment.id} updated',
        (
            f'{notification["headline"]} '
            f'For {order_label} #{order.id}, the payment status is now '
            f'{payment.get_payment_status_display()}. '
            'Check your order tracking page for the latest status.'
        ),
        status_value=payment.payment_status,
        cake_order=payment.cake_order if payment.cake_order_id else None,
        package_order=payment.package_order if payment.package_order_id else None,
        payment=payment,
    )


def _log_staff_activity(actor, action, description, target_type='', target_id=None):
    if not actor or not actor.is_authenticated:
        return None

    actor_role = 'Administrator' if actor.is_superuser else ''
    if hasattr(actor, 'profile'):
        actor_role = actor.profile.get_role_display()

    return ActivityLog.objects.create(
        actor=actor,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        description=description,
    )


def _build_payment_qr_response(amount, order_label):
    preview = build_gcash_checkout_details(amount, order_label)
    return {
        'amount': preview['amount'],
        'amount_label': preview['amount_label'],
        'merchant_name': preview['account_name'],
        'merchant_number': preview['account_number'],
        'instruction_note': preview['payment_note'],
        'instruction_payload': preview['instruction_payload'],
        'qr_code_data_uri': preview['qr_code_data_uri'],
    }


@login_required
def payment_qr_preview(request):
    amount = _parse_decimal(request.GET.get('amount'))
    if amount <= Decimal('0.00'):
        return JsonResponse({'error': 'A positive amount is required.'}, status=400)

    order_label = request.GET.get('order_label', '').strip() or 'Order payment'
    return JsonResponse(_build_payment_qr_response(amount, order_label))


def _is_local_demo_request(request):
    remote_addr = request.META.get('REMOTE_ADDR')
    return settings.DEBUG and remote_addr in {None, '127.0.0.1', '::1'}


def _get_demo_request_mode(request):
    if _is_local_demo_request(request):
        return 'local'
    if getattr(settings, 'DEMO_BOT_REMOTE_ENABLED', False):
        return 'browser'
    return None


def _parse_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_demo_state(request):
    return request.session.get(DEMO_SESSION_STATE_KEY)


def _set_demo_state(request, state):
    request.session[DEMO_SESSION_STATE_KEY] = state
    request.session.modified = True


def _clear_demo_state(request):
    if DEMO_SESSION_STATE_KEY in request.session:
        del request.session[DEMO_SESSION_STATE_KEY]
        request.session.modified = True


def _process_is_running(pid):
    if not pid:
        return False
    try:
        pid_value = int(pid)
    except (TypeError, ValueError):
        return False

    if os.name == 'nt':
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid_value}', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout.strip()
        return bool(output) and 'No tasks are running' not in output

    try:
        os.kill(pid_value, 0)
    except OSError:
        return False
    return True


def _stop_process_tree(pid):
    if not _process_is_running(pid):
        return False

    pid_value = str(pid)
    if os.name == 'nt':
        result = subprocess.run(
            ['taskkill', '/PID', pid_value, '/T', '/F'],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    try:
        os.killpg(int(pid), signal.SIGTERM)
        return True
    except OSError:
        return False


def _normalize_script_steps(raw_steps):
    allowed_steps = {step_id for step_id, _ in DEMO_SCRIPT_STEPS}
    if not isinstance(raw_steps, list):
        return []
    normalized_steps = []
    for step in raw_steps:
        if not isinstance(step, str):
            continue
        step_value = step.strip()
        if step_value in allowed_steps and step_value not in normalized_steps:
            normalized_steps.append(step_value)
    return normalized_steps


def _resolve_demo_script_steps(scenario, raw_steps):
    if scenario == 'custom':
        return _normalize_script_steps(raw_steps)
    return list(DEMO_BROWSER_SCENARIO_STEPS.get(scenario, DEMO_BROWSER_SCENARIO_STEPS['full']))


def _ensure_browser_demo_user():
    user, created = User.objects.get_or_create(
        username=DEMO_BROWSER_USERNAME,
        defaults={
            'email': DEMO_BROWSER_EMAIL,
            'first_name': 'Panel',
            'last_name': 'Demo',
        },
    )
    if created or not user.check_password(DEMO_BROWSER_PASSWORD):
        user.email = DEMO_BROWSER_EMAIL
        user.first_name = 'Panel'
        user.last_name = 'Demo'
        user.set_password(DEMO_BROWSER_PASSWORD)
        user.save()

    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            'role': 'customer',
            'phone': '09171234567',
            'address': '123 Demo Street, Lucena City',
        },
    )
    profile.role = 'customer'
    if not profile.phone:
        profile.phone = '09171234567'
    if not profile.address:
        profile.address = '123 Demo Street, Lucena City'
    profile.save()
    _sync_user_staff_flags(user, profile.role)
    return user


def _ensure_browser_demo_catalog():
    cake = Cake.objects.filter(
        is_active=True,
        category='custom',
    ).exclude(
        image=''
    ).order_by('-updated_at', '-id').first()
    if cake is None:
        cake = Cake.objects.filter(is_active=True).exclude(
            image=''
        ).order_by('-updated_at', '-id').first()
    if cake is None:
        cake = Cake.objects.filter(is_active=True).order_by('-updated_at', '-id').first()
    if cake is None:
        cake = Cake.objects.create(
            name='Panel Demo Cake',
            category='birthday',
            description='A seeded cake for browser-based panel demonstrations.',
            price='1850.00',
            stock=5,
            is_active=True,
        )

    package = _get_public_package_queryset().annotate(
        thumbnail_count=Count('thumbnails', distinct=True),
    ).filter(
        Q(thumbnail_count__gt=0) | ~Q(image=''),
    ).order_by('-thumbnail_count', '-updated_at', '-id').first()
    if package is None:
        package = _get_public_package_queryset().order_by('-updated_at', '-id').first()
    if package is None:
        package = Package.objects.create(
            name='Panel Demo Package',
            package_type='kids_birthday',
            description='A seeded package for browser-based panel demonstrations.',
            base_price='7500.00',
            features='Host\nBackdrop\nBasic styling',
            included_items='Cake\nCupcakes\nBalloons',
            status='active',
        )

    return cake, package


def _ensure_browser_demo_orders(user, cake, package, payment_mode):
    default_payment_status = 'verifying' if payment_mode == 'gcash' else 'pending'
    reference_number = 'DEMO-GCASH-001' if payment_mode == 'gcash' else ''

    cake_order = CakeOrder.objects.filter(user=user, cake=cake).order_by('-id').first()
    if cake_order is None:
        cake_order = CakeOrder.objects.create(
            user=user,
            cake=cake,
            quantity=1,
            total_price=cake.price,
            order_status='confirmed',
            theme='Panel showcase',
            size='8 inches',
            shape='Round',
            flavor='Chocolate',
            frosting='Buttercream',
            filling='Chocolate Ganache',
            color_palette='Gold and blush',
            message_on_cake='Final Defense Demo',
            special_instructions='Prepared for the remote final defense walkthrough.',
            delivery_date=timezone.now() + timedelta(days=7),
            delivery_address='123 Demo Street, Lucena City',
            contact_name='Panel Demo',
            contact_phone='09171234567',
            contact_email=DEMO_BROWSER_EMAIL,
        )
    CakeCustomization.objects.get_or_create(
        cake_order=cake_order,
        defaults={
            'message_on_cake': cake_order.message_on_cake,
            'color_palette': cake_order.color_palette,
            'additional_decorations': 'Fresh Flowers\nEdible Sprinkles',
        },
    )
    cake_payment = cake_order.payments.order_by('-created_at').first()
    if cake_payment is None:
        cake_payment = Payment.objects.create(
            amount=cake_order.total_price,
            payment_method=payment_mode,
            payment_status=default_payment_status,
            cake_order=cake_order,
            reference_number=reference_number,
        )
    else:
        cake_payment.payment_method = payment_mode
        cake_payment.payment_status = default_payment_status
        cake_payment.reference_number = reference_number
        cake_payment.save(update_fields=['payment_method', 'payment_status', 'reference_number', 'updated_at'])

    package_order = PackageOrder.objects.filter(user=user, package=package).order_by('-id').first()
    if package_order is None:
        package_order = PackageOrder.objects.create(
            user=user,
            package=package,
            total_price=package.base_price,
            order_status='preparing',
            event_type=package.package_type,
            event_date=timezone.localdate() + timedelta(days=14),
            event_time=datetime.strptime('14:00', '%H:%M').time(),
            venue='Hanilies Demo Hall, Lucena City',
            contact_name='Panel Demo',
            contact_phone='09171234567',
            contact_email=DEMO_BROWSER_EMAIL,
            selected_addons='Themed Cupcakes\nBackdrop Decor',
            cake_flavor='Vanilla',
            cake_frosting='Buttercream',
            cake_filling='Mango',
            cake_message='Celebrate Success',
        )
    package_payment = package_order.payments.order_by('-created_at').first()
    if package_payment is None:
        package_payment = Payment.objects.create(
            amount=package_order.total_price,
            payment_method=payment_mode,
            payment_status=default_payment_status,
            package_order=package_order,
            reference_number=reference_number,
        )
    else:
        package_payment.payment_method = payment_mode
        package_payment.payment_status = default_payment_status
        package_payment.reference_number = reference_number
        package_payment.save(update_fields=['payment_method', 'payment_status', 'reference_number', 'updated_at'])

    Notification.objects.get_or_create(
        user=user,
        notification_type='order_status',
        title='Your cake order has been confirmed.',
        cake_order=cake_order,
        defaults={
            'message': 'This seeded order is ready to showcase cake tracking during the panel defense.',
            'status_value': cake_order.order_status,
        },
    )
    Notification.objects.get_or_create(
        user=user,
        notification_type='order_status',
        title='Your package booking is now being prepared.',
        package_order=package_order,
        defaults={
            'message': 'This seeded package booking is ready to showcase the remote demo flow.',
            'status_value': package_order.order_status,
        },
    )

    return cake_order, package_order


def _build_browser_demo_payload(request, scenario, script_steps, payment_mode):
    demo_user = _ensure_browser_demo_user()
    cake, package = _ensure_browser_demo_catalog()
    cake_order, package_order = _ensure_browser_demo_orders(
        demo_user,
        cake,
        package,
        payment_mode,
    )

    step_urls = {
        'home': reverse('home'),
        'login': reverse('login'),
        'ai_recommendations': reverse('home'),
        'cakes': f"{reverse('cakes')}?category={cake.category}",
        'cake_order': f"{reverse('cake_customize')}?cake_id={cake.id}",
        'cake_tracking': f"{reverse('order_tracking')}?type=cake&id={cake_order.id}",
        'packages': f"{reverse('packages')}?type={package.package_type}",
        'package_order': f"{reverse('order_package')}?package_id={package.id}",
        'package_tracking': f"{reverse('order_tracking')}?type=package&id={package_order.id}",
        'profile': reverse('profile'),
        'order_tracking': reverse('order_tracking'),
        'about': reverse('about'),
        'contact': reverse('contact'),
    }

    launch_step = script_steps[0] if script_steps else 'home'
    return {
        'scenario': scenario,
        'script_steps': script_steps,
        'launch_url': step_urls.get(launch_step, reverse('home')),
        'step_urls': step_urls,
        'credentials': {
            'username': DEMO_BROWSER_USERNAME,
            'password': DEMO_BROWSER_PASSWORD,
        },
    }


def _get_running_demo_state(request):
    state = _get_demo_state(request)
    if not state:
        return None
    if state.get('mode') == 'browser':
        return state
    if not _process_is_running(state.get('pid')):
        _clear_demo_state(request)
        return None
    return state


@require_POST
def start_demo_bot(request):
    demo_mode = _get_demo_request_mode(request)
    if demo_mode is None:
        return JsonResponse({
            'ok': False,
            'error': 'The demo bot is not enabled for this environment.',
        }, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    scenario = payload.get('scenario', 'full')
    if scenario not in DEMO_SCENARIOS:
        return JsonResponse({
            'ok': False,
            'error': 'Unsupported demo scenario requested.',
        }, status=400)

    running_state = _get_running_demo_state(request)
    if running_state:
        return JsonResponse({
            'ok': False,
            'error': 'A demo bot is already running. Stop it before starting another one.',
            'active_demo': running_state,
        }, status=409)

    browser = payload.get('browser', 'auto')
    if browser not in {'auto', 'edge', 'chrome'}:
        browser = 'auto'

    delay = max(0.0, _parse_float(payload.get('delay'), 1.2))
    hold_seconds = max(0.0, _parse_float(payload.get('hold_seconds'), 20.0))
    headless = bool(payload.get('headless', False))
    close_browser = bool(payload.get('close_browser', True))
    narrate = bool(payload.get('narrate', True)) and not headless
    base_url = request.build_absolute_uri('/').rstrip('/')
    payment_mode = payload.get('payment_mode', 'gcash')
    if payment_mode not in {'cod', 'gcash'}:
        payment_mode = 'gcash'
    script_steps = _normalize_script_steps(payload.get('script_steps', []))

    if scenario == 'custom' and not script_steps:
        return JsonResponse({
            'ok': False,
            'error': 'Choose at least one custom script step before starting the demo.',
        }, status=400)

    if demo_mode == 'browser':
        resolved_steps = _resolve_demo_script_steps(scenario, payload.get('script_steps', []))
        browser_demo = _build_browser_demo_payload(
            request,
            scenario,
            resolved_steps,
            payment_mode,
        )
        state = {
            'mode': 'browser',
            'scenario': scenario,
            'script_steps': resolved_steps,
            'payment_mode': payment_mode,
            'started_at': timezone.now().isoformat(),
        }
        _set_demo_state(request, state)
        return JsonResponse({
            'ok': True,
            'mode': 'browser',
            'scenario': scenario,
            'active_demo': state,
            'browser_demo': browser_demo,
            'message': f'{scenario.title()} demo prepared. This browser will walk through the deployed site for the panel defense.',
        })

    command = [
        sys.executable,
        str(settings.BASE_DIR / 'manage.py'),
        'demo_bot',
        scenario,
        '--base-url',
        base_url,
        '--browser',
        browser,
        '--delay',
        str(delay),
        '--hold-seconds',
        str(hold_seconds if close_browser else 0),
        '--payment-mode',
        payment_mode,
    ]

    if scenario == 'custom':
        command.extend(['--script', ','.join(script_steps)])

    if narrate:
        command.append('--narrate')
    if headless:
        command.append('--headless')
    if close_browser or headless:
        command.append('--close-browser')

    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if os.name == 'nt':
        creationflags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)

    try:
        process = subprocess.Popen(
            command,
            cwd=settings.BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(os.name != 'nt'),
        )
    except OSError:
        return JsonResponse({
            'ok': False,
            'error': 'Unable to start the demo bot process on this machine.',
        }, status=500)

    state = {
        'pid': process.pid,
        'scenario': scenario,
        'script_steps': script_steps,
        'payment_mode': payment_mode,
        'started_at': timezone.now().isoformat(),
    }
    _set_demo_state(request, state)

    return JsonResponse({
        'ok': True,
        'mode': 'local',
        'scenario': scenario,
        'pid': process.pid,
        'script_steps': script_steps,
        'message': f'{scenario.title()} demo started. Watch the automated browser window for the live walkthrough.',
    })


def demo_bot_status(request):
    if _get_demo_request_mode(request) is None:
        return JsonResponse({'ok': False, 'error': 'Demo bot access is not enabled here.'}, status=403)

    state = _get_running_demo_state(request)
    if not state:
        return JsonResponse({'ok': True, 'running': False})

    return JsonResponse({'ok': True, 'running': True, 'active_demo': state})


@require_POST
def stop_demo_bot(request):
    if _get_demo_request_mode(request) is None:
        return JsonResponse({'ok': False, 'error': 'Demo bot access is not enabled here.'}, status=403)

    state = _get_demo_state(request)
    if not state:
        return JsonResponse({
            'ok': False,
            'error': 'No running demo bot was found for this browser session.',
        }, status=404)

    if state.get('mode') == 'browser':
        _clear_demo_state(request)
        return JsonResponse({
            'ok': True,
            'message': 'The browser-based demo walkthrough was stopped.',
        })

    pid = state.get('pid')
    if not _process_is_running(pid):
        _clear_demo_state(request)
        return JsonResponse({
            'ok': True,
            'message': 'The demo bot had already finished.',
        })

    if not _stop_process_tree(pid):
        return JsonResponse({
            'ok': False,
            'error': 'Unable to stop the active demo bot process.',
        }, status=500)

    _clear_demo_state(request)
    return JsonResponse({
        'ok': True,
        'message': 'The active demo bot was stopped.',
    })


def _build_tracking_steps(order_kind, order_status):
    if order_kind == 'package':
        flow = [
            ('pending', 'Order Placed', 'Your package order has been received.'),
            ('confirmed', 'Order Confirmed',
             'Your event package order and details are confirmed.'),
            ('preparing', 'Preparation Ongoing',
             'Your package inclusions and cake are being prepared.'),
            ('ready_for_pickup', 'Ready for Pickup',
             'Your package is ready for pickup or dispatch.'),
            ('completed', 'Completed', 'Your package order has been completed.'),
        ]
    else:
        flow = [
            ('pending', 'Order Placed', 'Your cake order has been received.'),
            ('confirmed', 'Order Confirmed', 'Your cake order is confirmed.'),
            ('preparing', 'Preparing Cake',
             'The baking team is preparing your order.'),
            ('out_for_delivery', 'Out for Delivery',
             'Your order is already on the way.'),
            ('delivered', 'Delivered', 'Your order has been delivered.'),
        ]

    reached = True
    steps = []
    for value, label, description in flow:
        state = 'completed' if reached else 'pending'
        if value == order_status:
            state = 'active'
            reached = False
        steps.append({'value': value, 'label': label,
                     'description': description, 'state': state})

    if order_status == 'cancelled':
        steps.append({
            'value': 'cancelled',
            'label': 'Cancelled',
            'description': 'This order was cancelled and is no longer being processed.',
            'state': 'active',
        })
    return steps


def _get_top_value(queryset, field_name):
    return queryset.values(field_name).annotate(total=Count('id')).order_by('-total').first()


def _build_user_preference_profile(user):
    if not user.is_authenticated:
        return {
            'has_history': False,
            'order_count': 0,
            'headline': 'Best-Selling Picks',
            'subheadline': 'Rule-based suggestions based on current best sellers and order volume.',
        }

    cake_orders = CakeOrder.objects.filter(user=user)
    package_orders = PackageOrder.objects.filter(user=user)
    total_order_count = cake_orders.count() + package_orders.count()
    top_cake_category = _get_top_value(
        cake_orders.exclude(cake__category=''), 'cake__category')
    top_cake_flavor = _get_top_value(cake_orders.exclude(flavor=''), 'flavor')
    top_package_type = _get_top_value(
        package_orders.exclude(event_type=''), 'event_type')

    cake_totals = cake_orders.aggregate(
        total=Sum('total_price'), count=Count('id'))
    package_totals = package_orders.aggregate(
        total=Sum('total_price'), count=Count('id'))

    average_cake_budget = None
    if cake_totals['count']:
        average_cake_budget = cake_totals['total'] / cake_totals['count']

    average_package_budget = None
    if package_totals['count']:
        average_package_budget = package_totals['total'] / \
            package_totals['count']

    has_history = total_order_count > 0
    if has_history:
        headline = 'Recommended For Your Next Celebration'
        subheadline = f'Rule-based suggestions tuned from your {total_order_count} previous order(s) and current best sellers.'
    else:
        headline = 'Best-Selling Picks'
        subheadline = 'Rule-based suggestions based on current best sellers and order volume.'

    return {
        'has_history': has_history,
        'order_count': total_order_count,
        'headline': headline,
        'subheadline': subheadline,
        'top_cake_category': top_cake_category,
        'top_cake_flavor': top_cake_flavor,
        'top_package_type': top_package_type,
        'average_cake_budget': average_cake_budget,
        'average_package_budget': average_package_budget,
        'ordered_cake_ids': set(cake_orders.exclude(cake_id__isnull=True).values_list('cake_id', flat=True)),
        'ordered_package_ids': set(package_orders.exclude(package_id__isnull=True).values_list('package_id', flat=True)),
    }


def _price_is_close(target_price, reference_price, tolerance=Decimal('0.35')):
    if not reference_price:
        return False
    if reference_price <= 0:
        return False
    difference = abs(target_price - reference_price)
    return difference <= (reference_price * tolerance)


def _normalize_match_score(score, floor=72, ceiling=98):
    return max(floor, min(ceiling, floor + score))


def _build_cake_recommendations(user):
    category_lookup = dict(Cake.CAKE_CATEGORIES)
    profile = _build_user_preference_profile(user)
    cakes = list(Cake.objects.filter(is_active=True).annotate(
        order_count=Count('orders')).order_by('name'))
    scored_items = []

    top_category = (profile.get('top_cake_category')
                    or {}).get('cake__category')
    top_flavor = (profile.get('top_cake_flavor') or {}).get('flavor', '')

    for cake in cakes:
        score = 0
        reasons = []

        if top_category and cake.category == top_category:
            score += 18
            reasons.append(
                f"Matches your usual {category_lookup.get(top_category, top_category).lower()} orders")

        combined_text = f'{cake.name} {cake.description}'.lower()
        if top_flavor and top_flavor.lower() in combined_text:
            score += 12
            reasons.append(
                f"Aligned with your preferred {top_flavor.lower()} flavor")

        if cake.id in profile.get('ordered_cake_ids', set()):
            score += 10
            reasons.append('You have ordered this cake before')

        if _price_is_close(cake.price, profile.get('average_cake_budget')):
            score += 8
            reasons.append('Close to your usual cake budget')

        popularity_bonus = min(cake.order_count * 5, 20)
        score += popularity_bonus
        if cake.order_count:
            reasons.append(f'Popular choice with {cake.order_count} order(s)')
        elif not reasons:
            reasons.append('Fresh option for custom celebration requests')

        scored_items.append({
            'id': cake.id,
            'name': cake.name,
            'subtitle': category_lookup.get(cake.category, cake.category),
            'description': cake.description or 'Made to order for birthdays, weddings, and custom events.',
            'price': cake.price,
            'image_url': cake.image_url(),
            'url': f"{reverse('cake_customize')}?cake_id={cake.id}",
            'match_score': _normalize_match_score(score),
            'reason': reasons[0],
            'badge': 'Best Seller' if cake.order_count else 'Made to Order',
            'sales_count': cake.order_count,
        })

    scored_items.sort(
        key=lambda item: (-item['match_score'], -item['sales_count'], item['price']))
    return scored_items[:3], profile


def _build_package_recommendations(profile):
    package_lookup = dict(Package.PACKAGE_TYPES)
    packages = list(_get_public_package_queryset().annotate(
        order_count=Count('orders')).order_by('name'))
    scored_items = []

    top_type = (profile.get('top_package_type') or {}).get('event_type')

    for package in packages:
        score = 0
        reasons = []

        if top_type and package.package_type == top_type:
            score += 18
            reasons.append(
                f"Matches your usual {package_lookup.get(top_type, top_type).lower()} events")

        if package.id in profile.get('ordered_package_ids', set()):
            score += 10
            reasons.append('You have ordered this package before')

        if _price_is_close(package.base_price, profile.get('average_package_budget')):
            score += 8
            reasons.append('Close to your usual package budget')

        popularity_bonus = min(package.order_count * 5, 20)
        score += popularity_bonus
        if package.order_count:
            reasons.append(
                f'Popular package with {package.order_count} order(s)')
        elif not reasons:
            reasons.append('Strong starter package for upcoming celebrations')

        scored_items.append({
            'id': package.id,
            'name': package.name,
            'subtitle': package_lookup.get(package.package_type, package.package_type),
            'description': package.description or 'Bundle your cake, setup, and celebration extras in one order.',
            'price': package.base_price,
            'image_url': package.image.url if package.image else '/static/images/bg.png',
            'url': f"{reverse('order_package')}?package_id={package.id}",
            'match_score': _normalize_match_score(score),
            'reason': reasons[0],
            'badge': 'Top Package' if package.order_count else 'Event Ready',
            'sales_count': package.order_count,
        })

    scored_items.sort(
        key=lambda item: (-item['match_score'], -item['sales_count'], item['price']))
    return scored_items[:3]


def _build_home_insights(profile):
    top_cake = Cake.objects.filter(is_active=True).annotate(
        order_count=Count('orders')).order_by('-order_count', 'name').first()
    top_flavor = _get_top_value(CakeOrder.objects.exclude(flavor=''), 'flavor')
    top_package_type = _get_top_value(
        PackageOrder.objects.exclude(event_type=''), 'event_type')
    total_orders = CakeOrder.objects.count() + PackageOrder.objects.count()
    package_lookup = dict(Package.PACKAGE_TYPES)

    insights = [
        {
            'label': 'Best Seller',
            'title': top_cake.name if top_cake else 'Custom cakes available daily',
            'detail': f"{top_cake.order_count} order(s) recorded" if top_cake and top_cake.order_count else 'Start building order history to unlock stronger recommendations.',
            'icon': 'fas fa-fire',
        },
        {
            'label': 'Top Flavor',
            'title': (top_flavor or {}).get('flavor', 'Chocolate'),
            'detail': f"Chosen in {(top_flavor or {}).get('total', 0)} cake order(s)" if top_flavor else 'Flavor signals will update as more cake orders are placed.',
            'icon': 'fas fa-chart-pie',
        },
        {
            'label': 'Event Trend',
            'title': package_lookup.get((top_package_type or {}).get('event_type'), 'Celebration bundles'),
            'detail': f"{total_orders} total order(s) analyzed" if total_orders else 'Recommendations are using the live catalog while order history grows.',
            'icon': 'fas fa-sparkles',
        },
    ]

    if profile.get('has_history'):
        insights[2][
            'detail'] = f"Personalized from your {profile['order_count']} order(s) plus live best-seller signals."

    return insights


def _build_home_stats():
    current_year = timezone.now().year
    return [
        {'value': f'{current_year - 2009}+', 'label': 'Years Serving'},
        {'value': Cake.objects.filter(
            is_active=True).count(), 'label': 'Active Cakes'},
        {'value': Package.objects.filter(
            status='active').count(), 'label': 'Live Packages'},
        {'value': CakeOrder.objects.count() + PackageOrder.objects.count(),
         'label': 'Orders Logged'},
    ]


# ============================================
# MAIN SITE PAGES
# ============================================

@ensure_csrf_cookie
def home(request):
    """Home page"""
    recommended_cakes, recommendation_profile = _build_cake_recommendations(
        request.user)
    recommended_packages = _build_package_recommendations(
        recommendation_profile)
    featured_cakes = list(Cake.objects.filter(is_active=True).annotate(
        order_count=Count('orders')).order_by('-order_count', 'name')[:4])
    featured_packages = list(_get_public_package_queryset().annotate(
        order_count=Count('orders')).order_by('-order_count', 'name')[:3])

    context = {
        'hero_stats': _build_home_stats(),
        'recommendation_headline': recommendation_profile['headline'],
        'recommendation_subheadline': recommendation_profile['subheadline'],
        'recommendation_profile': recommendation_profile,
        'recommended_cakes': recommended_cakes,
        'recommended_packages': recommended_packages,
        'featured_cakes': featured_cakes,
        'featured_packages': featured_packages,
        'home_insights': _build_home_insights(recommendation_profile),
    }
    return render(request, 'hanilies/home.html', context)


def about(request):
    """About page"""
    return render(request, 'hanilies/about.html')


def contact(request):
    """Contact page"""
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')

        messages.success(
            request, 'Thank you for your message! We will get back to you soon.')
        return redirect('contact')

    return render(request, 'hanilies/contact.html')


def cakes(request):
    """Cakes listing page"""
    cake_list = Cake.objects.filter(is_active=True).order_by('name')
    selected_category = request.GET.get('category', '').strip()
    search_term = request.GET.get('q', '').strip()

    if selected_category:
        cake_list = cake_list.filter(category=selected_category)
    if search_term:
        cake_list = cake_list.filter(Q(name__icontains=search_term) | Q(
            description__icontains=search_term))

    context = {
        'cakes': cake_list,
        'categories': Cake.CAKE_CATEGORIES,
        'selected_category': selected_category,
        'search_term': search_term,
    }
    return render(request, 'hanilies/cakes.html', context)


def packages(request):
    """Packages listing page"""
    package_list = _get_public_package_queryset().prefetch_related('thumbnails').order_by('name')
    selected_type = request.GET.get('type', '').strip()
    search_term = request.GET.get('q', '').strip()

    if selected_type:
        package_list = package_list.filter(package_type=selected_type)
    if search_term:
        package_list = package_list.filter(
            Q(name__icontains=search_term) | Q(description__icontains=search_term))

    context = {
        'packages': package_list,
        'package_types': PUBLIC_PACKAGE_TYPES,
        'selected_type': selected_type,
        'search_term': search_term,
    }
    return render(request, 'hanilies/packages.html', context)


# ============================================
# AUTHENTICATION PAGES
# ============================================

def login_view(request):
    """User login page"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Ensure user has a profile
            if not hasattr(user, 'profile'):
                if user.is_superuser:
                    _assign_user_role(user, 'owner')
                else:
                    _assign_user_role(user, 'customer')

            # Check if user has admin role (for redirect)
            role = user.profile.role

            if user.is_superuser or role in STAFF_ROLE_VALUES:
                return redirect('admin_dashboard')
            else:
                return redirect('profile')
        else:
            return render(request, 'hanilies/login.html', {'error': 'Invalid username or password'})

    return render(request, 'hanilies/login.html')


def register_view(request):
    """User registration page"""
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        firstname = request.POST.get('firstname')
        lastname = request.POST.get('lastname')
        phone = request.POST.get('phone')

        if password != confirm_password:
            return render(request, 'hanilies/register.html', {'error': 'Passwords do not match'})

        if User.objects.filter(username=username).exists():
            return render(request, 'hanilies/register.html', {'error': 'Username already exists'})

        if User.objects.filter(email=email).exists():
            return render(request, 'hanilies/register.html', {'error': 'Email already registered'})

        if len(password) < 8:
            return render(request, 'hanilies/register.html', {'error': 'Password must be at least 8 characters'})

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=firstname,
            last_name=lastname
        )

        UserProfile.objects.create(
            user=user,
            phone=phone,
            role='customer'
        )
        _sync_user_staff_flags(user, 'customer')

        login(request, user)
        messages.success(
            request, 'Registration successful! Welcome to Hanilies Cakeshoppe!')
        return redirect('profile')

    return render(request, 'hanilies/register.html')


def logout_view(request):
    """Log out user"""
    storage = messages.get_messages(request)
    storage.used = True
    logout(request)
    return redirect('home')


# ============================================
# USER PAGES (Require Login)
# ============================================

@login_required
def profile(request):
    """User profile page"""
    if not hasattr(request.user, 'profile'):
        _assign_user_role(request.user, 'customer')

    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.save()

        if hasattr(user, 'profile'):
            user.profile.phone = request.POST.get('phone', user.profile.phone)
            user.profile.address = request.POST.get(
                'address', user.profile.address)
            user.profile.save()

        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    cake_orders = CakeOrder.objects.filter(user=request.user)
    package_orders = PackageOrder.objects.filter(user=request.user)
    total_spent = (
        cake_orders.aggregate(total=Sum('total_price')).get(
            'total') or Decimal('0.00')
    ) + (
        package_orders.aggregate(total=Sum('total_price')).get(
            'total') or Decimal('0.00')
    )
    recent_notifications = list(
        Notification.objects.filter(user=request.user).select_related(
            'cake_order', 'package_order', 'payment'
        )[:6]
    )
    context = {
        'order_count': cake_orders.count() + package_orders.count(),
        'total_spent': total_spent,
        'recent_notifications': recent_notifications,
        'unread_notification_count': sum(
            1 for notification in recent_notifications if not notification.is_read),
    }
    return render(request, 'hanilies/profile.html', context)


@login_required
def change_password(request):
    """Change user password"""
    if request.method == 'POST':
        user = request.user
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not user.check_password(current_password):
            messages.error(request, 'Current password is incorrect')
            return redirect('profile')

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match')
            return redirect('profile')

        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters')
            return redirect('profile')

        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user)

        messages.success(request, 'Password changed successfully!')
        return redirect('profile')

    return redirect('profile')


@login_required
def update_preferences(request):
    """Update user preferences"""
    if request.method == 'POST':
        account_notifications = request.POST.get(
            'account_notifications') == 'on'
        promo_emails = request.POST.get('promo_emails') == 'on'
        sms_notifications = request.POST.get('sms_notifications') == 'on'

        request.session['account_notifications'] = account_notifications
        request.session['promo_emails'] = promo_emails
        request.session['sms_notifications'] = sms_notifications

        messages.success(request, 'Preferences updated successfully!')
        return redirect('profile')

    return redirect('profile')


@login_required
def order_tracking(request):
    """Track order status"""
    cake_orders = list(
        CakeOrder.objects.filter(user=request.user).select_related(
            'cake').prefetch_related('payments').order_by('-created_at')
    )
    package_orders = list(
        PackageOrder.objects.filter(user=request.user).select_related(
            'package').prefetch_related('payments').order_by('-created_at')
    )

    selected_type = request.GET.get('type')
    selected_id = request.GET.get('id')
    selected_order = None

    if selected_type == 'cake' and selected_id:
        selected_order = next(
            (order for order in cake_orders if str(order.id) == selected_id), None)
    elif selected_type == 'package' and selected_id:
        selected_order = next(
            (order for order in package_orders if str(order.id) == selected_id), None)

    if selected_order is None:
        if cake_orders:
            selected_type = 'cake'
            selected_order = cake_orders[0]
        elif package_orders:
            selected_type = 'package'
            selected_order = package_orders[0]

    selected_payment = None
    selected_payments = []
    selected_customization = None
    selected_refund_request = None
    cancellation_quote = None
    tracking_steps = []
    selected_notifications = []
    if selected_order is not None:
        selected_payments = list(_get_order_payments_queryset(selected_order))
        selected_payment = _get_order_primary_payment(selected_order)
        if selected_type == 'cake':
            selected_customization = getattr(selected_order, 'customization', None)
        selected_refund_request = getattr(selected_order, 'refund_request', None)
        if selected_refund_request is None:
            cancellation_quote = _build_cancellation_quote(
                selected_type, selected_order)
        tracking_steps = _build_tracking_steps(
            selected_type, selected_order.order_status)

        notification_queryset = Notification.objects.filter(user=request.user)
        if selected_type == 'cake':
            notification_queryset = notification_queryset.filter(
                cake_order=selected_order)
        else:
            notification_queryset = notification_queryset.filter(
                package_order=selected_order)

        notification_queryset.filter(is_read=False).update(is_read=True)
        selected_notifications = list(
            notification_queryset.select_related('payment')[:8]
        )

    context = {
        'cake_orders': cake_orders,
        'package_orders': package_orders,
        'selected_order': selected_order,
        'selected_order_type': selected_type,
        'selected_payment': selected_payment,
        'selected_payments': selected_payments,
        'selected_customization': selected_customization,
        'selected_refund_request': selected_refund_request,
        'cancellation_quote': cancellation_quote,
        'tracking_steps': tracking_steps,
        'selected_notifications': selected_notifications,
    }
    return render(request, 'hanilies/order_tracking.html', context)


@login_required
@require_POST
def request_order_cancellation(request, order_type, order_id):
    if order_type == 'cake':
        order = get_object_or_404(CakeOrder, id=order_id, user=request.user)
    elif order_type == 'package':
        order = get_object_or_404(PackageOrder, id=order_id, user=request.user)
    else:
        raise PermissionDenied('Invalid order type.')

    if getattr(order, 'refund_request', None) is not None:
        messages.info(request, 'A cancellation request for this order is already on file.')
        return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")

    cancellation_quote = _build_cancellation_quote(order_type, order)
    if not cancellation_quote.get('allowed'):
        messages.error(request, cancellation_quote.get('reason', 'This order cannot be cancelled at the moment.'))
        return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(request, 'Please provide a reason for the cancellation request.')
        return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")

    refund_payment = _get_order_primary_payment(order)
    refund_request = RefundRequest.objects.create(
        cake_order=order if order_type == 'cake' else None,
        package_order=order if order_type == 'package' else None,
        payment=refund_payment,
        requested_by=request.user,
        reason=reason,
        internal_note=cancellation_quote['reason'],
        penalty_fee=cancellation_quote['penalty_fee'],
        refundable_amount=cancellation_quote['refundable_amount'],
        status='requested',
    )
    _create_refund_status_notification(refund_request)
    messages.success(request, 'Your cancellation request has been submitted for admin review.')
    return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")


@login_required
def cake_customize(request):
    """Customize a cake"""
    selected_cake_id = request.POST.get(
        'cake_id') if request.method == 'POST' else request.GET.get('cake_id')
    cake_queryset = Cake.objects.filter(is_active=True)
    if not cake_queryset.exists():
        messages.error(
            request, 'No active cakes are available yet. Please add cakes from the admin panel first.')
        return redirect('cakes')

    selected_cake = get_object_or_404(
        cake_queryset, id=selected_cake_id) if selected_cake_id else cake_queryset.order_by('name').first()
    defaults = _get_profile_defaults(request.user)

    if request.method == 'POST':
        quantity = max(int(request.POST.get('quantity', 1) or 1), 1)
        selected_decorations = request.POST.getlist('decorations')
        decoration_labels, decoration_total = _get_selected_option_labels(
            selected_decorations, CAKE_DECORATION_OPTIONS)
        total_price = (selected_cake.price * quantity) + decoration_total
        payment_method = request.POST.get('payment_method', 'cod')
        deposit_amount, balance_due = _calculate_deposit_breakdown(total_price)
        reference_number = request.POST.get('reference_number', '').strip()
        proof_image = request.FILES.get('proof_image')

        if payment_method not in PAYMENT_PLAN_LABELS:
            payment_method = 'cod'

        if not reference_number or proof_image is None:
            messages.error(
                request, 'A GCash reference number and proof of payment are required to place the order.')
        else:
            cake_order = CakeOrder.objects.create(
                user=request.user,
                cake=selected_cake,
                quantity=quantity,
                total_price=total_price,
                payment_plan=payment_method,
                deposit_amount=total_price if payment_method == 'gcash' else deposit_amount,
                balance_due=Decimal('0.00') if payment_method == 'gcash' else balance_due,
                theme=request.POST.get('theme', '').strip(),
                size=request.POST.get('size', '').strip(),
                shape=request.POST.get('shape', '').strip() or 'Round',
                flavor=request.POST.get('flavor', '').strip() or 'Chocolate',
                frosting=request.POST.get(
                    'frosting', '').strip() or 'Buttercream',
                filling=request.POST.get('filling', '').strip(),
                color_palette=request.POST.get('color_palette', '').strip(),
                message_on_cake=request.POST.get(
                    'message_on_cake', '').strip(),
                special_instructions=request.POST.get(
                    'special_instructions', '').strip(),
                delivery_date=_parse_delivery_datetime(
                    request.POST.get('delivery_date')),
                delivery_address=request.POST.get(
                    'delivery_address', '').strip(),
                contact_name=request.POST.get('contact_name', '').strip(),
                contact_phone=request.POST.get('contact_phone', '').strip(),
                contact_email=request.POST.get('contact_email', '').strip(),
            )

            CakeCustomization.objects.create(
                cake_order=cake_order,
                message_on_cake=cake_order.message_on_cake,
                color_palette=cake_order.color_palette,
                design_reference=request.FILES.get('design_reference'),
                additional_decorations='\n'.join(decoration_labels),
            )

            _create_checkout_payments(
                cake_order,
                payment_method,
                reference_number,
                proof_image,
            )
            messages.success(
                request,
                (
                    f'Cake order #{cake_order.id} was placed successfully. '
                    f'Your {_get_payment_plan_label(payment_method).lower()} is now waiting for payment review.'
                ),
            )
            return redirect(f"{reverse('order_tracking')}?type=cake&id={cake_order.id}")

    cake_order_label = f'{selected_cake.name} cake order'
    base_deposit_amount, _ = _calculate_deposit_breakdown(selected_cake.price)
    context = {
        'cake': selected_cake,
        'cakes': cake_queryset.order_by('name'),
        'decoration_options': CAKE_DECORATION_OPTIONS,
        'theme_options': CAKE_THEME_OPTIONS,
        'payment_plan_labels': PAYMENT_PLAN_LABELS,
        'default_deposit_amount': base_deposit_amount,
        'defaults': defaults,
        'gcash_account': get_gcash_profile(),
        'gcash_preview': build_gcash_checkout_details(
            base_deposit_amount,
            cake_order_label,
        ),
        'payment_qr_preview_url': reverse('payment_qr_preview'),
    }
    return render(request, 'hanilies/cake_customize.html', context)


@login_required
def package_order(request):
    """Order a package"""
    draft = _get_package_draft(request)
    selected_package_id = request.POST.get('package_id') if request.method == 'POST' else request.GET.get(
        'package_id') or request.GET.get('package') or draft.get('package_id')
    package_queryset = _get_public_package_queryset()

    if not package_queryset.exists():
        messages.error(
            request, 'No active packages are available yet. Please add packages from the admin panel first.')
        return redirect('packages')

    selected_package = get_object_or_404(package_queryset, id=selected_package_id) if selected_package_id and str(
        selected_package_id).isdigit() else package_queryset.order_by('name').first()

    if request.method == 'POST':
        event_type = request.POST.get('event_type', selected_package.package_type)
        if event_type not in PUBLIC_EVENT_TYPE_VALUES:
            messages.error(
                request, 'Selected event type is no longer available for package bookings.')
            context = {
                'package': selected_package,
                'packages': package_queryset.order_by('name'),
                'event_types': PUBLIC_EVENT_TYPES,
                'addon_options': PACKAGE_ADDON_OPTIONS,
                'draft': draft,
            }
            return render(request, 'hanilies/package_order.html', context)

        selected_addons = request.POST.getlist('selected_addons')
        addon_labels, addon_total = _get_selected_option_labels(
            selected_addons, PACKAGE_ADDON_OPTIONS)
        updated_draft = {
            'package_id': str(selected_package.id),
            'event_type': event_type,
            'selected_addons': selected_addons,
            'selected_addon_labels': addon_labels,
            'addons_total': str(addon_total),
            'base_total': str(selected_package.base_price + addon_total),
        }
        existing_draft = _get_package_draft(request)
        existing_draft.update(updated_draft)
        _set_package_draft(request, existing_draft)
        return redirect('package_cake_customize')

    context = {
        'package': selected_package,
        'packages': package_queryset.order_by('name'),
        'event_types': PUBLIC_EVENT_TYPES,
        'addon_options': PACKAGE_ADDON_OPTIONS,
        'draft': draft,
    }
    return render(request, 'hanilies/package_order.html', context)


@login_required
def package_cake_customize(request):
    """Customize cake for a package"""
    draft = _get_package_draft(request)
    package_id = draft.get('package_id')
    if not package_id:
        messages.error(request, 'Please select a package first.')
        return redirect('order_package')

    selected_package = get_object_or_404(_get_public_package_queryset(), id=package_id)

    if request.method == 'POST':
        size_key = request.POST.get('cake_size', 'standard')
        selected_decorations = request.POST.getlist('cake_decorations')
        decoration_labels, decoration_total = _get_selected_option_labels(
            selected_decorations, PACKAGE_CAKE_DECORATIONS)
        size_option = PACKAGE_CAKE_UPGRADES.get(
            size_key, PACKAGE_CAKE_UPGRADES['standard'])
        cake_custom_total = size_option['price'] + decoration_total

        draft.update({
            'cake_theme': request.POST.get('theme', '').strip(),
            'cake_flavor': request.POST.get('flavor', '').strip(),
            'cake_frosting': request.POST.get('frosting', '').strip(),
            'cake_filling': request.POST.get('filling', '').strip(),
            'cake_size_key': size_key,
            'cake_size_label': size_option['label'],
            'cake_shape': request.POST.get('shape', '').strip(),
            'cake_message': request.POST.get('message_on_cake', '').strip(),
            'cake_color_palette': request.POST.get('color_palette', '').strip(),
            'cake_special_instructions': request.POST.get('cake_instructions', '').strip(),
            'cake_decorations': selected_decorations,
            'cake_decoration_labels': decoration_labels,
            'cake_custom_total': str(cake_custom_total),
        })
        _set_package_draft(request, draft)
        return redirect('package_payment')

    context = {
        'package': selected_package,
        'draft': draft,
        'theme_options': CAKE_THEME_OPTIONS,
        'size_options': PACKAGE_CAKE_UPGRADES,
        'decoration_options': PACKAGE_CAKE_DECORATIONS,
    }
    return render(request, 'hanilies/package_cake_customize.html', context)


@login_required
def package_payment(request):
    """Process package payment"""
    draft = _get_package_draft(request)
    package_id = draft.get('package_id')
    if not package_id:
        messages.error(request, 'Please complete the package selection first.')
        return redirect('order_package')

    selected_package = get_object_or_404(_get_public_package_queryset(), id=package_id)
    defaults = _get_profile_defaults(request.user)
    subtotal = _parse_decimal(
        draft.get('base_total', selected_package.base_price))
    custom_total = _parse_decimal(draft.get('cake_custom_total', '0.00'))
    grand_total = subtotal + custom_total
    deposit_amount, balance_due = _calculate_deposit_breakdown(grand_total)

    if request.method == 'POST':
        event_type = request.POST.get(
            'event_type', draft.get('event_type', selected_package.package_type))
        payment_method = request.POST.get('payment_method', 'cod')
        reference_number = request.POST.get('reference_number', '').strip()
        proof_image = request.FILES.get('proof_image')

        if payment_method not in PAYMENT_PLAN_LABELS:
            payment_method = 'cod'

        if event_type not in PUBLIC_EVENT_TYPE_VALUES:
            messages.error(
                request, 'Selected event type is no longer available for package bookings.')
        elif not reference_number or proof_image is None:
            messages.error(
                request, 'A GCash reference number and proof of payment are required to place the package order.')
        else:
            package_order = PackageOrder.objects.create(
                user=request.user,
                package=selected_package,
                total_price=grand_total,
                payment_plan=payment_method,
                deposit_amount=grand_total if payment_method == 'gcash' else deposit_amount,
                balance_due=Decimal('0.00') if payment_method == 'gcash' else balance_due,
                event_type=event_type,
                event_date=request.POST.get('event_date'),
                event_time=request.POST.get('event_time') or None,
                venue=request.POST.get('venue', '').strip(),
                contact_name=request.POST.get('contact_name', '').strip(),
                contact_phone=request.POST.get('contact_phone', '').strip(),
                contact_email=request.POST.get('contact_email', '').strip(),
                selected_addons='\n'.join(
                    draft.get('selected_addon_labels', [])),
                cake_flavor=draft.get('cake_flavor', ''),
                cake_frosting=draft.get('cake_frosting', ''),
                cake_filling=draft.get('cake_filling', ''),
                cake_message=draft.get('cake_message', ''),
            )

            _create_checkout_payments(
                package_order,
                payment_method,
                reference_number,
                proof_image,
            )

            _clear_package_draft(request)
            messages.success(
                request,
                (
                    f'Package order #{package_order.id} was placed successfully. '
                    f'Your {_get_payment_plan_label(payment_method).lower()} is now waiting for payment review.'
                ),
            )
            return redirect(f"{reverse('order_tracking')}?type=package&id={package_order.id}")

    package_order_label = f'{selected_package.name} package booking'
    context = {
        'package': selected_package,
        'draft': draft,
        'payment_plan_labels': PAYMENT_PLAN_LABELS,
        'defaults': defaults,
        'subtotal': subtotal,
        'custom_total': custom_total,
        'grand_total': grand_total,
        'deposit_amount': deposit_amount,
        'balance_due': balance_due,
        'gcash_account': get_gcash_profile(),
        'gcash_preview': build_gcash_checkout_details(
            deposit_amount,
            package_order_label,
        ),
        'payment_qr_preview_url': reverse('payment_qr_preview'),
    }
    return render(request, 'hanilies/package_payment.html', context)


# ============================================
# ADMIN HELPER FUNCTIONS
# ============================================

def get_admin_menu(request):
    """Generate an admin sidebar filtered by the current user's role."""
    return [
        {
            'name': item['name'],
            'url': item['url'],
            'icon': item['icon'],
        }
        for item in ADMIN_MENU_ITEMS
        if _user_has_any_role(request.user, item['roles'])
    ]


def is_admin_user(user):
    """Check if user has admin access"""
    return _user_has_any_role(user, STAFF_ROLE_VALUES)


# ============================================
# ADMIN DASHBOARD
# ============================================

@login_required
def admin_dashboard(request):
    """Admin dashboard with statistics"""
    access_denied = _require_admin_roles(request, STAFF_ROLE_VALUES, 'home')
    if access_denied:
        return access_denied

    if not hasattr(request.user, 'profile'):
        if request.user.is_superuser:
            _assign_user_role(request.user, 'owner')
        else:
            _assign_user_role(request.user, 'customer')

    role = getattr(request.user, 'profile', None)
    admin_menu = get_admin_menu(request)
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    total_sales_today = Payment.objects.filter(
        payment_status='paid',
        paid_at__date=today,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_sales_week = Payment.objects.filter(
        payment_status='paid',
        paid_at__date__gte=start_of_week,
        paid_at__date__lte=today,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_sales_month = Payment.objects.filter(
        payment_status='paid',
        paid_at__date__gte=start_of_month,
        paid_at__date__lte=today,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    context = {
        'admin_menu': admin_menu,
        'role': role.role if role else 'admin',
        'role_display': role.get_role_display() if role else 'Administrator',
        'total_cakes': Cake.objects.filter(is_active=True).count(),
        'total_cake_orders': CakeOrder.objects.count(),
        'total_packages': Package.objects.filter(status='active').count(),
        'total_package_orders': PackageOrder.objects.count(),
        'total_users': User.objects.filter(is_active=True).count(),
        'pending_payments': Payment.objects.filter(
            payment_status__in=['pending', 'verifying']).count(),
        'pending_refunds': RefundRequest.objects.filter(status='requested').count(),
        'total_sales_today': total_sales_today,
        'total_sales_week': total_sales_week,
        'total_sales_month': total_sales_month,
        'recent_activity_logs': ActivityLog.objects.select_related('actor').all()[:5],
        'recent_cake_orders': CakeOrder.objects.all().order_by('-created_at')[:5],
        'recent_package_orders': PackageOrder.objects.all().order_by('-created_at')[:5],
        'now': timezone.now(),
    }

    return render(request, 'admin/dashboard.html', context)

# ============================================
# ADMIN CAKES
# ============================================


@login_required
def admin_cakes(request):
    """List all cakes"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    cakes = Cake.objects.all().order_by('-created_at')
    return render(request, 'admin/cakes/list.html', {
        'cakes': cakes,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_add(request):
    """Add a new cake with image upload"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name')
            category = request.POST.get('category')
            if category not in CAKE_CATEGORY_VALUES:
                messages.error(request, 'Selected cake category is not available.')
                return render(request, 'admin/cakes/add.html', {
                    'admin_menu': get_admin_menu(request),
                    'cake_categories': Cake.CAKE_CATEGORIES,
                })

            description = request.POST.get('description')
            price = request.POST.get('price')
            stock = request.POST.get('stock', 0)
            is_active = request.POST.get('is_active') == 'on'

            # Create cake object
            cake = Cake(
                name=name,
                category=category,
                description=description,
                price=price,
                stock=stock,
                is_active=is_active
            )

            # Handle image upload
            if 'image' in request.FILES:
                cake.image = request.FILES['image']

            cake.save()
            _log_staff_activity(
                request.user,
                'cake_created',
                f'Created cake "{cake.name}".',
                'cake',
                cake.id,
            )
            messages.success(
                request, f'Cake "{cake.name}" added successfully!')
            return redirect('admin_cakes')

        except Exception as e:
            messages.error(request, f'Error adding cake: {str(e)}')
            return redirect('admin_cake_add')

    return render(request, 'admin/cakes/add.html', {
        'admin_menu': get_admin_menu(request),
        'cake_categories': Cake.CAKE_CATEGORIES,
    })


@login_required
def admin_cake_edit(request, cake_id):
    """Edit a cake with image upload"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    cake = get_object_or_404(Cake, id=cake_id)

    if request.method == 'POST':
        try:
            # Update basic info
            cake.name = request.POST.get('name')
            category = request.POST.get('category')
            if category not in CAKE_CATEGORY_VALUES:
                messages.error(request, 'Selected cake category is not available.')
                return render(request, 'admin/cakes/edit.html', {
                    'cake': cake,
                    'admin_menu': get_admin_menu(request),
                    'cake_categories': Cake.CAKE_CATEGORIES,
                })

            cake.category = category
            cake.description = request.POST.get('description')
            cake.price = request.POST.get('price')
            cake.stock = request.POST.get('stock')
            cake.is_active = request.POST.get('is_active') == 'on'

            # Handle image upload
            if 'image' in request.FILES:
                # Delete old image if exists
                if cake.image:
                    cake.image.delete(save=False)
                cake.image = request.FILES['image']

            # Handle remove image checkbox
            if request.POST.get('remove_image') == 'on':
                if cake.image:
                    cake.image.delete(save=False)
                    cake.image = None

            cake.save()
            _log_staff_activity(
                request.user,
                'cake_updated',
                f'Updated cake "{cake.name}".',
                'cake',
                cake.id,
            )
            messages.success(
                request, f'Cake "{cake.name}" updated successfully!')
            return redirect('admin_cakes')

        except Exception as e:
            messages.error(request, f'Error updating cake: {str(e)}')
            return redirect('admin_cake_edit', cake_id=cake_id)

    return render(request, 'admin/cakes/edit.html', {
        'cake': cake,
        'admin_menu': get_admin_menu(request),
        'cake_categories': Cake.CAKE_CATEGORIES,
    })


@login_required
def admin_cake_delete(request, cake_id):
    """Delete a cake"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'baker'})
    if access_denied:
        return access_denied

    cake = get_object_or_404(Cake, id=cake_id)
    cake_name = cake.name
    cake.delete()
    _log_staff_activity(
        request.user,
        'cake_deleted',
        f'Deleted cake "{cake_name}".',
        'cake',
        cake_id,
    )
    messages.success(request, f'Cake "{cake_name}" deleted successfully!')
    return redirect('admin_cakes')


# ============================================
# ADMIN CAKE ORDERS
# ============================================

@login_required
def admin_cake_orders(request):
    """List all cake orders"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    orders = CakeOrder.objects.all().order_by('-created_at')
    return render(request, 'admin/orders/cake_orders.html', {
        'orders': orders,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_view(request, order_id):
    """View order details"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    order = get_object_or_404(CakeOrder, id=order_id)
    return render(request, 'admin/orders/cake_order_view.html', {
        'order': order,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_update(request, order_id):
    """Update order status"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'baker'})
    if access_denied:
        return access_denied

    if request.method == 'POST':
        order = get_object_or_404(CakeOrder, id=order_id)
        previous_status = order.order_status
        new_status = request.POST.get('status')

        if new_status and new_status != previous_status:
            order.order_status = new_status
            order.save()
            if new_status == 'cancelled':
                _cancel_outstanding_balance_payments(order)
            _create_order_status_notification(order, 'cake', previous_status)
            _log_staff_activity(
                request.user,
                'cake_order_status_updated',
                f'Updated cake order #{order.id} from {previous_status} to {order.order_status}.',
                'cake_order',
                order.id,
            )
            messages.success(
                request, f'Order #{order.id} status updated to {order.get_order_status_display()}')
    return redirect('admin_cake_orders')


@login_required
@require_POST
def admin_cake_order_delete(request, order_id):
    """Delete a cake order"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor'})
    if access_denied:
        return access_denied

    order = get_object_or_404(CakeOrder, id=order_id)
    order_id_value = order.id
    order.delete()
    _log_staff_activity(
        request.user,
        'cake_order_deleted',
        f'Deleted cake order #{order_id_value}.',
        'cake_order',
        order_id_value,
    )
    messages.success(request, f'Order #{order_id_value} deleted successfully!')
    return redirect('admin_cake_orders')


# ============================================
# ADMIN PACKAGES
# ============================================

@login_required
def admin_packages(request):
    """List all packages"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    packages = Package.objects.all().prefetch_related('thumbnails').order_by('-created_at')
    return render(request, 'admin/packages/list.html', {
        'packages': packages,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_add(request):
    """Add a new package"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    if request.method == 'POST':
        try:
            package_type = request.POST.get('package_type')
            if package_type not in PUBLIC_PACKAGE_TYPE_VALUES:
                messages.error(
                    request, 'Selected package type is no longer available.')
                return render(request, 'admin/packages/add.html', {
                    'admin_menu': get_admin_menu(request),
                    'thumbnail_slots': _build_package_thumbnail_slots(),
                })

            package = Package(
                name=request.POST.get('name'),
                package_type=package_type,
                description=request.POST.get('description'),
                base_price=request.POST.get('base_price'),
                status=request.POST.get('status', 'active'),
                features=request.POST.get('features', ''),
                image=request.FILES.get('image'),
            )
            package.save()
            _sync_package_thumbnails(package, request.FILES)
            _log_staff_activity(
                request.user,
                'package_created',
                f'Created package "{package.name}".',
                'package',
                package.id,
            )
            messages.success(
                request, f'Package "{package.name}" added successfully!')
            return redirect('admin_packages')
        except Exception as e:
            messages.error(request, f'Error adding package: {str(e)}')

    return render(request, 'admin/packages/add.html', {
        'admin_menu': get_admin_menu(request),
        'thumbnail_slots': _build_package_thumbnail_slots(),
    })


@login_required
def admin_package_edit(request, package_id):
    """Edit a package"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    package = get_object_or_404(Package.objects.prefetch_related('thumbnails'), id=package_id)

    if request.method == 'POST':
        try:
            package_type = request.POST.get('package_type')
            if package_type not in PUBLIC_PACKAGE_TYPE_VALUES:
                messages.error(
                    request, 'Selected package type is no longer available.')
                return render(request, 'admin/packages/edit.html', {
                    'package': package,
                    'admin_menu': get_admin_menu(request),
                    'thumbnail_slots': _build_package_thumbnail_slots(package),
                })

            package.name = request.POST.get('name')
            package.package_type = package_type
            package.description = request.POST.get('description')
            package.base_price = request.POST.get('base_price')
            package.status = request.POST.get('status')
            package.features = request.POST.get('features', '')

            uploaded_image = request.FILES.get('image')
            if uploaded_image:
                package.image = uploaded_image

            package.save()
            thumbnail_removals = {
                slot_order
                for slot_order in range(1, MAX_PACKAGE_THUMBNAILS + 1)
                if request.POST.get(f'remove_thumbnail_{slot_order}') == 'on'
            }
            _sync_package_thumbnails(package, request.FILES, thumbnail_removals)
            _log_staff_activity(
                request.user,
                'package_updated',
                f'Updated package "{package.name}".',
                'package',
                package.id,
            )
            messages.success(
                request, f'Package "{package.name}" updated successfully!')
            return redirect('admin_packages')
        except Exception as e:
            messages.error(request, f'Error updating package: {str(e)}')

    return render(request, 'admin/packages/edit.html', {
        'package': package,
        'admin_menu': get_admin_menu(request),
        'thumbnail_slots': _build_package_thumbnail_slots(package),
    })


@login_required
def admin_package_delete(request, package_id):
    """Delete a package"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'packager'})
    if access_denied:
        return access_denied

    package = get_object_or_404(Package, id=package_id)
    package_name = package.name
    package.delete()
    _log_staff_activity(
        request.user,
        'package_deleted',
        f'Deleted package "{package_name}".',
        'package',
        package_id,
    )
    messages.success(
        request, f'Package "{package_name}" deleted successfully!')
    return redirect('admin_packages')


# ============================================
# ADMIN PACKAGE ORDERS
# ============================================

@login_required
def admin_package_orders(request):
    """List all package orders"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    orders = PackageOrder.objects.all().order_by('-created_at')
    return render(request, 'admin/orders/package_orders.html', {
        'orders': orders,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_view(request, order_id):
    """View package order details"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    order = get_object_or_404(PackageOrder, id=order_id)
    return render(request, 'admin/orders/package_order_view.html', {
        'order': order,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_update(request, order_id):
    """Update package order status"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'packager'})
    if access_denied:
        return access_denied

    if request.method == 'POST':
        order = get_object_or_404(PackageOrder, id=order_id)
        previous_status = order.order_status
        new_status = request.POST.get('status')

        if new_status and new_status != previous_status:
            order.order_status = new_status
            order.save()
            if new_status == 'cancelled':
                _cancel_outstanding_balance_payments(order)
            _create_order_status_notification(order, 'package', previous_status)
            _log_staff_activity(
                request.user,
                'package_order_status_updated',
                f'Updated package order #{order.id} from {previous_status} to {order.order_status}.',
                'package_order',
                order.id,
            )
            messages.success(
                request, f'Package Order #{order.id} status updated to {order.get_order_status_display()}')
    return redirect('admin_package_orders')


@login_required
@require_POST
def admin_package_order_delete(request, order_id):
    """Delete a package order"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor'})
    if access_denied:
        return access_denied

    order = get_object_or_404(PackageOrder, id=order_id)
    order_id_value = order.id
    order.delete()
    _log_staff_activity(
        request.user,
        'package_order_deleted',
        f'Deleted package order #{order_id_value}.',
        'package_order',
        order_id_value,
    )
    messages.success(
        request, f'Package Order #{order_id_value} deleted successfully!')
    return redirect('admin_package_orders')


# ============================================
# ADMIN PAYMENTS
# ============================================

@login_required
def admin_payments(request):
    """List all payments"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'cashier'})
    if access_denied:
        return access_denied

    # Get all payments
    payments = Payment.objects.select_related('cake_order', 'package_order').all().order_by('-created_at')

    # Categorize payments
    pending_payments = payments.filter(
        payment_method='gcash',
        payment_purpose__in=['deposit', 'full'],
        payment_status__in=['pending', 'verifying'],
    )
    balance_payments = payments.filter(
        payment_purpose='balance',
        payment_status='pending',
    )
    verified_payments = payments.filter(payment_status='paid')
    rejected_payments = payments.filter(payment_status__in=['failed', 'cancelled'])

    return render(request, 'admin/payments/list.html', {
        'payments': payments,
        'pending_payments': pending_payments,
        'balance_payments': balance_payments,
        'verified_payments': verified_payments,
        'rejected_payments': rejected_payments,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_payment_verify(request, payment_id):
    """Verify/Approve/Reject a payment"""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'cashier'})
    if access_denied:
        return access_denied

    payment = get_object_or_404(Payment, id=payment_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        previous_status = payment.payment_status

        if action == 'approve':
            payment.payment_status = 'paid'
            payment.paid_at = timezone.now()
            messages.success(
                request, f'Payment #{payment.id} has been approved!')
        elif action == 'reject':
            payment.payment_status = 'failed'
            payment.paid_at = None
            messages.warning(
                request, f'Payment #{payment.id} has been rejected.')
        elif action == 'collect_balance' and payment.payment_purpose == 'balance':
            payment.payment_status = 'paid'
            payment.paid_at = timezone.now()
            messages.success(
                request, f'Balance payment #{payment.id} has been marked as collected.')
        else:
            payment.payment_status = 'verifying'
            payment.paid_at = None
            messages.info(
                request, f'Payment #{payment.id} is under verification.')

        payment.save()
        if previous_status != payment.payment_status:
            _create_payment_status_notification(payment, previous_status)
            _sync_order_confirmation_from_payment(payment, request.user)
            _log_staff_activity(
                request.user,
                'payment_status_updated',
                f'Updated payment #{payment.id} from {previous_status} to {payment.payment_status}.',
                'payment',
                payment.id,
            )

    return redirect('admin_payments')


@login_required
@require_POST
def admin_payment_delete(request, payment_id):
    """Delete a completed payment from the admin panel"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    payment = get_object_or_404(Payment, id=payment_id)

    if payment.payment_status not in ['paid', 'failed', 'cancelled']:
        messages.error(
            request, 'Only verified or rejected payments can be deleted.')
        return redirect('admin_payments')

    payment_id_value = payment.id
    payment.delete()
    _log_staff_activity(
        request.user,
        'payment_deleted',
        f'Deleted payment #{payment_id_value}.',
        'payment',
        payment_id_value,
    )
    messages.success(request, f'Payment #{payment_id_value} deleted successfully!')
    return redirect('admin_payments')


@login_required
def admin_refunds(request):
    """List customer cancellation and refund requests."""
    access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor', 'cashier'})
    if access_denied:
        return access_denied

    refunds = RefundRequest.objects.select_related(
        'cake_order__user',
        'package_order__user',
        'payment',
        'requested_by',
        'approved_by',
        'processed_by',
    ).all()
    return render(request, 'admin/refunds/list.html', {
        'requested_refunds': refunds.filter(status='requested'),
        'approved_refunds': refunds.filter(status__in=['approved', 'processing']),
        'closed_refunds': refunds.filter(status__in=['rejected', 'processed']),
        'admin_menu': get_admin_menu(request),
    })


@login_required
@require_POST
def admin_refund_update(request, refund_id):
    """Approve, reject, or process a refund request."""
    refund_request = get_object_or_404(RefundRequest, id=refund_id)
    action = request.POST.get('action')

    if action in ['approve', 'reject']:
        access_denied = _require_admin_roles(request, {'owner', 'admin', 'manager', 'supervisor'})
    else:
        access_denied = _require_admin_roles(request, {'owner', 'admin', 'cashier'})
    if access_denied:
        return access_denied

    order = refund_request.cake_order or refund_request.package_order
    order_type = 'cake' if refund_request.cake_order_id else 'package'

    if action == 'approve':
        if _user_has_any_role(request.user, {'owner', 'admin'}) and request.POST.get('penalty_fee'):
            custom_penalty = _quantize_amount(request.POST.get('penalty_fee'))
            refundable_base = _get_paid_or_pending_gcash_total(order)
            refund_request.penalty_fee = min(refundable_base, custom_penalty)
            refund_request.refundable_amount = _quantize_amount(refundable_base - refund_request.penalty_fee)
        refund_request.status = 'approved'
        refund_request.approved_by = request.user
        refund_request.reviewed_at = timezone.now()
        refund_request.internal_note = request.POST.get('internal_note', refund_request.internal_note).strip()
        refund_request.save()

        previous_status = order.order_status
        order.order_status = 'cancelled'
        order.save(update_fields=['order_status', 'updated_at'])
        _cancel_outstanding_balance_payments(order)
        _create_order_status_notification(order, order_type, previous_status)
        _create_refund_status_notification(refund_request)
        _log_staff_activity(
            request.user,
            'refund_approved',
            f'Approved refund request #{refund_request.id} for {_get_order_label(order)} #{order.id}.',
            'refund_request',
            refund_request.id,
        )
        messages.success(request, f'Refund request #{refund_request.id} approved successfully.')
    elif action == 'reject':
        refund_request.status = 'rejected'
        refund_request.approved_by = request.user
        refund_request.reviewed_at = timezone.now()
        refund_request.internal_note = request.POST.get('internal_note', refund_request.internal_note).strip()
        refund_request.save()
        _create_refund_status_notification(refund_request)
        _log_staff_activity(
            request.user,
            'refund_rejected',
            f'Rejected refund request #{refund_request.id}.',
            'refund_request',
            refund_request.id,
        )
        messages.success(request, f'Refund request #{refund_request.id} rejected successfully.')
    elif action == 'process':
        if refund_request.status not in ['approved', 'processing']:
            messages.error(request, 'Only approved refunds can be processed.')
            return redirect('admin_refunds')

        refund_request.status = 'processed'
        refund_request.processed_by = request.user
        refund_request.processed_at = timezone.now()
        refund_request.refund_reference_number = request.POST.get('refund_reference_number', '').strip()
        refund_request.internal_note = request.POST.get('internal_note', refund_request.internal_note).strip()
        refund_request.save()
        _create_refund_status_notification(refund_request)
        _log_staff_activity(
            request.user,
            'refund_processed',
            f'Processed refund request #{refund_request.id}.',
            'refund_request',
            refund_request.id,
        )
        messages.success(request, f'Refund request #{refund_request.id} processed successfully.')

    return redirect('admin_refunds')


@login_required
def admin_activity_logs(request):
    """List recorded staff audit trail entries"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    activity_logs = ActivityLog.objects.select_related('actor').all()[:100]
    return render(request, 'admin/activity_logs.html', {
        'activity_logs': activity_logs,
        'admin_menu': get_admin_menu(request),
    })


@login_required
@require_POST
def admin_activity_log_delete(request, log_id):
    """Delete an audit trail entry from the admin panel"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    activity_log = get_object_or_404(ActivityLog, id=log_id)
    activity_log.delete()
    messages.success(request, 'Audit trail entry deleted successfully!')
    return redirect('admin_activity_logs')


# ============================================
# ADMIN USERS (Role Management)
# ============================================

@login_required
def admin_users(request):
    """List all users"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    users = User.objects.all().order_by('-date_joined')
    return render(request, 'admin/users/list.html', {
        'users': users,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_user_add(request):
    """Create a customer or staff account from the admin panel."""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        address = (request.POST.get('address') or '').strip()
        role_value = request.POST.get('role') or 'customer'

        if role_value not in dict(ROLE_CHOICES):
            messages.error(request, 'Please choose a valid role.')
        elif not username:
            messages.error(request, 'Username is required.')
        elif not email:
            messages.error(request, 'Email is required.')
        elif password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        elif len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
        else:
            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            _assign_user_role(new_user, role_value, phone=phone, address=address)

            _log_staff_activity(
                request.user,
                'user_created',
                f'Created user "{new_user.username}" with role {role_value}.',
                'user',
                new_user.id,
            )

            messages.success(request, f'User "{new_user.username}" created successfully!')
            return redirect('admin_users')

    return render(request, 'admin/users/add.html', {
        'role_choices': ROLE_CHOICES,
        'admin_menu': get_admin_menu(request),
    })


@login_required
def admin_user_edit(request, user_id):
    """Edit user profile"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    edit_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        edit_user.first_name = request.POST.get('first_name')
        edit_user.last_name = request.POST.get('last_name')
        edit_user.email = request.POST.get('email')
        edit_user.save()

        if hasattr(edit_user, 'profile'):
            edit_user.profile.phone = request.POST.get('phone')
            edit_user.profile.address = request.POST.get('address')
            edit_user.profile.save()

        _log_staff_activity(
            request.user,
            'user_updated',
            f'Updated user "{edit_user.username}".',
            'user',
            edit_user.id,
        )

        messages.success(
            request, f'User "{edit_user.username}" updated successfully!')
        return redirect('admin_users')

    return render(request, 'admin/users/edit.html', {
        'edit_user': edit_user,
        'admin_menu': get_admin_menu(request)
    })


@login_required
@require_POST
def admin_user_delete(request, user_id):
    """Delete a user from the admin panel"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    delete_user = get_object_or_404(User, id=user_id)

    if delete_user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('admin_users')

    username = delete_user.username
    delete_user.delete()
    _log_staff_activity(
        request.user,
        'user_deleted',
        f'Deleted user "{username}".',
        'user',
        user_id,
    )
    messages.success(request, f'User "{username}" deleted successfully!')
    return redirect('admin_users')


@login_required
def admin_user_role(request, user_id):
    """Change user role"""
    access_denied = _require_admin_roles(request, {'owner', 'admin'})
    if access_denied:
        return access_denied

    edit_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        new_role = request.POST.get('role')
        if new_role not in dict(ROLE_CHOICES):
            messages.error(request, 'Please choose a valid role.')
            return redirect('admin_user_role', user_id=user_id)

        _assign_user_role(
            edit_user,
            new_role,
            phone=getattr(getattr(edit_user, 'profile', None), 'phone', ''),
            address=getattr(getattr(edit_user, 'profile', None), 'address', ''),
        )

        _log_staff_activity(
            request.user,
            'user_role_updated',
            f'Changed role for user "{edit_user.username}" to {new_role}.',
            'user',
            edit_user.id,
        )

        messages.success(
            request, f'User "{edit_user.username}" role updated to {new_role}')
        return redirect('admin_users')

    return render(request, 'admin/users/role.html', {
        'edit_user': edit_user,
        'role_choices': ROLE_CHOICES,
        'admin_menu': get_admin_menu(request)
    })


# ============================================
# ADMIN ORDER DETAIL (Combined View)
# ============================================

@login_required
def admin_order_detail(request, order_id, order_type):
    """View single order details (works for both cake and package orders)"""
    access_denied = _require_admin_roles(request, STAFF_ROLE_VALUES)
    if access_denied:
        return access_denied

    if order_type == 'cake':
        order = get_object_or_404(CakeOrder, id=order_id)
        template = 'admin/orders/cake_order_view.html'
    else:
        order = get_object_or_404(PackageOrder, id=order_id)
        template = 'admin/orders/package_order_view.html'

    context = {
        'order': order,
        'order_type': order_type,
        'admin_menu': get_admin_menu(request),
        'role_display': request.user.profile.get_role_display() if hasattr(request.user, 'profile') else 'Admin',
    }
    return render(request, template, context)


# ============================================
# CONTEXT PROCESSOR
# ============================================

def user_role_context(request):
    """Context processor for user role"""
    if request.user.is_authenticated:
        role = getattr(request.user, 'profile', None)
        return {
            'user_role': role.role if role else 'customer',
            'user_role_display': role.get_role_display() if role else 'Customer - Customer Portal',
        }
    return {}
