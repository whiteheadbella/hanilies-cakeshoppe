import json
import os
import signal
import subprocess
import sys

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.urls import reverse
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from .models import UserProfile, Cake, CakeOrder, CakeCustomization, Package, PackageOrder, Payment


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

CAKE_DECORATION_OPTIONS = {
    'fresh_flowers': {'label': 'Fresh Flowers', 'price': Decimal('300.00')},
    'edible_gold': {'label': 'Edible Gold Leaf', 'price': Decimal('500.00')},
    'cake_topper': {'label': 'Custom Cake Topper', 'price': Decimal('250.00')},
    'sprinkles': {'label': 'Edible Sprinkles', 'price': Decimal('100.00')},
    'fresh_fruits': {'label': 'Fresh Fruit Toppings', 'price': Decimal('200.00')},
}

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


def _parse_decimal(value, default='0.00'):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


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


def _get_package_draft(request):
    return request.session.get(PACKAGE_ORDER_SESSION_KEY, {})


def _set_package_draft(request, draft):
    request.session[PACKAGE_ORDER_SESSION_KEY] = draft
    request.session.modified = True


def _clear_package_draft(request):
    if PACKAGE_ORDER_SESSION_KEY in request.session:
        del request.session[PACKAGE_ORDER_SESSION_KEY]
        request.session.modified = True


def _is_local_demo_request(request):
    remote_addr = request.META.get('REMOTE_ADDR')
    return settings.DEBUG and remote_addr in {None, '127.0.0.1', '::1'}


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


def _get_running_demo_state(request):
    state = _get_demo_state(request)
    if not state:
        return None
    if not _process_is_running(state.get('pid')):
        _clear_demo_state(request)
        return None
    return state


@require_POST
def start_demo_bot(request):
    if not _is_local_demo_request(request):
        return JsonResponse({
            'ok': False,
            'error': 'The demo bot launcher is only available from the local presentation machine.',
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
        'scenario': scenario,
        'pid': process.pid,
        'script_steps': script_steps,
        'message': f'{scenario.title()} demo started. Watch the automated browser window for the live walkthrough.',
    })


def demo_bot_status(request):
    if not _is_local_demo_request(request):
        return JsonResponse({'ok': False, 'error': 'Local access only.'}, status=403)

    state = _get_running_demo_state(request)
    if not state:
        return JsonResponse({'ok': True, 'running': False})

    return JsonResponse({'ok': True, 'running': True, 'active_demo': state})


@require_POST
def stop_demo_bot(request):
    if not _is_local_demo_request(request):
        return JsonResponse({'ok': False, 'error': 'Local access only.'}, status=403)

    state = _get_demo_state(request)
    if not state:
        return JsonResponse({
            'ok': False,
            'error': 'No running demo bot was found for this browser session.',
        }, status=404)

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
    packages = list(Package.objects.filter(status='active').annotate(
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
    featured_packages = list(Package.objects.filter(status='active').annotate(
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
    package_list = Package.objects.filter(status='active').order_by('name')
    selected_type = request.GET.get('type', '').strip()
    search_term = request.GET.get('q', '').strip()

    if selected_type:
        package_list = package_list.filter(package_type=selected_type)
    if search_term:
        package_list = package_list.filter(
            Q(name__icontains=search_term) | Q(description__icontains=search_term))

    context = {
        'packages': package_list,
        'package_types': Package.PACKAGE_TYPES,
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
                    UserProfile.objects.create(user=user, role='owner')
                else:
                    UserProfile.objects.create(user=user, role='viewer')

            # Check if user has admin role (for redirect)
            role = user.profile.role

            if user.is_superuser or role in ['owner', 'admin', 'manager', 'baker', 'packager', 'cashier']:
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
            role='viewer'
        )

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
        UserProfile.objects.create(user=request.user, role='viewer')

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
    context = {
        'order_count': cake_orders.count() + package_orders.count(),
        'total_spent': total_spent,
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
        email_notifications = request.POST.get('email_notifications') == 'on'
        promo_emails = request.POST.get('promo_emails') == 'on'
        sms_notifications = request.POST.get('sms_notifications') == 'on'

        request.session['email_notifications'] = email_notifications
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
    tracking_steps = []
    if selected_order is not None:
        selected_payment = selected_order.payments.order_by(
            '-created_at').first()
        tracking_steps = _build_tracking_steps(
            selected_type, selected_order.order_status)

    context = {
        'cake_orders': cake_orders,
        'package_orders': package_orders,
        'selected_order': selected_order,
        'selected_order_type': selected_type,
        'selected_payment': selected_payment,
        'tracking_steps': tracking_steps,
    }
    return render(request, 'hanilies/order_tracking.html', context)


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
        reference_number = request.POST.get('reference_number', '').strip()
        proof_image = request.FILES.get('proof_image')

        if payment_method == 'gcash' and (not reference_number or proof_image is None):
            messages.error(
                request, 'GCash orders require a reference number and proof of payment.')
        else:
            cake_order = CakeOrder.objects.create(
                user=request.user,
                cake=selected_cake,
                quantity=quantity,
                total_price=total_price,
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

            Payment.objects.create(
                amount=total_price,
                payment_method=payment_method,
                payment_status='verifying' if payment_method == 'gcash' else 'pending',
                cake_order=cake_order,
                reference_number=reference_number,
                proof_image=proof_image,
            )
            messages.success(
                request, f'Cake order #{cake_order.id} was placed successfully.')
            return redirect(f"{reverse('order_tracking')}?type=cake&id={cake_order.id}")

    context = {
        'cake': selected_cake,
        'cakes': cake_queryset.order_by('name'),
        'decoration_options': CAKE_DECORATION_OPTIONS,
        'defaults': defaults,
    }
    return render(request, 'hanilies/cake_customize.html', context)


@login_required
def package_order(request):
    """Order a package"""
    draft = _get_package_draft(request)
    selected_package_id = request.POST.get('package_id') if request.method == 'POST' else request.GET.get(
        'package_id') or request.GET.get('package') or draft.get('package_id')
    package_queryset = Package.objects.filter(status='active')

    if not package_queryset.exists():
        messages.error(
            request, 'No active packages are available yet. Please add packages from the admin panel first.')
        return redirect('packages')

    selected_package = get_object_or_404(package_queryset, id=selected_package_id) if selected_package_id and str(
        selected_package_id).isdigit() else package_queryset.order_by('name').first()

    if request.method == 'POST':
        selected_addons = request.POST.getlist('selected_addons')
        addon_labels, addon_total = _get_selected_option_labels(
            selected_addons, PACKAGE_ADDON_OPTIONS)
        updated_draft = {
            'package_id': str(selected_package.id),
            'event_type': request.POST.get('event_type', selected_package.package_type),
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
        'event_types': PackageOrder.EVENT_TYPES,
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

    selected_package = get_object_or_404(
        Package, id=package_id, status='active')

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

    selected_package = get_object_or_404(
        Package, id=package_id, status='active')
    defaults = _get_profile_defaults(request.user)
    subtotal = _parse_decimal(
        draft.get('base_total', selected_package.base_price))
    custom_total = _parse_decimal(draft.get('cake_custom_total', '0.00'))
    grand_total = subtotal + custom_total

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'cod')
        reference_number = request.POST.get('reference_number', '').strip()
        proof_image = request.FILES.get('proof_image')

        if payment_method == 'gcash' and (not reference_number or proof_image is None):
            messages.error(
                request, 'GCash package orders require a reference number and proof of payment.')
        else:
            package_order = PackageOrder.objects.create(
                user=request.user,
                package=selected_package,
                total_price=grand_total,
                event_type=request.POST.get('event_type', draft.get(
                    'event_type', selected_package.package_type)),
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

            Payment.objects.create(
                amount=grand_total,
                payment_method=payment_method,
                payment_status='verifying' if payment_method == 'gcash' else 'pending',
                package_order=package_order,
                reference_number=reference_number,
                proof_image=proof_image,
            )

            _clear_package_draft(request)
            messages.success(
                request, f'Package order #{package_order.id} was placed successfully.')
            return redirect(f"{reverse('order_tracking')}?type=package&id={package_order.id}")

    context = {
        'package': selected_package,
        'draft': draft,
        'defaults': defaults,
        'subtotal': subtotal,
        'custom_total': custom_total,
        'grand_total': grand_total,
    }
    return render(request, 'hanilies/package_payment.html', context)


# ============================================
# ADMIN HELPER FUNCTIONS
# ============================================

def get_admin_menu(request):
    """Generate admin sidebar menu - all items shown to admin users"""
    menu = [
        {'name': 'Dashboard', 'url': 'admin_dashboard', 'icon': 'tachometer-alt'},
        {'name': 'Cakes', 'url': 'admin_cakes', 'icon': 'birthday-cake'},
        {'name': 'Cake Orders', 'url': 'admin_cake_orders', 'icon': 'shopping-cart'},
        {'name': 'Packages', 'url': 'admin_packages', 'icon': 'gift'},
        {'name': 'Package Orders', 'url': 'admin_package_orders',
            'icon': 'calendar-check'},
        {'name': 'Payments', 'url': 'admin_payments', 'icon': 'credit-card'},
        {'name': 'Users', 'url': 'admin_users', 'icon': 'users'},
    ]
    return menu


def is_admin_user(user):
    """Check if user has admin access"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if hasattr(user, 'profile'):
        return user.profile.role in ['owner', 'admin', 'manager', 'baker', 'packager', 'cashier']
    return False


# ============================================
# ADMIN DASHBOARD
# ============================================

@login_required
def admin_dashboard(request):
    """Admin dashboard with statistics"""
    if not is_admin_user(request.user):
        messages.error(
            request, 'You do not have permission to access the admin panel.')
        return redirect('home')

    if not hasattr(request.user, 'profile'):
        if request.user.is_superuser:
            UserProfile.objects.create(user=request.user, role='owner')
        else:
            UserProfile.objects.create(user=request.user, role='viewer')

    role = getattr(request.user, 'profile', None)
    admin_menu = get_admin_menu(request)

    context = {
        'admin_menu': admin_menu,
        'role': role.role if role else 'admin',
        'role_display': role.get_role_display() if role else 'Administrator',
        'total_cakes': Cake.objects.filter(is_active=True).count(),
        'total_cake_orders': CakeOrder.objects.count(),
        'total_packages': Package.objects.filter(status='active').count(),
        'total_package_orders': PackageOrder.objects.count(),
        'total_users': User.objects.filter(is_active=True).count(),
        'pending_payments': Payment.objects.filter(payment_status='pending').count(),
        'recent_cake_orders': CakeOrder.objects.all().order_by('-created_at')[:5],
        'recent_package_orders': PackageOrder.objects.all().order_by('-created_at')[:5],
        'now': datetime.now(),  # Add current date and time
    }

    return render(request, 'admin/dashboard.html', context)

# ============================================
# ADMIN CAKES
# ============================================


@login_required
def admin_cakes(request):
    """List all cakes"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    cakes = Cake.objects.all().order_by('-created_at')
    return render(request, 'admin/cakes/list.html', {
        'cakes': cakes,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_add(request):
    """Add a new cake with image upload"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name')
            category = request.POST.get('category')
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
            messages.success(
                request, f'Cake "{cake.name}" added successfully!')
            return redirect('admin_cakes')

        except Exception as e:
            messages.error(request, f'Error adding cake: {str(e)}')
            return redirect('admin_cake_add')

    return render(request, 'admin/cakes/add.html', {'admin_menu': get_admin_menu(request)})


@login_required
def admin_cake_edit(request, cake_id):
    """Edit a cake with image upload"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    cake = get_object_or_404(Cake, id=cake_id)

    if request.method == 'POST':
        try:
            # Update basic info
            cake.name = request.POST.get('name')
            cake.category = request.POST.get('category')
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
            messages.success(
                request, f'Cake "{cake.name}" updated successfully!')
            return redirect('admin_cakes')

        except Exception as e:
            messages.error(request, f'Error updating cake: {str(e)}')
            return redirect('admin_cake_edit', cake_id=cake_id)

    return render(request, 'admin/cakes/edit.html', {
        'cake': cake,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_delete(request, cake_id):
    """Delete a cake"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    cake = get_object_or_404(Cake, id=cake_id)
    cake.delete()
    messages.success(request, f'Cake "{cake.name}" deleted successfully!')
    return redirect('admin_cakes')


# ============================================
# ADMIN CAKE ORDERS
# ============================================

@login_required
def admin_cake_orders(request):
    """List all cake orders"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    orders = CakeOrder.objects.all().order_by('-created_at')
    return render(request, 'admin/orders/cake_orders.html', {
        'orders': orders,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_view(request, order_id):
    """View order details"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    order = get_object_or_404(CakeOrder, id=order_id)
    return render(request, 'admin/orders/cake_order_view.html', {
        'order': order,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_update(request, order_id):
    """Update order status"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        order = get_object_or_404(CakeOrder, id=order_id)
        order.order_status = request.POST.get('status')
        order.save()
        messages.success(
            request, f'Order #{order.id} status updated to {order.get_order_status_display()}')
    return redirect('admin_cake_orders')


# ============================================
# ADMIN PACKAGES
# ============================================

@login_required
def admin_packages(request):
    """List all packages"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    packages = Package.objects.all().order_by('-created_at')
    return render(request, 'admin/packages/list.html', {
        'packages': packages,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_add(request):
    """Add a new package"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        try:
            package = Package(
                name=request.POST.get('name'),
                package_type=request.POST.get('package_type'),
                description=request.POST.get('description'),
                base_price=request.POST.get('base_price'),
                status=request.POST.get('status', 'active'),
                features=request.POST.get('features', '')  # Add features
            )
            package.save()
            messages.success(
                request, f'Package "{package.name}" added successfully!')
            return redirect('admin_packages')
        except Exception as e:
            messages.error(request, f'Error adding package: {str(e)}')

    return render(request, 'admin/packages/add.html', {'admin_menu': get_admin_menu(request)})


@login_required
def admin_package_edit(request, package_id):
    """Edit a package"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)

    if request.method == 'POST':
        try:
            package.name = request.POST.get('name')
            package.package_type = request.POST.get('package_type')
            package.description = request.POST.get('description')
            package.base_price = request.POST.get('base_price')
            package.status = request.POST.get('status')
            package.features = request.POST.get(
                'features', '')  # Update features
            package.save()
            messages.success(
                request, f'Package "{package.name}" updated successfully!')
            return redirect('admin_packages')
        except Exception as e:
            messages.error(request, f'Error updating package: {str(e)}')

    return render(request, 'admin/packages/edit.html', {
        'package': package,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_delete(request, package_id):
    """Delete a package"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    package = get_object_or_404(Package, id=package_id)
    package_name = package.name
    package.delete()
    messages.success(
        request, f'Package "{package_name}" deleted successfully!')
    return redirect('admin_packages')


# ============================================
# ADMIN PACKAGE ORDERS
# ============================================

@login_required
def admin_package_orders(request):
    """List all package orders"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    orders = PackageOrder.objects.all().order_by('-created_at')
    return render(request, 'admin/orders/package_orders.html', {
        'orders': orders,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_view(request, order_id):
    """View package order details"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    order = get_object_or_404(PackageOrder, id=order_id)
    return render(request, 'admin/orders/package_order_view.html', {
        'order': order,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_update(request, order_id):
    """Update package order status"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        order = get_object_or_404(PackageOrder, id=order_id)
        order.order_status = request.POST.get('status')
        order.save()
        messages.success(
            request, f'Package Order #{order.id} status updated to {order.get_order_status_display()}')
    return redirect('admin_package_orders')


# ============================================
# ADMIN PAYMENTS
# ============================================

@login_required
def admin_payments(request):
    """List all payments"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    # Get all payments
    payments = Payment.objects.all().order_by('-created_at')

    # Categorize payments
    pending_payments = payments.filter(payment_status='pending')
    verified_payments = payments.filter(payment_status='paid')
    rejected_payments = payments.filter(payment_status='failed')

    return render(request, 'admin/payments/list.html', {
        'payments': payments,
        'pending_payments': pending_payments,
        'verified_payments': verified_payments,
        'rejected_payments': rejected_payments,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_payment_verify(request, payment_id):
    """Verify/Approve/Reject a payment"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    payment = get_object_or_404(Payment, id=payment_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
            payment.payment_status = 'paid'
            payment.paid_at = timezone.now()
            messages.success(
                request, f'Payment #{payment.id} has been approved!')
        elif action == 'reject':
            payment.payment_status = 'failed'
            messages.warning(
                request, f'Payment #{payment.id} has been rejected.')
        else:
            payment.payment_status = 'verifying'
            messages.info(
                request, f'Payment #{payment.id} is under verification.')

        payment.save()

    return redirect('admin_payments')


# ============================================
# ADMIN USERS (Role Management)
# ============================================

@login_required
def admin_users(request):
    """List all users"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    users = User.objects.all().order_by('-date_joined')
    return render(request, 'admin/users/list.html', {
        'users': users,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_user_edit(request, user_id):
    """Edit user profile"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

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

        messages.success(
            request, f'User "{edit_user.username}" updated successfully!')
        return redirect('admin_users')

    return render(request, 'admin/users/edit.html', {
        'edit_user': edit_user,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_user_role(request, user_id):
    """Change user role"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

    edit_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        new_role = request.POST.get('role')
        if hasattr(edit_user, 'profile'):
            edit_user.profile.role = new_role
            edit_user.profile.save()
        else:
            UserProfile.objects.create(user=edit_user, role=new_role)

        messages.success(
            request, f'User "{edit_user.username}" role updated to {new_role}')
        return redirect('admin_users')

    return render(request, 'admin/users/role.html', {
        'edit_user': edit_user,
        'admin_menu': get_admin_menu(request)
    })


# ============================================
# ADMIN ORDER DETAIL (Combined View)
# ============================================

@login_required
def admin_order_detail(request, order_id, order_type):
    """View single order details (works for both cake and package orders)"""
    if not is_admin_user(request.user):
        messages.error(request, 'Permission denied')
        return redirect('admin_dashboard')

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
            'user_role': role.role if role else 'viewer',
            'user_role_display': role.get_role_display() if role else 'Viewer - Read Only',
        }
    return {}
