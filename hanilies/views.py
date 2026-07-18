import json
import os
import re
import csv
import hashlib
import time
from urllib.parse import urlencode
from io import BytesIO

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetDoneView, PasswordResetView
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.urls import reverse, reverse_lazy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum, Count, Q, OuterRef, Subquery, DateTimeField, F, Prefetch
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError
from .forms import (
    CakeBookingDateForm,
    AdminContactInquiryReplyForm,
    ContactInquiryForm,
    HaniliesPasswordResetForm,
    HaniliesSetPasswordForm,
    PackageBookingDateForm,
    build_cake_booking_window,
    build_package_booking_window,
)
from .models import HomeHeroImage, HomeStripImage, UserProfile, Notification, AboutPageImage, Cake, CakeOrder, CakeCustomization, Package, PackageOrder, PackageThumbnail, Payment, RefundRequest, ActivityLog, Testimonial, ContactInquiry
from .payment_qr import build_gcash_checkout_details, get_gcash_profile


PACKAGE_ORDER_SESSION_KEY = 'package_order_draft'
CHECKOUT_META_SESSION_KEY = 'checkout_payment_meta'
DEMO_SCENARIOS = {'customer', 'admin', 'full', 'custom'}
DEMO_SCRIPT_STEPS = [
    ('intro', 'Introduction'),
    ('register', 'Customer Registration'),
    ('customer_login', 'Customer Login'),
    ('homepage', 'Homepage Walkthrough'),
    ('cake_browse', 'Cake Ordering'),
    ('cake_customize', 'Customize Your Cake'),
    ('package_browse', 'Package Ordering'),
    ('package_customize', 'Customize Your Package Cake'),
    ('cart_review', 'Shopping Cart Review'),
    ('checkout', 'Checkout'),
    ('payment', 'Simulated Payment'),
    ('customer_orders', 'Customer Order Confirmation'),
    ('admin_login', 'Administrator Login'),
    ('admin_dashboard', 'Administrator Dashboard'),
    ('admin_cake_orders', 'Cake Order Management'),
    ('admin_package_orders', 'Package Order Management'),
    ('admin_payments', 'Payment Verification'),
    ('admin_cakes', 'Cake Management'),
    ('admin_packages', 'Package Management'),
    ('admin_users', 'User Management'),
    ('audit_trail', 'Audit Trail'),
    ('admin_logout', 'Administrator Logout'),
]
DEMO_SESSION_STATE_KEY = 'active_demo_bot'
DEMO_BROWSER_ADMIN_USERNAME = os.environ.get('DEMO_BOT_ADMIN_USERNAME', 'paneladmin')
DEMO_BROWSER_ADMIN_PASSWORD = os.environ.get('DEMO_BOT_ADMIN_PASSWORD', 'PanelAdmin123!')
DEMO_BROWSER_ADMIN_EMAIL = os.environ.get('DEMO_BOT_ADMIN_EMAIL', 'paneladmin@example.com')
DEMO_BROWSER_SCENARIO_STEPS = {
    'customer': ['intro', 'register', 'customer_login', 'homepage', 'cake_browse', 'cake_customize', 'package_browse', 'package_customize', 'cart_review', 'checkout', 'payment', 'customer_orders'],
    'admin': ['admin_login', 'admin_dashboard', 'admin_cake_orders', 'admin_package_orders', 'admin_payments', 'admin_cakes', 'admin_packages', 'admin_users', 'audit_trail', 'admin_logout'],
    'full': ['intro', 'register', 'customer_login', 'homepage', 'cake_browse', 'cake_customize', 'package_browse', 'package_customize', 'cart_review', 'checkout', 'payment', 'customer_orders', 'admin_login', 'admin_dashboard', 'admin_cake_orders', 'admin_package_orders', 'admin_payments', 'admin_cakes', 'admin_packages', 'admin_users', 'audit_trail', 'admin_logout'],
}
DEMO_BOT_DEFAULT_INTRO = 'Welcome to Hanilies Cakeshoppe. This guided demo will walk through the customer ordering journey and the administrator monitoring workflow.'

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

CAKE_THEME_OPTIONS_BY_CATEGORY = {
    value: [label] for value, label in Cake.CAKE_CATEGORIES
}

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


def _get_cake_theme_options_for_category(category_value):
    return list(CAKE_THEME_OPTIONS_BY_CATEGORY.get(category_value, CAKE_THEME_OPTIONS))


CAKE_CUSTOMIZATION_GROUP_SPECS = [
    {'key': 'sizes', 'label': 'Cake Tier Options',
        'item_label': 'Tier Option', 'input_type': 'select'},
    {'key': 'cake_sizes', 'label': 'Cake Size Options',
        'item_label': 'Cake Size', 'input_type': 'select'},
    {'key': 'flavors', 'label': 'Flavors',
        'item_label': 'Flavor', 'input_type': 'select'},
    {'key': 'shapes', 'label': 'Shapes',
        'item_label': 'Shape', 'input_type': 'select'},
    {'key': 'frostings', 'label': 'Frosting',
        'item_label': 'Frosting', 'input_type': 'select'},
    {'key': 'fillings', 'label': 'Fillings',
        'item_label': 'Filling', 'input_type': 'select'},
    {'key': 'decorations', 'label': 'Decorations',
        'item_label': 'Decoration', 'input_type': 'checkbox'},
]

PACKAGE_CUSTOMIZATION_GROUP_SPECS = [
    {'key': 'addons', 'label': 'Package Add-ons',
        'item_label': 'Add-on', 'input_type': 'checkbox'},
    {'key': 'cake_sizes', 'label': 'Cake Size Upgrades',
        'item_label': 'Cake Size', 'input_type': 'select'},
    {'key': 'cake_shapes', 'label': 'Cake Shapes',
        'item_label': 'Cake Shape', 'input_type': 'select'},
    {'key': 'cake_flavors', 'label': 'Cake Flavors',
        'item_label': 'Cake Flavor', 'input_type': 'select'},
    {'key': 'cake_frostings', 'label': 'Cake Frosting',
        'item_label': 'Cake Frosting', 'input_type': 'select'},
    {'key': 'cake_fillings', 'label': 'Cake Fillings',
        'item_label': 'Cake Filling', 'input_type': 'select'},
    {'key': 'cake_decorations', 'label': 'Cake Decorations',
        'item_label': 'Cake Decoration', 'input_type': 'checkbox'},
]

DEFAULT_CAKE_CUSTOMIZATION_OPTIONS = {
    'flavors': [
        {'label': 'Chocolate', 'price': '0.00'},
        {'label': 'Vanilla', 'price': '0.00'},
        {'label': 'Red Velvet', 'price': '0.00'},
        {'label': 'Ube', 'price': '0.00'},
        {'label': 'Mocha', 'price': '0.00'},
        {'label': 'Strawberry', 'price': '0.00'},
    ],
    'sizes': [
        {'label': '1 Tier', 'price': '0.00'},
        {'label': '2 Tier', 'price': '0.00'},
        {'label': '3 Tier', 'price': '0.00'},
        {'label': '4 Tier', 'price': '0.00'},
        {'label': '5 Tier', 'price': '0.00'},
    ],
    'cake_sizes': [
        {'label': '6 Inches', 'price': '10.00'},
        {'label': '8 Inches', 'price': '20.00'},
        {'label': '10 Inches', 'price': '30.00'},
        {'label': '12 Inches', 'price': '50.00'},
    ],
    'shapes': [
        {'label': 'Round', 'price': '0.00'},
        {'label': 'Square', 'price': '0.00'},
        {'label': 'Heart', 'price': '0.00'},
        {'label': 'Custom', 'price': '0.00'},
    ],
    'frostings': [
        {'label': 'Buttercream', 'price': '0.00'},
        {'label': 'Cream Cheese', 'price': '0.00'},
        {'label': 'Ganache', 'price': '0.00'},
        {'label': 'Fondant', 'price': '0.00'},
    ],
    'fillings': [
        {'label': 'Chocolate Ganache', 'price': '0.00'},
        {'label': 'Strawberry Jam', 'price': '0.00'},
        {'label': 'Cookies and Cream', 'price': '0.00'},
        {'label': 'Mango', 'price': '0.00'},
    ],
    'decorations': [
        {'key': 'fresh_flowers', 'label': 'Fresh Flowers', 'price': '300.00'},
        {'key': 'edible_gold', 'label': 'Edible Gold Leaf', 'price': '500.00'},
        {'key': 'cake_topper', 'label': 'Custom Cake Topper', 'price': '250.00'},
        {'key': 'sprinkles', 'label': 'Edible Sprinkles', 'price': '100.00'},
        {'key': 'fresh_fruits', 'label': 'Fresh Fruit Toppings', 'price': '200.00'},
    ],
}

LEGACY_CAKE_SIZE_TIER_LABELS = {
    item['label'].strip().lower()
    for item in DEFAULT_CAKE_CUSTOMIZATION_OPTIONS['sizes']
}

ABOUT_PAGE_IMAGE_DEFAULTS = {
    AboutPageImage.SLOT_STORY: {
        'title': 'Our Story',
        'image_url': '/static/images/cake1.jpg',
    },
    AboutPageImage.SLOT_TEAM_TERESA: {
        'title': 'Teresa Rabillas',
        'image_url': '/static/images/cake1.jpg',
    },
    AboutPageImage.SLOT_TEAM_MARIA: {
        'title': 'Maria Santos',
        'image_url': '/static/images/cake2.jpg',
    },
    AboutPageImage.SLOT_TEAM_JOHN: {
        'title': 'John Reyes',
        'image_url': '/static/images/cake3.jpg',
    },
    AboutPageImage.SLOT_TEAM_ANNA: {
        'title': 'Anna Lim',
        'image_url': '/static/images/cake1.jpg',
    },
}

ABOUT_PAGE_IMAGE_SLOT_DETAILS = [
    {
        'slot': AboutPageImage.SLOT_STORY,
        'title': 'Our Story',
        'usage': 'Large image beside the Our Story text block.',
    },
    {
        'slot': AboutPageImage.SLOT_TEAM_TERESA,
        'title': 'Teresa Rabillas',
        'usage': 'Team card image for the founder.',
    },
    {
        'slot': AboutPageImage.SLOT_TEAM_MARIA,
        'title': 'Maria Santos',
        'usage': 'Team card image for the head baker.',
    },
    {
        'slot': AboutPageImage.SLOT_TEAM_JOHN,
        'title': 'John Reyes',
        'usage': 'Team card image for the sales manager.',
    },
    {
        'slot': AboutPageImage.SLOT_TEAM_ANNA,
        'title': 'Anna Lim',
        'usage': 'Team card image for the customer service lead.',
    },
]

DEFAULT_PACKAGE_CUSTOMIZATION_OPTIONS = {
    'addons': [
        {'key': 'brownies', 'label': 'Chocofudge Brownies', 'price': '300.00'},
        {'key': 'cupcakes', 'label': 'Themed Cupcakes', 'price': '350.00'},
        {'key': 'cookies', 'label': 'Chocochip Cookies', 'price': '250.00'},
        {'key': 'marshmallow', 'label': 'Marshmallow on Stick', 'price': '200.00'},
        {'key': 'cake_pop', 'label': 'Cake Pop', 'price': '250.00'},
        {'key': 'gummies', 'label': 'Assorted Gummies', 'price': '150.00'},
        {'key': 'wafer', 'label': 'Wafer Sticks', 'price': '180.00'},
        {'key': 'chocolate_fountain', 'label': 'Chocolate Fountain', 'price': '1500.00'},
        {'key': 'lolli_balloon', 'label': 'Lolli Balloon with Print', 'price': '50.00'},
        {'key': 'pillar_balloon', 'label': 'Pillar Balloon', 'price': '100.00'},
        {'key': 'centerpiece', 'label': 'Centerpiece Balloon', 'price': '150.00'},
    ],
    'cake_sizes': [
        {'value': 'standard', 'label': 'Standard package cake size', 'price': '0.00'},
        {'value': 'upgrade_10', 'label': 'Upgrade to 10 inches', 'price': '500.00'},
        {'value': 'upgrade_12', 'label': 'Upgrade to 12 inches', 'price': '900.00'},
        {'value': 'extra_layer', 'label': 'Add extra layer', 'price': '1500.00'},
    ],
    'cake_shapes': [
        {'label': 'Round', 'price': '0.00'},
        {'label': 'Square', 'price': '0.00'},
        {'label': 'Heart', 'price': '0.00'},
        {'label': 'Custom', 'price': '0.00'},
    ],
    'cake_flavors': [
        {'label': 'Chocolate', 'price': '0.00'},
        {'label': 'Vanilla', 'price': '0.00'},
        {'label': 'Red Velvet', 'price': '0.00'},
        {'label': 'Ube', 'price': '0.00'},
        {'label': 'Mocha', 'price': '0.00'},
        {'label': 'Strawberry', 'price': '0.00'},
    ],
    'cake_frostings': [
        {'label': 'Buttercream', 'price': '0.00'},
        {'label': 'Cream Cheese', 'price': '0.00'},
        {'label': 'Ganache', 'price': '0.00'},
        {'label': 'Fondant', 'price': '0.00'},
    ],
    'cake_fillings': [
        {'label': 'Chocolate Ganache', 'price': '0.00'},
        {'label': 'Strawberry Jam', 'price': '0.00'},
        {'label': 'Cookies and Cream', 'price': '0.00'},
        {'label': 'Mango', 'price': '0.00'},
    ],
    'cake_decorations': [
        {'key': 'edible_gold', 'label': 'Edible Gold Leaf', 'price': '500.00'},
        {'key': 'fresh_flowers', 'label': 'Fresh Flowers', 'price': '300.00'},
        {'key': 'custom_topper', 'label': 'Custom Cake Topper', 'price': '250.00'},
        {'key': 'sprinkles', 'label': 'Edible Sprinkles', 'price': '100.00'},
        {'key': 'fresh_fruits', 'label': 'Fresh Fruit Toppings', 'price': '200.00'},
    ],
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
    'sprinkles': {'label': 'Edible Sprinkles', 'price': Decimal('100.00')},
    'fresh_fruits': {'label': 'Fresh Fruit Toppings', 'price': Decimal('200.00')},
}

ORDER_STATUS_NOTIFICATION_CONFIG = {
    'cake': {
        'payment_retry': {
            'headline': 'Your payment proof was rejected. Please resubmit a valid payment receipt to continue your cake order.',
            'subject': 'Cake order awaiting payment resubmission',
        },
        'confirmed': {
            'headline': 'Your cake order has been confirmed.',
            'subject': 'Cake order confirmed',
        },
        'preparing': {
            'headline': 'Your cake is now being prepared.',
            'subject': 'Cake order now preparing',
        },
        'ready_for_pickup': {
            'headline': 'Your cake order is ready for pickup.',
            'subject': 'Cake order ready for pickup',
        },
        'out_for_delivery': {
            'headline': 'Your cake order is out for delivery.',
            'subject': 'Cake order out for delivery',
        },
        'completed': {
            'headline': 'Your cake order has been completed.',
            'subject': 'Cake order completed',
        },
    },
    'package': {
        'payment_retry': {
            'headline': 'Your payment proof was rejected. Please resubmit a valid payment receipt to continue your package booking.',
            'subject': 'Package booking awaiting payment resubmission',
        },
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
        'out_for_delivery': {
            'headline': 'Your package booking is out for delivery.',
            'subject': 'Package booking out for delivery',
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
    'rejected': {
        'headline': 'Your payment was rejected. Please review the payment details and upload a new proof of payment.',
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
FULL_ACCESS_ROLE_VALUES = {'owner', 'admin', 'manager', 'supervisor'}
STAFF_ROLE_VALUES = {'owner', 'admin', 'manager',
                     'supervisor', 'baker', 'packager', 'cashier'}
HOME_HERO_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES
USER_MANAGEMENT_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES
AUDIT_TRAIL_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES
PAYMENT_REVIEW_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES | {'cashier'}
CAKE_PRODUCT_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES | {'cashier', 'baker'}
PACKAGE_PRODUCT_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES | {'cashier', 'packager'}
CAKE_ORDER_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES | {'cashier', 'baker'}
PACKAGE_ORDER_ROLE_VALUES = FULL_ACCESS_ROLE_VALUES | {'cashier', 'packager'}
SALES_REPORT_ROLE_VALUES = CAKE_ORDER_ROLE_VALUES | PACKAGE_ORDER_ROLE_VALUES | PAYMENT_REVIEW_ROLE_VALUES
STOCK_REPORT_ROLE_VALUES = CAKE_PRODUCT_ROLE_VALUES | PACKAGE_PRODUCT_ROLE_VALUES
LOW_STOCK_THRESHOLD = 5
PAYMENT_PLAN_LABELS = {
    'cod': '50% GCash Deposit + COD Balance',
    'gcash': 'Full GCash Payment',
}
DELIVERY_SERVICE_AREA_CHOICES = [
    ('Oroquieta City', 'Misamis Occidental'),
    ('Aloran', 'Misamis Occidental'),
    ('Baliangao', 'Misamis Occidental'),
    ('Bonifacio', 'Misamis Occidental'),
    ('Calamba', 'Misamis Occidental'),
    ('Clarin', 'Misamis Occidental'),
    ('Concepcion', 'Misamis Occidental'),
    ('Don Victoriano Chiongbian', 'Misamis Occidental'),
    ('Jimenez', 'Misamis Occidental'),
    ('Lopez Jaena', 'Misamis Occidental'),
    ('Ozamiz City', 'Misamis Occidental'),
    ('Panaon', 'Misamis Occidental'),
    ('Plaridel', 'Misamis Occidental'),
    ('Sapang Dalaga', 'Misamis Occidental'),
    ('Sinacaban', 'Misamis Occidental'),
    ('Tangub City', 'Misamis Occidental'),
    ('Lucena City', 'Quezon'),
]
DELIVERY_SERVICE_AREA_MAP = {
    city.lower(): {'city': city, 'province': province}
    for city, province in DELIVERY_SERVICE_AREA_CHOICES
}
PAYMENT_PROOF_MAX_BYTES = 5 * 1024 * 1024
PAYMENT_PROOF_ALLOWED_FORMATS = {'JPEG', 'PNG'}
PAYMENT_PROOF_ALLOWED_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
}
PAYMENT_PROOF_GENERIC_CONTENT_TYPES = {
    'application/octet-stream',
    'binary/octet-stream',
}
ADMIN_MENU_ITEMS = [
    {'name': 'Admin Dashboard', 'url': 'admin_dashboard',
        'icon': 'house', 'roles': STAFF_ROLE_VALUES, 'section': 'Dashboard'},
    {'name': 'Homepage Banner', 'url': 'admin_home_hero_images',
        'icon': 'images', 'roles': HOME_HERO_ROLE_VALUES, 'section': 'Content'},
    {'name': 'Promotional Banner', 'url': 'admin_home_strip_images',
        'icon': 'panorama', 'roles': HOME_HERO_ROLE_VALUES, 'section': 'Content'},
    {'name': 'About Images', 'url': 'admin_about_images',
        'icon': 'address-card', 'roles': HOME_HERO_ROLE_VALUES, 'section': 'Content'},
    {'name': 'Testimonials', 'url': 'admin_testimonials', 'icon': 'comments',
        'roles': FULL_ACCESS_ROLE_VALUES, 'section': 'Content'},
    {'name': 'Cake Products', 'url': 'admin_cakes', 'icon': 'birthday-cake',
        'roles': CAKE_PRODUCT_ROLE_VALUES, 'section': 'Products'},
    {'name': 'Package Products', 'url': 'admin_packages', 'icon': 'gift',
        'roles': PACKAGE_PRODUCT_ROLE_VALUES, 'section': 'Products'},
    {'name': 'Cake Orders', 'url': 'admin_cake_orders', 'icon': 'shopping-cart',
        'roles': CAKE_ORDER_ROLE_VALUES, 'section': 'Orders'},
    {'name': 'Package Orders', 'url': 'admin_package_orders', 'icon': 'calendar-check',
        'roles': PACKAGE_ORDER_ROLE_VALUES, 'section': 'Orders'},
    {'name': 'Payments', 'url': 'admin_payments', 'icon': 'credit-card',
        'roles': PAYMENT_REVIEW_ROLE_VALUES, 'section': 'Orders'},
    {'name': 'Refunds', 'url': 'admin_refunds', 'icon': 'rotate-left',
        'roles': PAYMENT_REVIEW_ROLE_VALUES, 'section': 'Orders'},
    {'name': 'Stock Report', 'url': 'admin_stock_report', 'icon': 'boxes-stacked',
        'roles': STOCK_REPORT_ROLE_VALUES, 'section': 'Inventory'},
    {'name': 'Order Sales Report', 'url': 'admin_order_sales_report', 'icon': 'chart-column',
        'roles': SALES_REPORT_ROLE_VALUES, 'section': 'Reports'},
    {'name': 'Users & Customers', 'url': 'admin_users', 'icon': 'users',
        'roles': USER_MANAGEMENT_ROLE_VALUES, 'section': 'Users'},
    {'name': 'Inquiries', 'url': 'admin_contact_inquiries', 'icon': 'envelope-open-text',
        'roles': FULL_ACCESS_ROLE_VALUES, 'section': 'Users'},
    {'name': 'Audit Trail', 'url': 'admin_activity_logs',
        'icon': 'clipboard-list', 'roles': AUDIT_TRAIL_ROLE_VALUES, 'section': 'System'},
]

ROLE_CHOICES = UserProfile.ROLE_CHOICES


def _parse_decimal(value, default='0.00'):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _quantize_amount(value):
    return _parse_decimal(value).quantize(Decimal('0.01'))


def _normalize_reference_number(reference_number):
    return re.sub(r'\s+', '', str(reference_number or '')).upper()


def _format_currency_label(value):
    return format(_quantize_amount(value), '.2f')


def _generate_checkout_nonce():
    return os.urandom(6).hex().upper()


def _build_generated_order_number(order_kind, nonce):
    prefix = 'CKO' if order_kind == 'cake' else 'PKO'
    return f'{prefix}-{timezone.localdate().strftime("%Y%m%d")}-{nonce}'


def _get_checkout_flow_key(order_kind, identifier):
    return f'{order_kind}:{identifier}'


def _get_checkout_meta_store(request):
    return request.session.get(CHECKOUT_META_SESSION_KEY, {})


def _set_checkout_meta_store(request, store):
    request.session[CHECKOUT_META_SESSION_KEY] = store
    request.session.modified = True


def _get_or_create_checkout_meta(request, flow_key, order_kind):
    store = _get_checkout_meta_store(request)
    meta = store.get(flow_key)
    if meta:
        return meta

    nonce = _generate_checkout_nonce()
    meta = {
        'order_kind': order_kind,
        'order_number': _build_generated_order_number(order_kind, nonce),
    }
    store[flow_key] = meta
    _set_checkout_meta_store(request, store)
    return meta


def _clear_checkout_meta(request, flow_key):
    store = _get_checkout_meta_store(request)
    if flow_key in store:
        del store[flow_key]
        _set_checkout_meta_store(request, store)


def _validate_checkout_payment_submission(reference_number, proof_image, expected_amount, submitted_amount=None, exclude_payment_id=None):
    normalized_reference = _normalize_reference_number(reference_number)
    submitted_amount_value = _quantize_amount(submitted_amount or '0.00')

    if not normalized_reference:
        return None, 'Please enter the GCash reference number from your receipt.'
    if proof_image is None:
        return None, 'Please upload a proof of payment image.'
    if submitted_amount_value != _quantize_amount(expected_amount):
        return None, 'Amount paid does not match the required amount.'

    reference_queryset = Payment.objects.filter(
        reference_number__iexact=normalized_reference,
    )
    if exclude_payment_id is not None:
        reference_queryset = reference_queryset.exclude(id=exclude_payment_id)
    if reference_queryset.exists():
        return None, 'This GCash reference number has already been used.'

    if getattr(proof_image, 'size', 0) > PAYMENT_PROOF_MAX_BYTES:
        return None, 'The uploaded payment proof must be 5 MB or smaller.'

    content_type = str(getattr(proof_image, 'content_type', '') or '').lower()
    if content_type and content_type not in PAYMENT_PROOF_ALLOWED_CONTENT_TYPES and content_type not in PAYMENT_PROOF_GENERIC_CONTENT_TYPES:
        return None, 'Only JPG, JPEG, and PNG files are allowed.'

    try:
        proof_image.seek(0)
        with Image.open(proof_image) as image:
            image.verify()
            image_format = (image.format or '').upper()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return None, 'Only JPG, JPEG, and PNG files are allowed.'
    finally:
        try:
            proof_image.seek(0)
        except (AttributeError, OSError, ValueError):
            pass

    if image_format not in PAYMENT_PROOF_ALLOWED_FORMATS:
        return None, 'Only JPG, JPEG, and PNG files are allowed.'

    return normalized_reference, None


def _validate_optional_design_reference_upload(uploaded_image):
    if uploaded_image is None:
        return None

    if getattr(uploaded_image, 'size', 0) > PAYMENT_PROOF_MAX_BYTES:
        return 'The uploaded design reference must be 5 MB or smaller.'

    content_type = str(
        getattr(uploaded_image, 'content_type', '') or '').lower()
    if content_type and content_type not in PAYMENT_PROOF_ALLOWED_CONTENT_TYPES and content_type not in PAYMENT_PROOF_GENERIC_CONTENT_TYPES:
        return 'Only JPG, JPEG, and PNG files are allowed for the design reference.'

    try:
        uploaded_image.seek(0)
        with Image.open(uploaded_image) as image:
            image.verify()
            image_format = (image.format or '').upper()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return 'Only JPG, JPEG, and PNG files are allowed for the design reference.'
    finally:
        try:
            uploaded_image.seek(0)
        except (AttributeError, OSError, ValueError):
            pass

    if image_format not in PAYMENT_PROOF_ALLOWED_FORMATS:
        return 'Only JPG, JPEG, and PNG files are allowed for the design reference.'

    return None


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


def _get_order_product_summary(order):
    if isinstance(order, CakeOrder):
        product = order.cake
    else:
        product = order.package

    if product is None:
        return ''

    product_name = str(getattr(product, 'name', '') or '').strip()
    product_code = str(getattr(product, 'product_code', '') or '').strip()
    summary_parts = []
    if product_name:
        summary_parts.append(product_name)
    if product_code:
        summary_parts.append(f'Code: {product_code}')

    if not summary_parts:
        return ''

    return f"Product: {' | '.join(summary_parts)}. "


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
        if order.order_status in ['ready_for_pickup', 'out_for_delivery', 'completed']:
            return {
                'allowed': False,
                'reason': 'Cake orders can no longer be cancelled once they are ready for pickup, out for delivery, or completed.',
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
        if order.order_status in ['ready_for_pickup', 'out_for_delivery', 'completed']:
            return {
                'allowed': False,
                'reason': 'Package orders can no longer be cancelled once they are ready for pickup, out for delivery, or completed.',
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
    refundable_amount = _quantize_amount(
        max(refundable_base - penalty_fee, Decimal('0.00')))
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
            f'{_get_order_product_summary(order)}'
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


def _get_payment_order_details(payment):
    if payment.cake_order_id:
        return payment.cake_order, 'cake'
    if payment.package_order_id:
        return payment.package_order, 'package'
    return None, None


def _sync_order_confirmation_from_payment(payment, actor=None):
    if payment.payment_status != 'paid' or payment.payment_purpose not in ['deposit', 'full']:
        return

    order, order_type = _get_payment_order_details(payment)
    if order is None:
        return

    if order.order_status not in {'pending', 'payment_retry'}:
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


def _sync_order_rejection_from_payment(payment, actor=None):
    if payment.payment_status != 'rejected' or payment.payment_purpose not in ['deposit', 'full']:
        return

    order, order_type = _get_payment_order_details(payment)
    if order is None or order.order_status == 'cancelled':
        return

    previous_status = order.order_status
    order.order_status = 'payment_retry'
    order.save(update_fields=['order_status', 'updated_at'])
    _create_order_status_notification(order, order_type, previous_status)

    if actor is not None:
        _log_staff_activity(
            actor,
            'order_awaiting_payment_resubmission',
            f'Marked {_get_order_label(order)} #{order.id} as awaiting payment resubmission after rejecting {payment.payment_purpose} payment #{payment.id}.',
            f'{order_type}_order',
            order.id,
        )


def _set_order_pending_after_resubmission(order):
    previous_status = order.order_status
    if previous_status != 'payment_retry':
        return

    order.order_status = 'pending'
    order.save(update_fields=['order_status', 'updated_at'])


def _is_full_access_user(user):
    return _user_has_any_role(user, FULL_ACCESS_ROLE_VALUES)


def _get_allowed_status_updates(user, order):
    role_value = _get_user_role_value(user)
    order_kind = _get_order_kind(order)

    if order.order_status in {'completed', 'cancelled'}:
        return []

    if _is_full_access_user(user):
        if order.order_status in {'pending', 'payment_retry'}:
            return [('cancelled', 'Cancelled')]
        return [
            ('preparing', 'Preparing'),
            ('ready_for_pickup', 'Ready for Pickup'),
            ('out_for_delivery', 'Out for Delivery'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ]

    if role_value == 'cashier':
        if order.order_status in {'confirmed', 'preparing', 'ready_for_pickup', 'out_for_delivery'}:
            return [
                ('ready_for_pickup', 'Ready for Pickup'),
                ('out_for_delivery', 'Out for Delivery'),
                ('completed', 'Completed'),
            ]
        return []

    if role_value == 'baker' and order_kind == 'cake' and order.order_status == 'confirmed':
        return [('preparing', 'Preparing')]

    if role_value == 'packager' and order_kind == 'package' and order.order_status == 'confirmed':
        return [('preparing', 'Preparing')]

    return []


def _can_view_order_for_role(user, order):
    role_value = _get_user_role_value(user)
    if role_value in FULL_ACCESS_ROLE_VALUES or role_value == 'cashier':
        return True
    if role_value == 'baker' and _get_order_kind(order) == 'cake':
        return order.order_status in {'confirmed', 'preparing', 'ready_for_pickup', 'out_for_delivery', 'completed'}
    if role_value == 'packager' and _get_order_kind(order) == 'package':
        return order.order_status in {'confirmed', 'preparing', 'ready_for_pickup', 'out_for_delivery', 'completed'}
    return False


def _decorate_admin_orders_with_actions(orders, request):
    payment_status_labels = dict(Payment.PAYMENT_STATUS)
    payment_method_labels = dict(Payment.PAYMENT_METHODS)
    payment_purpose_labels = dict(Payment.PAYMENT_PURPOSES)

    for order in orders:
        if order.is_archived:
            order.allowed_status_updates = []
        else:
            order.allowed_status_updates = _get_allowed_status_updates(
                request.user, order)
        order.can_archive = _is_full_access_user(request.user)
        order.archive_action_label = 'Restore Order' if order.is_archived else 'Archive Order'
        order.archive_confirm_label = 'Restore' if order.is_archived else 'Archive'
        order.latest_payment_status_label = payment_status_labels.get(
            getattr(order, 'latest_payment_status', ''),
            'No Payment Yet',
        )
        order.latest_payment_method_label = payment_method_labels.get(
            getattr(order, 'latest_payment_method', ''),
            '',
        )
        order.latest_payment_purpose_label = payment_purpose_labels.get(
            getattr(order, 'latest_payment_purpose', ''),
            '',
        )
        if order.latest_payment_purpose_label and order.latest_payment_method_label:
            order.latest_payment_summary_label = (
                f'{order.latest_payment_purpose_label} via {order.latest_payment_method_label}'
            )
        else:
            order.latest_payment_summary_label = (
                order.latest_payment_purpose_label or order.latest_payment_method_label
            )
    return orders


def _build_admin_order_payment_prefetch():
    return Prefetch('payments', queryset=Payment.objects.order_by('-updated_at', '-id'))


def _annotate_admin_order_activity(queryset, payment_relation_field):
    latest_payment_queryset = Payment.objects.filter(
        **{payment_relation_field: OuterRef('pk')}
    ).order_by('-updated_at', '-id')
    latest_payment_updated_at = Subquery(
        latest_payment_queryset.values('updated_at')[:1],
        output_field=DateTimeField(),
    )
    return queryset.annotate(
        latest_payment_id=Subquery(
            latest_payment_queryset.values('id')[:1]),
        latest_payment_status=Subquery(
            latest_payment_queryset.values('payment_status')[:1]),
        latest_payment_method=Subquery(
            latest_payment_queryset.values('payment_method')[:1]),
        latest_payment_purpose=Subquery(
            latest_payment_queryset.values('payment_purpose')[:1]),
        latest_payment_updated_at=latest_payment_updated_at,
        last_activity_at=Greatest(
            F('updated_at'),
            Coalesce(latest_payment_updated_at, F('updated_at')),
        ),
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

    deposit_amount, balance_due = _calculate_deposit_breakdown(
        order.total_price)
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
        status='active',
        package_type__in=PUBLIC_PACKAGE_TYPE_VALUES,
        is_archived=False,
    )


def _get_public_cake_queryset():
    return Cake.objects.filter(is_active=True, is_archived=False)


def _ensure_about_page_image_records():
    for slot_detail in ABOUT_PAGE_IMAGE_SLOT_DETAILS:
        AboutPageImage.objects.get_or_create(slot=slot_detail['slot'])


def _build_about_page_image_context():
    _ensure_about_page_image_records()
    stored_images = {item.slot: item for item in AboutPageImage.objects.all()}
    context = {}
    for slot_detail in ABOUT_PAGE_IMAGE_SLOT_DETAILS:
        slot = slot_detail['slot']
        record = stored_images.get(slot)
        default_payload = ABOUT_PAGE_IMAGE_DEFAULTS[slot]
        image_url = record.image.url if record and record.image else default_payload['image_url']
        context[slot] = {
            'slot': slot,
            'title': default_payload['title'],
            'image_url': image_url,
            'record': record,
        }
    return context


def _is_archived_admin_view(request):
    return request.GET.get('archived') == '1'


def _build_path_with_query(path, query_params):
    encoded_query = query_params.urlencode()
    return f'{path}?{encoded_query}' if encoded_query else path


def _build_named_url_with_query(route_name, query_params):
    return _build_path_with_query(reverse(route_name), query_params)


def _get_safe_admin_return_url(request, fallback_name):
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    query_params = request.GET.copy()
    query_params.pop('next', None)
    return _build_named_url_with_query(fallback_name, query_params)


def _paginate_admin_queryset(request, queryset, page_param, per_page=10):
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get(page_param) or 1)
    result_count = paginator.count
    start_index = page_obj.start_index() if result_count else 0
    end_index = page_obj.end_index() if result_count else 0

    def build_page_url(page_number):
        query_params = request.GET.copy()
        query_params.pop('next', None)
        if int(page_number) > 1:
            query_params[page_param] = str(page_number)
        else:
            query_params.pop(page_param, None)
        return _build_path_with_query(request.path, query_params)

    return page_obj, {
        'summary': f'Showing {start_index}-{end_index} of {result_count}',
        'has_multiple_pages': page_obj.has_other_pages(),
        'prev_url': build_page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        'next_url': build_page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
    }


def _archive_model_instance(instance, **field_overrides):
    update_fields = []
    if hasattr(instance, 'is_archived'):
        instance.is_archived = True
        update_fields.append('is_archived')
    if hasattr(instance, 'archived_at'):
        instance.archived_at = timezone.now()
        update_fields.append('archived_at')

    for field_name, field_value in field_overrides.items():
        setattr(instance, field_name, field_value)
        update_fields.append(field_name)

    if hasattr(instance, 'updated_at'):
        update_fields.append('updated_at')

    if update_fields:
        instance.save(update_fields=list(dict.fromkeys(update_fields)))


def _restore_model_instance(instance, **field_overrides):
    update_fields = []
    if hasattr(instance, 'is_archived'):
        instance.is_archived = False
        update_fields.append('is_archived')
    if hasattr(instance, 'archived_at'):
        instance.archived_at = None
        update_fields.append('archived_at')

    for field_name, field_value in field_overrides.items():
        setattr(instance, field_name, field_value)
        update_fields.append(field_name)

    if hasattr(instance, 'updated_at'):
        update_fields.append('updated_at')

    if update_fields:
        instance.save(update_fields=list(dict.fromkeys(update_fields)))


def _redirect_authenticated_user(user):
    if not hasattr(user, 'profile'):
        if user.is_superuser:
            _assign_user_role(user, 'owner')
        else:
            _assign_user_role(user, 'customer')

    role = user.profile.role
    if user.is_superuser or role in STAFF_ROLE_VALUES:
        return redirect('admin_dashboard')
    return redirect('profile')


def _build_sales_export_rows(payments):
    rows = []
    for payment in payments:
        order = payment.cake_order or payment.package_order
        order_type = 'Cake Order' if payment.cake_order_id else 'Package Order'
        order_id = order.id if order else ''
        customer_name = ''
        if order:
            customer_name = order.contact_name or order.user.get_full_name() or order.user.username

        rows.append({
            'payment_id': payment.id,
            'order_type': order_type,
            'order_id': order_id,
            'customer_name': customer_name,
            'payment_purpose': payment.get_payment_purpose_display(),
            'payment_method': payment.get_payment_method_display(),
            'reference_number': payment.reference_number or ('Not required' if payment.payment_method != 'gcash' else '-'),
            'amount': payment.amount,
            'paid_at': payment.paid_at or payment.created_at,
        })
    return rows


def _parse_stock_quantity(value, default=0):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _build_order_sales_report_rows(limit=8):
    product_totals = {}

    cake_orders = CakeOrder.objects.select_related('cake').filter(is_archived=False).exclude(
        order_status='cancelled',
    )
    for order in cake_orders:
        product = order.cake
        product_name = str(getattr(product, 'name', '') or 'Custom Cake').strip()
        product_code = str(getattr(product, 'product_code', '') or '').strip()
        product_key = ('cake', getattr(product, 'pk', None) or f'cake-order-{order.pk}')
        summary = product_totals.setdefault(product_key, {
            'type_key': 'cake',
            'type_label': 'Cake',
            'product_name': product_name,
            'product_code': product_code,
            'product_id': product_code or f'CAKE-ORDER-{order.pk}',
            'order_count': 0,
            'units_sold': 0,
            'gross_sales': Decimal('0.00'),
            'manage_url': reverse('admin_cake_edit', args=[product.pk]) if product else reverse('admin_cakes'),
        })
        summary['order_count'] += 1
        summary['units_sold'] += max(order.quantity or 0, 1)
        summary['gross_sales'] += order.total_price or Decimal('0.00')

    package_orders = PackageOrder.objects.select_related('package').filter(is_archived=False).exclude(
        order_status='cancelled',
    )
    for order in package_orders:
        product = order.package
        product_name = str(getattr(product, 'name', '') or 'Custom Package').strip()
        product_code = str(getattr(product, 'product_code', '') or '').strip()
        product_key = ('package', getattr(product, 'pk', None) or f'package-order-{order.pk}')
        summary = product_totals.setdefault(product_key, {
            'type_key': 'package',
            'type_label': 'Package',
            'product_name': product_name,
            'product_code': product_code,
            'product_id': product_code or f'PACKAGE-ORDER-{order.pk}',
            'order_count': 0,
            'units_sold': 0,
            'gross_sales': Decimal('0.00'),
            'manage_url': reverse('admin_package_edit', args=[product.pk]) if product else reverse('admin_packages'),
        })
        summary['order_count'] += 1
        summary['units_sold'] += 1
        summary['gross_sales'] += order.total_price or Decimal('0.00')

    rows = sorted(
        product_totals.values(),
        key=lambda item: (
            item['gross_sales'],
            item['units_sold'],
            item['product_name'].lower(),
        ),
        reverse=True,
    )
    if limit is not None:
        return rows[:limit]
    return rows


def _get_stock_health(stock_value):
    stock_value = int(stock_value or 0)
    if stock_value <= 0:
        return {'key': 'out', 'label': 'Out of Stock', 'tone': 'cancelled'}
    if stock_value <= LOW_STOCK_THRESHOLD:
        return {'key': 'low', 'label': 'Needs Replenishment', 'tone': 'pending'}
    return {'key': 'available', 'label': 'Available', 'tone': 'completed'}


def _decorate_products_with_stock_health(products):
    for product in products:
        stock_value = int(getattr(product, 'stock', 0) or 0)
        health = _get_stock_health(stock_value)
        product.stock_value = stock_value
        product.stock_health_key = health['key']
        product.stock_health_label = health['label']
        product.stock_health_tone = health['tone']
    return products


def _build_stock_report_rows(limit=None):
    rows = []
    for cake in Cake.objects.filter(is_archived=False).order_by('name'):
        health = _get_stock_health(cake.stock)
        rows.append({
            'type_key': 'cake',
            'type_label': 'Cake Product',
            'product_name': cake.name,
            'product_code': cake.product_code or f'CK-{cake.pk}',
            'stock_value': int(cake.stock or 0),
            'health_key': health['key'],
            'health_label': health['label'],
            'health_tone': health['tone'],
            'is_active': cake.is_active,
            'manage_url': reverse('admin_cake_edit', args=[cake.pk]),
        })
    for package in Package.objects.filter(is_archived=False).order_by('name'):
        health = _get_stock_health(package.stock)
        rows.append({
            'type_key': 'package',
            'type_label': 'Package Product',
            'product_name': package.name,
            'product_code': package.product_code or f'PKG-{package.pk}',
            'stock_value': int(package.stock or 0),
            'health_key': health['key'],
            'health_label': health['label'],
            'health_tone': health['tone'],
            'is_active': package.status == 'active',
            'manage_url': reverse('admin_package_edit', args=[package.pk]),
        })

    priority = {'out': 0, 'low': 1, 'available': 2}
    rows.sort(key=lambda item: (priority[item['health_key']], item['stock_value'], item['product_name'].lower()))
    if limit is not None:
        return rows[:limit]
    return rows


def _get_order_stock_context(order):
    if isinstance(order, CakeOrder):
        return {
            'product': order.cake,
            'quantity': max(order.quantity or 0, 1),
            'product_type': 'cake',
            'product_label': 'Cake Product',
            'order_label': 'cake order',
        }
    return {
        'product': order.package,
        'quantity': 1,
        'product_type': 'package',
        'product_label': 'Package Product',
        'order_label': 'package order',
    }


def _validate_order_stock_availability(order):
    stock_context = _get_order_stock_context(order)
    product = stock_context['product']
    if product is None:
        return None

    available_stock = int(getattr(product, 'stock', 0) or 0)
    required_units = int(stock_context['quantity'])
    if available_stock >= required_units:
        return None

    product_name = getattr(product, 'name', stock_context['product_label'])
    product_code = getattr(product, 'product_code', '') or 'Not assigned'
    return (
        f'Cannot complete order #{order.id} because {product_name} '
        f'({product_code}) only has {available_stock} stock on hand and '
        f'this order needs {required_units}.'
    )


def _commit_order_stock(order, actor=None):
    if getattr(order, 'stock_deducted', False):
        return False

    stock_error = _validate_order_stock_availability(order)
    if stock_error:
        raise ValueError(stock_error)

    stock_context = _get_order_stock_context(order)
    product = stock_context['product']
    if product is None:
        return False

    product.stock = max(int(product.stock or 0) - int(stock_context['quantity']), 0)
    product.save(update_fields=['stock', 'updated_at'])
    order.stock_deducted = True
    order.save(update_fields=['stock_deducted'])

    if actor is not None:
        _log_staff_activity(
            actor,
            f"{stock_context['product_type']}_stock_deducted",
            f"Deducted {stock_context['quantity']} stock from {stock_context['product_label']} \"{product.name}\" ({product.product_code or 'Not assigned'}) after completing {stock_context['order_label']} #{order.id}.",
            stock_context['product_type'],
            product.id,
        )
    return True


def _restore_order_stock(order, actor=None):
    if not getattr(order, 'stock_deducted', False):
        return False

    stock_context = _get_order_stock_context(order)
    product = stock_context['product']
    if product is None:
        return False

    product.stock = int(product.stock or 0) + int(stock_context['quantity'])
    product.save(update_fields=['stock', 'updated_at'])
    order.stock_deducted = False
    order.save(update_fields=['stock_deducted'])

    if actor is not None:
        _log_staff_activity(
            actor,
            f"{stock_context['product_type']}_stock_restored",
            f"Restored {stock_context['quantity']} stock to {stock_context['product_label']} \"{product.name}\" ({product.product_code or 'Not assigned'}) after moving {stock_context['order_label']} #{order.id} away from completed status.",
            stock_context['product_type'],
            product.id,
        )
    return True


def _build_sales_export_filename(file_format):
    return f'hanilies-sales-report-{timezone.localdate().isoformat()}.{file_format}'


AUDIT_EXPORT_MAX_DAYS = 30


def _build_activity_log_export_filename(file_format):
    return f'hanilies-audit-trail-{timezone.localdate().isoformat()}.{file_format}'


AUDIT_VALUE_LABEL_OVERRIDES = {
    'cake': 'Cake Product',
    'package': 'Package Product',
    'cake_order': 'Cake Order',
    'package_order': 'Package Order',
    'contact_inquiry': 'Inquiry',
    'home_hero_image': 'Homepage Banner',
    'home_strip_image': 'Promotional Banner',
    'about_page_image': 'About Image',
    'report': 'Report',
    'home_hero_created': 'Homepage Banner Created',
    'home_hero_updated': 'Homepage Banner Updated',
    'home_hero_deleted': 'Homepage Banner Deleted',
    'home_strip_created': 'Promotional Banner Created',
    'home_strip_updated': 'Promotional Banner Updated',
    'home_strip_deleted': 'Promotional Banner Deleted',
    'about_image_updated': 'About Images Updated',
    'cake_created': 'Cake Product Created',
    'cake_updated': 'Cake Product Updated',
    'cake_archived': 'Cake Product Archived',
    'cake_restored': 'Cake Product Restored',
    'package_created': 'Package Product Created',
    'package_updated': 'Package Product Updated',
    'package_archived': 'Package Product Archived',
    'package_restored': 'Package Product Restored',
    'cake_stock_initialized': 'Cake Product Stock Initialized',
    'cake_stock_updated': 'Cake Product Stock Updated',
    'cake_stock_deducted': 'Cake Product Stock Deducted',
    'cake_stock_restored': 'Cake Product Stock Restored',
    'package_stock_initialized': 'Package Product Stock Initialized',
    'package_stock_updated': 'Package Product Stock Updated',
    'package_stock_deducted': 'Package Product Stock Deducted',
    'package_stock_restored': 'Package Product Stock Restored',
    'user_password_reset_sent': 'Admin Password Reset Email Sent',
    'order_confirmed_from_payment': 'Order Confirmed From Payment',
    'order_awaiting_payment_resubmission': 'Order Awaiting Payment Resubmission',
    'sales_report_exported': 'Sales Report Exported',
    'audit_trail_exported': 'Audit Trail Exported',
    'audit_trail_print_preview': 'Audit Trail Print Preview Opened',
}

AUDIT_ACTION_GROUP_DEFINITIONS = [
    {
        'key': 'authentication',
        'label': 'Authentication',
        'description': 'Login sessions and password reset activity.',
        'icon': 'shield-halved',
        'actions': [
            'User login',
            'User logout',
            'Password reset requested',
            'Password reset completed',
            'user_password_reset_sent',
        ],
    },
    {
        'key': 'users',
        'label': 'Users & Customers',
        'description': 'Account creation, edits, role updates, and account status changes.',
        'icon': 'users',
        'actions': [
            'user_created',
            'user_updated',
            'user_role_updated',
            'user_archived',
            'user_restored',
        ],
    },
    {
        'key': 'content',
        'label': 'Content',
        'description': 'Homepage banners, promotional banners, and About page image updates.',
        'icon': 'images',
        'actions': [
            'home_hero_created',
            'home_hero_updated',
            'home_hero_deleted',
            'home_strip_created',
            'home_strip_updated',
            'home_strip_deleted',
            'about_image_updated',
        ],
    },
    {
        'key': 'products',
        'label': 'Products',
        'description': 'Cake product and package product maintenance activity.',
        'icon': 'box-open',
        'actions': [
            'cake_created',
            'cake_updated',
            'cake_archived',
            'cake_restored',
            'package_created',
            'package_updated',
            'package_archived',
            'package_restored',
        ],
    },
    {
        'key': 'inventory',
        'label': 'Inventory',
        'description': 'Stock setup, replenishment, deduction, and restoration events.',
        'icon': 'boxes-stacked',
        'actions': [
            'cake_stock_initialized',
            'cake_stock_updated',
            'cake_stock_deducted',
            'cake_stock_restored',
            'package_stock_initialized',
            'package_stock_updated',
            'package_stock_deducted',
            'package_stock_restored',
        ],
    },
    {
        'key': 'cake_orders',
        'label': 'Cake Orders',
        'description': 'Cake order status, archive, and restore actions.',
        'icon': 'shopping-cart',
        'actions': [
            'cake_order_status_updated',
            'cake_order_archived',
            'cake_order_restored',
        ],
    },
    {
        'key': 'package_orders',
        'label': 'Package Orders',
        'description': 'Package order status, archive, and restore actions.',
        'icon': 'calendar-check',
        'actions': [
            'package_order_status_updated',
            'package_order_archived',
            'package_order_restored',
        ],
    },
    {
        'key': 'payments',
        'label': 'Payments',
        'description': 'Payment verification changes and order payment follow-up events.',
        'icon': 'credit-card',
        'actions': [
            'payment_status_updated',
            'payment_archived',
            'payment_restored',
            'order_confirmed_from_payment',
            'order_awaiting_payment_resubmission',
        ],
    },
    {
        'key': 'refunds',
        'label': 'Refunds',
        'description': 'Refund approval, rejection, and processing events.',
        'icon': 'rotate-left',
        'actions': [
            'refund_approved',
            'refund_rejected',
            'refund_processed',
        ],
    },
    {
        'key': 'inquiries',
        'label': 'Inquiries',
        'description': 'Customer inquiry read states, replies, archive, and restore actions.',
        'icon': 'envelope-open-text',
        'actions': [
            'contact_inquiry_read',
            'contact_inquiry_unread',
            'contact_inquiry_replied',
            'contact_inquiry_archived',
            'contact_inquiry_restored',
            'contact_inquiry_deleted',
        ],
    },
    {
        'key': 'testimonials',
        'label': 'Testimonials',
        'description': 'Testimonial moderation, archive, and restore events.',
        'icon': 'comments',
        'actions': [
            'testimonial_approved',
            'testimonial_rejected',
            'testimonial_hidden',
            'testimonial_archived',
            'testimonial_restored',
        ],
    },
    {
        'key': 'reports',
        'label': 'Reports',
        'description': 'Report exports and print-preview activity from the admin dashboard.',
        'icon': 'chart-column',
        'actions': [
            'sales_report_exported',
            'audit_trail_exported',
            'audit_trail_print_preview',
        ],
    },
]


def _format_activity_label(value):
    if not value:
        return '-'
    return AUDIT_VALUE_LABEL_OVERRIDES.get(
        value,
        str(value).replace('_', ' ').strip().title(),
    )


def _parse_admin_filter_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _normalize_activity_log_filter_state(request, *, export_scope=False):
    today = timezone.localdate()
    action_values = [
        value.strip()
        for value in request.GET.getlist('action')
        if value.strip()
    ]
    if not action_values:
        single_action = request.GET.get('action', '').strip()
        if single_action:
            action_values = [single_action]

    filter_state = {
        'search': request.GET.get('q', '').strip(),
        'action': action_values[0] if len(action_values) == 1 else '',
        'action_values': action_values,
        'target_type': request.GET.get('target_type', '').strip(),
        'actor': request.GET.get('actor', '').strip(),
        'record_id': request.GET.get('record_id', '').strip(),
        'record_id_value': None,
        'record_id_invalid': False,
        'date_from_value': _parse_admin_filter_date(request.GET.get('date_from', '').strip()),
        'date_to_value': _parse_admin_filter_date(request.GET.get('date_to', '').strip()),
        'export_scope': export_scope,
    }

    if filter_state['record_id']:
        try:
            filter_state['record_id_value'] = int(filter_state['record_id'])
        except (TypeError, ValueError):
            filter_state['record_id_invalid'] = True

    if export_scope:
        date_to = filter_state['date_to_value'] or today
        if date_to > today:
            date_to = today

        date_from = filter_state['date_from_value'] or (
            date_to - timedelta(days=AUDIT_EXPORT_MAX_DAYS - 1)
        )
        max_window_start = date_to - timedelta(days=AUDIT_EXPORT_MAX_DAYS - 1)
        if date_from < max_window_start:
            date_from = max_window_start
        if date_from > date_to:
            date_from = max_window_start

        filter_state['date_from_value'] = date_from
        filter_state['date_to_value'] = date_to

    filter_state['date_from'] = (
        filter_state['date_from_value'].isoformat()
        if filter_state['date_from_value'] else ''
    )
    filter_state['date_to'] = (
        filter_state['date_to_value'].isoformat()
        if filter_state['date_to_value'] else ''
    )
    return filter_state


def _filter_activity_logs_queryset(queryset, filter_state):
    search_term = filter_state['search']
    if search_term:
        queryset = queryset.filter(
            Q(description__icontains=search_term)
            | Q(action__icontains=search_term)
            | Q(target_type__icontains=search_term)
            | Q(actor__username__icontains=search_term)
            | Q(actor_role__icontains=search_term)
        )

    if filter_state['action_values']:
        queryset = queryset.filter(action__in=filter_state['action_values'])

    if filter_state['target_type']:
        queryset = queryset.filter(target_type=filter_state['target_type'])

    if filter_state['actor']:
        if filter_state['actor'].isdigit():
            queryset = queryset.filter(actor_id=int(filter_state['actor']))
        else:
            queryset = queryset.none()

    if filter_state['record_id']:
        if filter_state['record_id_invalid']:
            queryset = queryset.none()
        else:
            queryset = queryset.filter(
                target_id=filter_state['record_id_value'])

    if filter_state['date_from_value']:
        queryset = queryset.filter(
            created_at__date__gte=filter_state['date_from_value'])

    if filter_state['date_to_value']:
        queryset = queryset.filter(
            created_at__date__lte=filter_state['date_to_value'])

    return queryset


def _build_activity_log_target_label(activity_log):
    if not activity_log.target_type:
        return '-'
    target_label = _format_activity_label(activity_log.target_type)
    if activity_log.target_id:
        return f'{target_label} #{activity_log.target_id}'
    return target_label


def _build_activity_log_summary(queryset):
    return {
        'total_records': queryset.count(),
        'unique_users': queryset.exclude(actor__isnull=True).values('actor_id').distinct().count(),
        'session_events': queryset.filter(action__in=['User login', 'User logout']).count(),
        'login_events': queryset.filter(action__icontains='login').count(),
        'order_events': queryset.filter(
            Q(target_type__in=['cake_order', 'package_order'])
            | Q(action__icontains='order')
        ).count(),
        'archive_events': queryset.filter(
            Q(action__icontains='archive')
            | Q(action__icontains='restore')
        ).count(),
        'module_count': queryset.exclude(target_type='').values('target_type').distinct().count(),
    }


def _build_activity_log_export_rows(queryset):
    rows = []
    for activity_log in queryset:
        created_at = timezone.localtime(activity_log.created_at)
        role_badge_key, role_badge_label = _get_activity_role_badge(
            activity_log.actor,
            activity_log.actor_role,
        )
        action_key = _get_activity_action_key(activity_log.action)
        if action_key == 'login':
            login_logout_label = 'Login'
        elif action_key == 'logout':
            login_logout_label = 'Logout'
        else:
            login_logout_label = '-'

        rows.append({
            'created_at': created_at,
            'date_display': created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'actor': activity_log.actor.username if activity_log.actor else 'Deleted user',
            'role': activity_log.actor_role or '-',
            'role_badge_key': role_badge_key,
            'role_badge_label': role_badge_label,
            'action': _format_activity_label(activity_log.action),
            'action_key': action_key,
            'display_record_id': f'#{activity_log.target_id}' if activity_log.target_id else '-',
            'login_logout_label': login_logout_label,
            'status_label': 'Archived' if activity_log.is_archived else 'Active',
            'status_key': 'archived' if activity_log.is_archived else 'active',
            'target': _build_activity_log_target_label(activity_log),
            'module': _format_activity_label(activity_log.target_type),
            'record_id': activity_log.target_id,
            'description': activity_log.description,
        })
    return rows


def _get_activity_action_key(action_value):
    normalized = (action_value or '').strip().lower()
    if any(token in normalized for token in ['create', 'add', 'placed', 'register']):
        return 'create'
    if any(token in normalized for token in ['update', 'edit', 'verify', 'approve', 'processed']):
        return 'update'
    if any(token in normalized for token in ['delete', 'remove', 'reject']):
        return 'delete'
    if 'archive' in normalized:
        return 'archive'
    if 'restore' in normalized:
        return 'restore'
    if 'login' in normalized:
        return 'login'
    if 'logout' in normalized:
        return 'logout'
    return 'default'


def _get_activity_role_badge(actor, actor_role):
    profile_role = ''
    if actor is not None:
        profile = getattr(actor, 'profile', None)
        profile_role = getattr(profile, 'role', '') or ''

    normalized = f'{profile_role} {actor_role or ""}'.strip().lower()
    if any(token in normalized for token in ['owner', 'admin']):
        return 'admin', 'Admin'
    if any(token in normalized for token in ['manager', 'supervisor', 'cashier', 'staff']):
        return 'staff', 'Staff'
    return 'customer', 'Customer'


def _build_activity_log_query(request, **overrides):
    query_params = request.GET.copy()
    query_params.pop('next', None)
    for key, value in overrides.items():
        if value in (None, ''):
            query_params.pop(key, None)
        else:
            query_params[key] = str(value)
    return query_params


def _build_activity_log_filter_chips(filter_state, actor_options):
    actor_labels = {
        str(actor['id']): actor['username']
        for actor in actor_options
    }
    chips = []

    if filter_state['search']:
        chips.append(f"Search: {filter_state['search']}")

    if filter_state['target_type']:
        chips.append(
            f"Module: {_format_activity_label(filter_state['target_type'])}")

    if filter_state['action_values']:
        chips.append(
            f"Action: {', '.join(_format_activity_label(value) for value in filter_state['action_values'])}")

    if filter_state['actor']:
        chips.append(
            f"User: {actor_labels.get(filter_state['actor'], 'Unknown user')}")

    if filter_state['record_id']:
        chips.append(f"Record ID: {filter_state['record_id']}")

    if filter_state['date_from_value'] or filter_state['date_to_value']:
        from_label = (
            filter_state['date_from_value'].strftime('%b %d, %Y')
            if filter_state['date_from_value'] else 'Any'
        )
        to_label = (
            filter_state['date_to_value'].strftime('%b %d, %Y')
            if filter_state['date_to_value'] else 'Any'
        )
        chips.append(f'Date: {from_label} - {to_label}')

    return chips



def _build_activity_log_action_groups(available_actions, selected_actions):
    available_action_set = {
        str(value).strip()
        for value in available_actions
        if str(value).strip()
    }
    selected_action_set = {
        str(value).strip()
        for value in selected_actions
        if str(value).strip()
    }
    known_action_values = set()
    action_groups = []

    for index, definition in enumerate(AUDIT_ACTION_GROUP_DEFINITIONS):
        actions = []
        for action_value in definition['actions']:
            if action_value in known_action_values:
                continue
            known_action_values.add(action_value)
            label = _format_activity_label(action_value)
            actions.append({
                'value': action_value,
                'label': label,
                'selected': action_value in selected_action_set,
                'search_text': ' '.join([
                    definition['label'],
                    label,
                    action_value.replace('_', ' '),
                ]).strip(),
            })

        selected_count = sum(1 for action in actions if action['selected'])
        action_groups.append({
            'key': definition['key'],
            'label': definition['label'],
            'description': definition['description'],
            'icon': definition['icon'],
            'actions': actions,
            'selected_count': selected_count,
            'total_actions': len(actions),
            'has_actions': bool(actions),
            'default_open': bool(selected_count) or (index == 0 and not selected_action_set),
            'has_available_actions': any(action['value'] in available_action_set for action in actions),
        })

    extra_actions = sorted(
        (available_action_set | selected_action_set) - known_action_values,
        key=lambda value: _format_activity_label(value).lower(),
    )
    if extra_actions:
        actions = []
        for action_value in extra_actions:
            label = _format_activity_label(action_value)
            actions.append({
                'value': action_value,
                'label': label,
                'selected': action_value in selected_action_set,
                'search_text': ' '.join([
                    'System Other',
                    label,
                    action_value.replace('_', ' '),
                ]).strip(),
            })

        action_groups.append({
            'key': 'system_other',
            'label': 'System & Other',
            'description': 'Additional audit actions currently recorded outside the standard dashboard categories.',
            'icon': 'gear',
            'actions': actions,
            'selected_count': sum(1 for action in actions if action['selected']),
            'total_actions': len(actions),
            'has_actions': bool(actions),
            'default_open': any(action['selected'] for action in actions),
            'has_available_actions': True,
        })

    return action_groups


def _get_customer_cake_orders_queryset(user):
    return CakeOrder.objects.filter(user=user).order_by('-created_at')


def _get_customer_package_orders_queryset(user):
    return PackageOrder.objects.filter(user=user).order_by('-created_at')


def _get_customer_order_queryset(user, order_type):
    if order_type == 'cake':
        return _get_customer_cake_orders_queryset(user).select_related('cake').prefetch_related('payments')
    if order_type == 'package':
        return _get_customer_package_orders_queryset(user).select_related('package').prefetch_related('payments')
    raise PermissionDenied


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


def _format_structured_delivery_address(street_address, barangay, city, province, landmark=''):
    address = f'{street_address}, Brgy. {barangay}, {city}, {province}'
    if landmark:
        address = f'{address} (Landmark: {landmark})'
    return address


def _split_structured_delivery_address(raw_address):
    parsed = {
        'delivery_street_address': '',
        'delivery_barangay': '',
        'delivery_city': '',
        'delivery_province': '',
        'delivery_landmark': '',
    }
    raw_address = (raw_address or '').strip()
    if not raw_address:
        return parsed

    landmark_match = re.search(
        r'\(Landmark:\s*(.*?)\)\s*$', raw_address, flags=re.IGNORECASE)
    if landmark_match:
        parsed['delivery_landmark'] = landmark_match.group(1).strip()
        raw_address = raw_address[:landmark_match.start()].rstrip(' ,')

    parts = [part.strip() for part in raw_address.split(',') if part.strip()]
    if len(parts) >= 4 and re.match(r'^(?:brgy\.|barangay)\s+', parts[1], flags=re.IGNORECASE):
        parsed['delivery_street_address'] = parts[0]
        parsed['delivery_barangay'] = re.sub(
            r'^(?:brgy\.|barangay)\s+',
            '',
            parts[1],
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        parsed['delivery_city'] = parts[2]
        parsed['delivery_province'] = parts[3]
        return parsed

    if raw_address.lower() in DELIVERY_SERVICE_AREA_MAP:
        area = DELIVERY_SERVICE_AREA_MAP[raw_address.lower()]
        parsed['delivery_city'] = area['city']
        parsed['delivery_province'] = area['province']
        return parsed

    for index, part in enumerate(parts):
        area = DELIVERY_SERVICE_AREA_MAP.get(part.lower())
        if not area:
            continue
        parsed['delivery_city'] = area['city']
        parsed['delivery_province'] = area['province']
        if index > 0:
            parsed['delivery_street_address'] = ', '.join(parts[:index])
        return parsed

    parsed['delivery_street_address'] = raw_address
    return parsed


def _validate_structured_delivery_address(street_address, barangay, city, landmark='', required=True):
    parsed = {
        'delivery_street_address': (street_address or '').strip(),
        'delivery_barangay': (barangay or '').strip(),
        'delivery_city': (city or '').strip(),
        'delivery_landmark': (landmark or '').strip(),
        'delivery_province': '',
        'delivery_address': '',
    }

    if not any([
        parsed['delivery_street_address'],
        parsed['delivery_barangay'],
        parsed['delivery_city'],
        parsed['delivery_landmark'],
    ]) and not required:
        return parsed, None

    if not parsed['delivery_street_address'] or not parsed['delivery_barangay'] or not parsed['delivery_city']:
        return None, 'Please complete the street address, barangay, and city for the delivery address.'

    area = DELIVERY_SERVICE_AREA_MAP.get(parsed['delivery_city'].lower())
    if area is None:
        return None, 'We currently deliver only within the listed service areas. Please choose a supported city or municipality.'

    if len(parsed['delivery_street_address']) < 5:
        return None, 'Enter a more complete street address for delivery.'

    if len(parsed['delivery_barangay']) < 2:
        return None, 'Enter a valid barangay for the delivery address.'

    parsed['delivery_city'] = area['city']
    parsed['delivery_province'] = area['province']
    parsed['delivery_address'] = _format_structured_delivery_address(
        parsed['delivery_street_address'],
        parsed['delivery_barangay'],
        parsed['delivery_city'],
        parsed['delivery_province'],
        parsed['delivery_landmark'],
    )
    return parsed, None


def _get_profile_defaults(user):
    profile = getattr(user, 'profile', None)
    full_name = f'{user.first_name} {user.last_name}'.strip() or user.username
    address_defaults = _split_structured_delivery_address(
        profile.address if profile else '')
    return {
        'contact_name': full_name,
        'contact_phone': profile.phone if profile else '',
        'contact_email': user.email,
        **address_defaults,
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


def _get_selected_options(selected_values, option_items):
    selected_options = []
    seen_values = set()
    total = Decimal('0.00')
    for selected_value in selected_values:
        option = _resolve_selected_option(selected_value, option_items)
        option_value = option.get('value') if option else ''
        if not option or not option.get('label') or option_value in seen_values:
            continue
        seen_values.add(option_value)
        selected_options.append(option)
        total += option['price']
    return selected_options, total


def _join_selected_option_labels(selected_options):
    return ', '.join(option['label'] for option in selected_options)


def _build_cake_size_label(tier_option, size_option):
    labels = []
    for option in [tier_option, size_option]:
        if not option:
            continue
        label = option['label']
        if label not in labels:
            labels.append(label)
    return ' / '.join(labels)


def _split_saved_multi_select_text(raw_value):
    return [
        item.strip()
        for item in (raw_value or '').split(',')
        if item.strip()
    ]


def _get_default_option(option_items):
    if not option_items:
        return None

    return {
        'label': option_items[0]['label'],
        'value': option_items[0].get('value', option_items[0]['label']),
        'price': _parse_decimal(option_items[0]['price']),
    }


def _get_single_select_price_adjustment(selected_option, option_items):
    if not selected_option:
        return Decimal('0.00')

    if not option_items:
        return _parse_decimal(selected_option['price'])

    baseline_price = _parse_decimal(option_items[0]['price'])
    selected_price = _parse_decimal(selected_option['price'])
    return max(selected_price - baseline_price, Decimal('0.00'))


def _apply_storefront_price_adjustments(option_items, *, use_first_option_as_base=False):
    if not option_items:
        return []

    baseline_price = _parse_decimal(option_items[0]['price']) if use_first_option_as_base else Decimal('0.00')
    adjusted_items = []
    for item in option_items:
        adjusted_item = dict(item)
        adjusted_price = max(_parse_decimal(item['price']) - baseline_price, Decimal('0.00'))
        adjusted_item['storefront_price'] = format(adjusted_price.quantize(Decimal('0.01')), 'f')
        adjusted_items.append(adjusted_item)
    return adjusted_items


def _parse_positive_int(value, default=1, minimum=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, minimum)


def _normalize_package_inclusion_label_text(label):
    normalized_label = str(label or '').strip()
    if not normalized_label:
        return ''

    if re.match(r'^event\s+duration\s*:', normalized_label, re.IGNORECASE):
        return re.sub(
            r'^event\s+duration\s*:\s*3\s*(?:-|â€“|â€”|Ã»|u|to)\s*4\s+hours\s+only\s*$',
            'Event Duration: 3-4 Hours only',
            normalized_label,
            flags=re.IGNORECASE,
        )

    return normalized_label


def _normalize_package_inclusion_items(raw_items):
    items = []
    used_keys = set()
    for raw_item in raw_items or []:
        if isinstance(raw_item, str):
            label = _normalize_package_inclusion_label_text(raw_item)
            quantity = 1
            image_path = ''
            price = '0.00'
            preferred_key = ''
        elif isinstance(raw_item, dict):
            label = _normalize_package_inclusion_label_text(
                raw_item.get('label')
                or raw_item.get('name')
                or raw_item.get('value')
                or ''
            )
            quantity = _parse_positive_int(
                raw_item.get('quantity'),
                default=1,
                minimum=1,
            )
            image_path = str(raw_item.get('image') or '').strip()
            price = str(raw_item.get('price') or '0.00').strip()
            preferred_key = str(raw_item.get('key') or '').strip()
        else:
            continue

        if not label:
            continue

        item = {
            'key': _build_unique_option_key(label, used_keys, preferred_key),
            'label': label,
            'quantity': quantity,
            'price': f'{_parse_decimal(price):.2f}',
        }
        if image_path:
            item['image'] = image_path
        items.append(item)
    return items


def _parse_legacy_package_inclusion_text(raw_text):
    return _normalize_package_inclusion_items(
        [line for line in (raw_text or '').splitlines() if line.strip()]
    )


def _format_package_inclusion_label(item):
    quantity = _parse_positive_int(item.get('quantity'), default=1, minimum=1)
    label = str(item.get('label') or '').strip()
    if not label:
        return ''
    return f'{quantity} x {label}' if quantity > 1 else label


def _format_package_inclusion_lines(items):
    return [
        formatted_label
        for formatted_label in (_format_package_inclusion_label(item) for item in items)
        if formatted_label
    ]


def _build_package_inclusion_image_field_name(index):
    return f'package_inclusion_image__{index}'


def _get_package_inclusion_items(package_or_items, *, for_display=True):
    if isinstance(package_or_items, list):
        normalized = _normalize_package_inclusion_items(package_or_items)
    else:
        customization_options = getattr(
            package_or_items, 'customization_options', {}) or {}
        normalized = _normalize_package_inclusion_items(
            customization_options.get('included_items', [])
        )
        if not normalized:
            fallback_text = getattr(package_or_items, 'included_items', '') or getattr(
                package_or_items, 'features', '')
            normalized = _parse_legacy_package_inclusion_text(fallback_text)

    if not for_display:
        return normalized

    return [
        {
            **item,
            'display_label': _format_package_inclusion_label(item),
            'price_decimal': _parse_decimal(item.get('price')),
            **({'image_url': default_storage.url(item['image'])}
               if item.get('image') else {}),
        }
        for item in normalized
    ]


def _split_package_inclusion_items(inclusion_items):
    display_items = _get_package_inclusion_items(
        inclusion_items, for_display=True)
    always_included_items = []
    optional_items = []

    for item in display_items:
        if _parse_decimal(item.get('price')) > 0:
            optional_items.append(item)
        else:
            always_included_items.append(item)

    return always_included_items, optional_items


def _build_package_inclusion_editor_items(raw_items):
    return _get_package_inclusion_items(raw_items, for_display=True)


def _parse_package_inclusion_payload(payload):
    payload = (payload or '').strip()
    if not payload:
        return []

    try:
        raw_items = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError('Package inclusions could not be read.') from exc

    if not isinstance(raw_items, list):
        raise ValueError('Package inclusions are invalid.')

    return _normalize_package_inclusion_items(raw_items)


def _collect_package_inclusion_image_paths(inclusion_items):
    image_paths = set()
    for item in _normalize_package_inclusion_items(inclusion_items):
        image_path = str(item.get('image') or '').strip()
        if image_path:
            image_paths.add(image_path)
    return image_paths


def _apply_package_inclusion_image_uploads(inclusion_items, request_files, *, object_id):
    normalized = _normalize_package_inclusion_items(inclusion_items)
    for index, item in enumerate(normalized):
        uploaded_image = request_files.get(
            _build_package_inclusion_image_field_name(index)
        )
        if uploaded_image:
            item['image'] = _save_option_image(
                uploaded_image,
                'package-inclusions',
                object_id,
                'included-items',
                item['label'],
            )
        elif not str(item.get('image') or '').strip():
            item.pop('image', None)
    return normalized


def _resolve_package_inclusion_submission(post_data, fallback_text=''):
    inclusion_items = _parse_package_inclusion_payload(
        post_data.get('package_inclusions_payload')
    )
    if not inclusion_items:
        inclusion_items = _parse_legacy_package_inclusion_text(
            fallback_text or post_data.get('features', '')
        )
    return inclusion_items


def _build_package_inclusion_lookup(inclusion_items):
    return {
        item['key']: {
            'label': item['label'],
            'quantity': _parse_positive_int(item.get('quantity'), default=1, minimum=1),
            'price': _parse_decimal(item.get('price')),
        }
        for item in _normalize_package_inclusion_items(inclusion_items)
        if item.get('key')
    }


def _build_selected_package_inclusions(post_data, inclusion_items):
    inclusion_lookup = _build_package_inclusion_lookup(inclusion_items)
    selected_keys = []
    selected_quantities = {}
    clicked_keys = [
        str(key).strip() for key in post_data.getlist('selected_inclusions')
        if str(key).strip()
    ]

    for key in inclusion_lookup.keys():
        raw_quantity = post_data.get(f'inclusion_quantity__{key}', '').strip()
        quantity = _parse_positive_int(
            raw_quantity if raw_quantity else 0,
            default=0,
            minimum=0,
        )
        if key in clicked_keys and quantity <= 0:
            quantity = inclusion_lookup[key]['quantity']
        if quantity <= 0:
            continue
        selected_keys.append(key)
        selected_quantities[key] = quantity

    for key in clicked_keys:
        if key in inclusion_lookup and key not in selected_quantities:
            selected_keys.append(key)
            selected_quantities[key] = inclusion_lookup[key]['quantity']

    labels = []
    total = Decimal('0.00')
    for key in selected_keys:
        inclusion = inclusion_lookup.get(key)
        if not inclusion:
            continue
        quantity = selected_quantities.get(key, inclusion['quantity'])
        labels.append(
            f'{quantity} x {inclusion["label"]}' if quantity > 1 else inclusion['label']
        )
        total += inclusion['price'] * quantity

    return selected_keys, selected_quantities, labels, total


def _build_selected_package_addons(post_data, option_lookup):
    selected_keys = []
    selected_quantities = {}
    checkbox_keys = [
        str(key).strip() for key in post_data.getlist('selected_addons')
        if str(key).strip()
    ]

    for key in option_lookup.keys():
        raw_quantity = post_data.get(f'addon_quantity__{key}', '').strip()
        quantity = _parse_positive_int(
            raw_quantity if raw_quantity else 0,
            default=0,
            minimum=0,
        )
        if key in checkbox_keys and quantity <= 0:
            quantity = 1
        if quantity <= 0:
            continue
        selected_keys.append(key)
        selected_quantities[key] = quantity

    for key in checkbox_keys:
        if key in option_lookup and key not in selected_quantities:
            selected_keys.append(key)
            selected_quantities[key] = 1

    labels = []
    total = Decimal('0.00')
    for key in selected_keys:
        option = option_lookup.get(key)
        if not option:
            continue
        quantity = selected_quantities.get(key, 1)
        labels.append(
            f'{quantity} x {option["label"]}' if quantity > 1 else option['label']
        )
        total += option['price'] * quantity

    return selected_keys, selected_quantities, labels, total


def _build_unique_option_key(label, used_keys, preferred_key=''):
    base_key = slugify(preferred_key or label) or 'option'
    candidate = base_key
    suffix = 2
    while candidate in used_keys:
        candidate = f'{base_key}-{suffix}'
        suffix += 1
    used_keys.add(candidate)
    return candidate


def _build_checkbox_option_dedupe_identity(label):
    return slugify(str(label or '').strip()) or str(label or '').strip().lower()


def _build_checkbox_option_merge_identity(item):
    raw_key = str(item.get('key') or '').strip()
    if raw_key:
        return slugify(raw_key.replace('_', ' ')) or raw_key.lower()

    return _build_checkbox_option_dedupe_identity(item.get('label'))


def _build_checkbox_option_merge_identities(item):
    identities = set()
    label_identity = _build_checkbox_option_dedupe_identity(item.get('label'))
    if label_identity:
        identities.add(label_identity)

    key_identity = _build_checkbox_option_merge_identity(item)
    if key_identity:
        identities.add(key_identity)

    return identities


def _normalize_option_items(raw_items, spec):
    normalized_entries = []
    checkbox_entry_indexes = {}
    used_keys = set()
    input_type = spec['input_type']

    for raw_item in raw_items or []:
        if isinstance(raw_item, str):
            label = raw_item.strip()
            price = '0.00'
            preferred_key = ''
            preferred_value = ''
            image_path = ''
        elif isinstance(raw_item, dict):
            label = str(
                raw_item.get('label')
                or raw_item.get('name')
                or raw_item.get('value')
                or raw_item.get('key')
                or ''
            ).strip()
            price = f'{_parse_decimal(raw_item.get("price", "0.00")):.2f}'
            preferred_key = str(raw_item.get('key') or '').strip()
            preferred_value = str(raw_item.get('value') or '').strip()
            image_path = str(raw_item.get('image') or '').strip()
        else:
            continue

        if not label:
            continue

        entry = {
            'label': label,
            'price': f'{_parse_decimal(price):.2f}',
            'preferred_key': preferred_key,
            'preferred_value': preferred_value,
            'image_path': image_path,
        }

        if input_type == 'checkbox':
            identity = _build_checkbox_option_dedupe_identity(label)
            existing_index = checkbox_entry_indexes.get(identity)
            if existing_index is not None:
                existing_entry = normalized_entries[existing_index]
                normalized_entries[existing_index] = {
                    **existing_entry,
                    'label': entry['label'],
                    'price': entry['price'],
                    'preferred_value': entry['preferred_value'] or existing_entry['preferred_value'],
                    'image_path': entry['image_path'] or existing_entry['image_path'],
                    'preferred_key': existing_entry['preferred_key'] or entry['preferred_key'],
                }
                continue

            checkbox_entry_indexes[identity] = len(normalized_entries)

        normalized_entries.append(entry)

    items = []
    for entry in normalized_entries:
        item = {
            'label': entry['label'],
            'price': entry['price'],
        }
        if entry['image_path']:
            item['image'] = entry['image_path']
        if input_type == 'checkbox':
            item['key'] = _build_unique_option_key(
                entry['label'], used_keys, entry['preferred_key'])
        else:
            item['value'] = entry['preferred_value'] or entry['label']
        items.append(item)

    return items


def _normalize_option_groups(raw_groups, specs):
    raw_groups = raw_groups if isinstance(raw_groups, dict) else {}
    normalized = {}
    for spec in specs:
        items = _normalize_option_items(raw_groups.get(spec['key'], []), spec)
        if items:
            normalized[spec['key']] = items
    return normalized


def _clone_option_items(option_items, input_type):
    cloned_items = []
    for item in option_items or []:
        label = str(item.get('label') or '').strip()
        if not label:
            continue

        cloned_item = {
            'label': label,
            'price': f'{_parse_decimal(item.get("price", "0.00")):.2f}',
        }

        if input_type == 'checkbox':
            option_key = str(item.get('key') or '').strip()
            if option_key:
                cloned_item['key'] = option_key
        else:
            option_value = str(item.get('value') or label).strip()
            if option_value:
                cloned_item['value'] = option_value

        image_path = str(item.get('image') or '').strip()
        if image_path:
            cloned_item['image'] = image_path

        cloned_items.append(cloned_item)

    return cloned_items


def _synchronize_cake_size_option_groups(raw_groups):
    normalized = _normalize_option_groups(
        raw_groups, CAKE_CUSTOMIZATION_GROUP_SPECS)
    filtered_cake_sizes = [
        item for item in normalized.get('cake_sizes', [])
        if str(item.get('label') or '').strip().lower() not in LEGACY_CAKE_SIZE_TIER_LABELS
    ]
    if filtered_cake_sizes:
        normalized['cake_sizes'] = filtered_cake_sizes
    else:
        normalized.pop('cake_sizes', None)

    has_tier_options = bool(normalized.get('sizes'))
    has_size_options = bool(normalized.get('cake_sizes'))

    if has_tier_options and has_size_options:
        return normalized

    if has_size_options:
        normalized['sizes'] = _clone_option_items(
            normalized['cake_sizes'], 'select')

    return normalized


def _build_option_merge_identity(item, input_type):
    if input_type == 'checkbox':
        return _build_checkbox_option_merge_identity(item)

    return (
        item.get('value')
        or item.get('label')
        or ''
    ).strip().lower()


def _merge_option_item_lists(default_items, configured_items, input_type):
    if input_type == 'checkbox':
        merged_items = []
        configured_entries = [
            (item, _build_checkbox_option_merge_identities(item))
            for item in configured_items
        ]
        consumed_indexes = set()

        for default_item in default_items:
            default_identities = _build_checkbox_option_merge_identities(
                default_item,
            )
            matched_index = None

            for index, (configured_item, configured_identities) in enumerate(
                configured_entries,
            ):
                if index in consumed_indexes:
                    continue
                if default_identities & configured_identities:
                    matched_index = index
                    merged_items.append({**default_item, **configured_item})
                    consumed_indexes.add(index)
                    break

            if matched_index is None:
                merged_items.append(default_item)

        for index, (configured_item, _) in enumerate(configured_entries):
            if index not in consumed_indexes:
                merged_items.append(configured_item)

        return merged_items

    merged_items = []
    configured_by_identity = {}
    configured_order = []

    for item in configured_items:
        identity = _build_option_merge_identity(item, input_type)
        if not identity:
            continue
        configured_by_identity[identity] = item
        configured_order.append(identity)

    consumed_identities = set()

    for default_item in default_items:
        identity = _build_option_merge_identity(default_item, input_type)
        if identity and identity in configured_by_identity:
            merged_items.append(
                {**default_item, **configured_by_identity[identity]})
            consumed_identities.add(identity)
        else:
            merged_items.append(default_item)

    for identity in configured_order:
        if identity in consumed_identities:
            continue
        merged_items.append(configured_by_identity[identity])

    return merged_items


def _build_option_editor_groups(raw_groups, specs, default_groups=None):
    if default_groups:
        normalized = _merge_option_groups(raw_groups, default_groups, specs)
    else:
        normalized = _normalize_option_groups(raw_groups, specs)
    return [
        {
            **spec,
            'items': [
                {
                    **item,
                    **({'image_url': default_storage.url(item['image'])}
                       if item.get('image') else {}),
                }
                for item in normalized.get(spec['key'], [])
            ],
        }
        for spec in specs
    ]


def _parse_customization_options_payload(payload, specs):
    payload = (payload or '').strip()
    if not payload:
        return {}

    try:
        raw_groups = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            'Product customization options could not be read.') from exc

    if not isinstance(raw_groups, dict):
        raise ValueError('Product customization options are invalid.')

    return _normalize_option_groups(raw_groups, specs)


def _merge_option_groups(raw_groups, default_groups, specs):
    configured = _normalize_option_groups(raw_groups, specs)
    defaults = _normalize_option_groups(default_groups, specs)
    merged = {}
    for spec in specs:
        default_items = defaults.get(spec['key'], [])
        configured_items = configured.get(spec['key'], [])
        if configured_items:
            merged[spec['key']] = _merge_option_item_lists(
                default_items,
                configured_items,
                spec['input_type'],
            )
        else:
            merged[spec['key']] = default_items
    return merged


def _build_storefront_option_groups(raw_groups, default_groups, specs):
    merged = _merge_option_groups(raw_groups, default_groups, specs)
    return {
        spec['key']: [
            {
                **item,
                **({'image_url': default_storage.url(item['image'])}
                   if item.get('image') else {}),
            }
            for item in merged.get(spec['key'], [])
        ]
        for spec in specs
    }


REMOVED_PACKAGE_CAKE_DECORATION_IDENTITIES = {
    'edible-image',
    'edible-image-print',
}
REMOVED_CAKE_STOREFRONT_TIER_IDENTITIES = {
    '5-tier',
}


def _filter_removed_package_cake_decorations(raw_groups):
    normalized = _normalize_option_groups(
        raw_groups, PACKAGE_CUSTOMIZATION_GROUP_SPECS)
    decoration_items = normalized.get('cake_decorations', [])
    if not decoration_items:
        return normalized

    normalized['cake_decorations'] = [
        item for item in decoration_items
        if not (
            _build_checkbox_option_merge_identity(item)
            in REMOVED_PACKAGE_CAKE_DECORATION_IDENTITIES
            or _build_checkbox_option_dedupe_identity(item.get('label'))
            in REMOVED_PACKAGE_CAKE_DECORATION_IDENTITIES
        )
    ]
    if not normalized['cake_decorations']:
        normalized.pop('cake_decorations', None)

    return normalized


def _filter_removed_cake_storefront_tiers(option_groups):
    filtered_groups = dict(option_groups)
    size_options = filtered_groups.get('sizes', [])
    if not size_options:
        return filtered_groups

    filtered_groups['sizes'] = [
        item for item in size_options
        if _build_checkbox_option_dedupe_identity(item.get('label'))
        not in REMOVED_CAKE_STOREFRONT_TIER_IDENTITIES
    ]
    return filtered_groups


def _build_option_image_field_name(group_key, index):
    return f'option_image__{group_key}__{index}'


def _collect_option_image_paths(raw_groups, specs):
    normalized = _normalize_option_groups(raw_groups, specs)
    image_paths = set()
    for spec in specs:
        for item in normalized.get(spec['key'], []):
            image_path = str(item.get('image') or '').strip()
            if image_path:
                image_paths.add(image_path)
    return image_paths


def _save_option_image(uploaded_image, product_prefix, object_id, group_key, label):
    validation_error = _validate_optional_design_reference_upload(
        uploaded_image)
    if validation_error:
        raise ValueError(validation_error)

    _, extension = os.path.splitext(uploaded_image.name or '')
    extension = extension.lower() or '.jpg'
    safe_label = slugify(label) or 'option'
    file_name = f'{safe_label}-{os.urandom(3).hex()}{extension}'
    return default_storage.save(
        f'{product_prefix}/{object_id}/{group_key}/{file_name}',
        uploaded_image,
    )


def _apply_option_image_uploads(option_groups, specs, request_files, *, product_prefix, object_id):
    normalized = _normalize_option_groups(option_groups, specs)
    for spec in specs:
        group_items = normalized.get(spec['key'], [])
        for index, item in enumerate(group_items):
            uploaded_image = request_files.get(
                _build_option_image_field_name(spec['key'], index))
            if uploaded_image:
                item['image'] = _save_option_image(
                    uploaded_image,
                    product_prefix,
                    object_id,
                    spec['key'],
                    item['label'],
                )
            elif not str(item.get('image') or '').strip():
                item.pop('image', None)
    return normalized


def _delete_option_images(image_paths):
    for image_path in image_paths:
        if not image_path:
            continue
        try:
            default_storage.delete(image_path)
        except Exception:
            continue


def _build_checkbox_option_lookup(option_items):
    return {
        item['key']: {
            'label': item['label'],
            'price': _parse_decimal(item['price']),
        }
        for item in option_items
        if item.get('key')
    }


def _build_select_option_lookup(option_items):
    return {
        item.get('value', item['label']): {
            'label': item['label'],
            'value': item.get('value', item['label']),
            'price': _parse_decimal(item['price']),
        }
        for item in option_items
        if item.get('label')
    }


def _resolve_selected_option(selected_value, option_items):
    selected_value = (selected_value or '').strip()
    if not selected_value:
        return None

    lookup = _build_select_option_lookup(option_items)
    matched = lookup.get(selected_value)
    if matched:
        return matched

    for item in option_items:
        if item['label'].strip().lower() == selected_value.lower():
            return {
                'label': item['label'],
                'value': item.get('value', item['label']),
                'price': _parse_decimal(item['price']),
            }

    return {
        'label': selected_value,
        'value': selected_value,
        'price': Decimal('0.00'),
    }


def _get_cake_storefront_options(cake):
    return _filter_removed_cake_storefront_tiers(
        _build_storefront_option_groups(
            _synchronize_cake_size_option_groups(
                getattr(cake, 'customization_options', {}),
            ),
            DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
            CAKE_CUSTOMIZATION_GROUP_SPECS,
        )
    )


def _get_package_storefront_options(package):
    return _build_storefront_option_groups(
        _filter_removed_package_cake_decorations(
            getattr(package, 'customization_options', {}),
        ),
        {},
        PACKAGE_CUSTOMIZATION_GROUP_SPECS,
    )


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


def _send_registration_confirmation_email(request, user):
    if not user.email:
        return

    login_url = request.build_absolute_uri(reverse('login'))
    profile_url = request.build_absolute_uri(reverse('profile'))
    contact_url = request.build_absolute_uri(reverse('contact'))
    full_name = user.get_full_name().strip() or user.username

    send_mail(
        'Welcome to Hanilies Cakeshoppe',
        (
            f'Hello {full_name},\n\n'
            'Your Hanilies Cakeshoppe customer account has been created successfully. '
            'You can now sign in, manage your profile, and place cake or package orders online.\n\n'
            f'Login: {login_url}\n'
            f'Profile: {profile_url}\n'
            f'Contact us: {contact_url}\n\n'
            'Thank you for registering with Hanilies Cakeshoppe.'
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


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
            f'{_get_order_product_summary(order)}'
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
            f'{_get_order_product_summary(order)}'
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


def _get_password_validation_errors(password, user=None):
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        return error.messages
    return []


def _build_login_throttle_cache_prefix(request, username):
    forwarded_for = str(request.META.get('HTTP_X_FORWARDED_FOR', '') or '')
    client_ip = forwarded_for.split(',')[0].strip() or str(
        request.META.get('REMOTE_ADDR', '') or 'unknown')
    normalized_username = (username or '').strip().lower() or 'unknown'
    digest = hashlib.sha256(
        f'{client_ip}|{normalized_username}'.encode('utf-8')
    ).hexdigest()
    return f'login-throttle:{digest}'


def _get_login_throttle_keys(request, username):
    cache_prefix = _build_login_throttle_cache_prefix(request, username)
    return f'{cache_prefix}:count', f'{cache_prefix}:lock'


def _clear_login_throttle(request, username):
    count_key, lock_key = _get_login_throttle_keys(request, username)
    cache.delete_many([count_key, lock_key])


def _get_login_lockout_remaining(request, username):
    _, lock_key = _get_login_throttle_keys(request, username)
    lock_expires_at = cache.get(lock_key)
    if not lock_expires_at:
        return 0

    remaining_seconds = int(lock_expires_at - time.time())
    if remaining_seconds <= 0:
        cache.delete(lock_key)
        return 0
    return remaining_seconds


def _record_failed_login_attempt(request, username):
    count_key, lock_key = _get_login_throttle_keys(request, username)
    failure_limit = max(1, int(getattr(settings, 'LOGIN_FAILURE_LIMIT', 5)))
    lockout_seconds = max(
        1, int(getattr(settings, 'LOGIN_LOCKOUT_SECONDS', 900)))
    failure_count = int(cache.get(count_key, 0)) + 1

    if failure_count >= failure_limit:
        cache.set(lock_key, time.time() + lockout_seconds, lockout_seconds)
        cache.delete(count_key)
        return lockout_seconds

    cache.set(count_key, failure_count, lockout_seconds)
    return 0


def _build_login_lockout_message(remaining_seconds):
    if remaining_seconds < 60:
        return (
            'Too many failed login attempts. Please try again in '
            f'{remaining_seconds} seconds.'
        )

    remaining_minutes = (remaining_seconds + 59) // 60
    minute_label = 'minute' if remaining_minutes == 1 else 'minutes'
    return (
        'Too many failed login attempts. Please try again in '
        f'{remaining_minutes} {minute_label}.'
    )


class HaniliesPasswordResetRequestView(PasswordResetView):
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'
    form_class = HaniliesPasswordResetForm
    success_url = reverse_lazy('password_reset_done')

    def form_valid(self, form):
        matching_users = list(form.get_users(form.cleaned_data['email']))

        for user in matching_users:
            _log_staff_activity(
                user,
                'Password reset requested',
                'Password reset instructions were requested for this account.',
                target_type='User',
                target_id=user.id,
            )

        return super().form_valid(form)


class HaniliesPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'registration/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['confirmation_message'] = (
            'Password reset instructions have been sent if the email is registered.'
        )
        return context


class HaniliesPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'registration/password_reset_confirm.html'
    form_class = HaniliesSetPasswordForm
    success_url = reverse_lazy('login')

    def form_valid(self, form):
        response = super().form_valid(form)
        _log_staff_activity(
            form.user,
            'Password reset completed',
            'Password was successfully reset using the password reset link.',
            target_type='User',
            target_id=form.user.id,
        )
        messages.success(
            self.request,
            'Password successfully reset. You may now log in.',
        )
        return response


def _get_payment_qr_reference_seed(request=None):
    if request is None:
        return 'public-preview'
    if not request.session.session_key:
        request.session.create()
    return f'user:{request.user.pk}|session:{request.session.session_key}'


def _build_checkout_gcash_preview(request, amount, order_label):
    reference_seed = _get_payment_qr_reference_seed(request)
    return build_gcash_checkout_details(
        amount,
        order_label,
        reference_seed=reference_seed,
    )


def _build_payment_qr_response(amount, order_label, reference_seed=''):
    preview = build_gcash_checkout_details(
        amount,
        order_label,
        reference_seed=reference_seed,
    )
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
    return JsonResponse(
        _build_payment_qr_response(
            amount,
            order_label,
            reference_seed=_get_payment_qr_reference_seed(request),
        )
    )


def _is_local_demo_request(request):
    remote_addr = request.META.get('REMOTE_ADDR')
    return settings.DEBUG and remote_addr in {None, '127.0.0.1', '::1'}


def _get_demo_request_mode(request):
    if _is_local_demo_request(request) or getattr(settings, 'DEMO_BOT_REMOTE_ENABLED', False):
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


def _normalize_demo_script_steps(raw_steps):
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
        return _normalize_demo_script_steps(raw_steps)
    return list(DEMO_BROWSER_SCENARIO_STEPS.get(scenario, DEMO_BROWSER_SCENARIO_STEPS['full']))


def _ensure_demo_admin_user():
    user, created = User.objects.get_or_create(
        username=DEMO_BROWSER_ADMIN_USERNAME,
        defaults={
            'email': DEMO_BROWSER_ADMIN_EMAIL,
            'first_name': 'Panel',
            'last_name': 'Admin',
        },
    )
    if created or not user.check_password(DEMO_BROWSER_ADMIN_PASSWORD):
        user.email = DEMO_BROWSER_ADMIN_EMAIL
        user.first_name = 'Panel'
        user.last_name = 'Admin'
        user.set_password(DEMO_BROWSER_ADMIN_PASSWORD)
        user.save()

    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            'role': 'admin',
            'phone': '09171234567',
            'address': 'Hanilies Admin Office, Lucena City',
        },
    )
    profile.role = 'admin'
    if not profile.phone:
        profile.phone = '09171234567'
    if not profile.address:
        profile.address = 'Hanilies Admin Office, Lucena City'
    profile.save()
    _sync_user_staff_flags(user, profile.role)
    return user


def _ensure_demo_showcase_catalog():
    cake = _get_public_cake_queryset().exclude(image='').order_by('-updated_at', '-id').first()
    if cake is None:
        cake = _get_public_cake_queryset().order_by('-updated_at', '-id').first()
    if cake is None:
        cake = Cake.objects.create(
            name='Demo Bot Showcase Cake',
            category='birthday',
            description='Auto-created showcase cake for the browser demo flow.',
            price=Decimal('1850.00'),
            stock=5,
            is_active=True,
        )

    package = _get_public_package_queryset().exclude(image='').order_by('-updated_at', '-id').first()
    if package is None:
        package = _get_public_package_queryset().order_by('-updated_at', '-id').first()
    if package is None:
        package = Package.objects.create(
            name='Demo Bot Showcase Package',
            package_type='kids_birthday',
            description='Auto-created showcase package for the browser demo flow.',
            base_price=Decimal('7500.00'),
            features='Host\nBackdrop\nBasic styling',
            included_items='Cake\nCupcakes\nBalloons',
            status='active',
        )

    return cake, package


def _build_browser_demo_payload(request, scenario, script_steps, delay):
    demo_admin = _ensure_demo_admin_user()
    showcase_cake, showcase_package = _ensure_demo_showcase_catalog()
    cake_catalog_url = f"{reverse('cakes')}?category={showcase_cake.category}"
    cake_customize_url = f"{reverse('cake_customize')}?cake_id={showcase_cake.id}"
    package_catalog_url = f"{reverse('packages')}?type={showcase_package.package_type}"
    package_order_url = f"{reverse('order_package')}?package_id={showcase_package.id}"
    package_payment_url = reverse('package_payment')
    home_url = reverse('home')
    login_url = reverse('login')
    logout_url = reverse('logout')
    customer_orders_url = f"{reverse('profile')}?section=orders"
    profile_url = f"{reverse('profile')}?section=profile&tab=personal#profile-edit-card"

    step_urls = {
        'home': home_url,
        'intro': home_url,
        'homepage': home_url,
        'register': reverse('register'),
        'login': login_url,
        'customer_login': login_url,
        'logout': logout_url,
        'cakes': cake_catalog_url,
        'cake_browse': cake_catalog_url,
        'cake_customize': cake_customize_url,
        'packages': package_catalog_url,
        'package_browse': package_catalog_url,
        'package_order': package_order_url,
        'package_customize': package_order_url,
        'package_payment': package_payment_url,
        'cart_review': package_payment_url,
        'checkout': package_payment_url,
        'payment': package_payment_url,
        'customer_orders': customer_orders_url,
        'profile': profile_url,
        'order_tracking': reverse('order_tracking'),
        'admin_login': login_url,
        'admin_dashboard': reverse('admin_dashboard'),
        'admin_cake_orders': reverse('admin_cake_orders'),
        'admin_package_orders': reverse('admin_package_orders'),
        'admin_payments': reverse('admin_payments'),
        'admin_cakes': reverse('admin_cakes'),
        'admin_packages': reverse('admin_packages'),
        'admin_users': reverse('admin_users'),
        'audit_trail': reverse('admin_activity_logs'),
        'admin_logout': logout_url,
    }
    return {
        'scenario': scenario,
        'script_steps': script_steps,
        'launch_url': home_url,
        'step_urls': step_urls,
        'delay': delay,
        'intro_message': DEMO_BOT_DEFAULT_INTRO,
        'admin_credentials': {
            'username': demo_admin.username,
            'password': DEMO_BROWSER_ADMIN_PASSWORD,
        },
        'sample_customer': {
            'first_name': 'Presentation',
            'last_name': 'Customer',
            'email_domain': 'example.com',
            'phone': '09171234567',
            'password': 'DemoRegister123!',
        },
        'showcase_catalog': {
            'cake_id': showcase_cake.id,
            'cake_name': showcase_cake.name,
            'cake_category': showcase_cake.category,
            'package_id': showcase_package.id,
            'package_name': showcase_package.name,
            'package_type': showcase_package.package_type,
        },
    }


@require_POST
def start_demo_bot(request):
    if _get_demo_request_mode(request) is None:
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

    if _get_demo_state(request):
        return JsonResponse({
            'ok': False,
            'error': 'A demo bot is already running. Stop it before starting another one.',
            'active_demo': _get_demo_state(request),
        }, status=409)

    delay = max(0.6, _parse_float(payload.get('delay'), 1.1))
    resolved_steps = _resolve_demo_script_steps(
        scenario,
        payload.get('script_steps', []),
    )
    if scenario == 'custom' and not resolved_steps:
        return JsonResponse({
            'ok': False,
            'error': 'Choose at least one custom script step before starting the demo.',
        }, status=400)

    browser_demo = _build_browser_demo_payload(
        request,
        scenario,
        resolved_steps,
        delay,
    )
    state = {
        'mode': 'browser',
        'scenario': scenario,
        'script_steps': resolved_steps,
        'started_at': timezone.now().isoformat(),
        'delay': delay,
    }
    _set_demo_state(request, state)
    return JsonResponse({
        'ok': True,
        'mode': 'browser',
        'scenario': scenario,
        'active_demo': state,
        'browser_demo': browser_demo,
        'message': 'The browser demo is prepared. This tab will now run the presentation walkthrough automatically.',
    })


def demo_bot_status(request):
    if _get_demo_request_mode(request) is None:
        return JsonResponse({'ok': False, 'error': 'Demo bot access is not enabled here.'}, status=403)

    state = _get_demo_state(request)
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

    _clear_demo_state(request)
    return JsonResponse({
        'ok': True,
        'message': 'The browser-based demo walkthrough was stopped.',
    })

def _build_tracking_steps(order_kind, order_status):
    if order_kind == 'package':
        flow = [
            ('pending', 'Pending Approval',
             'Your package order has been received and is awaiting payment approval.'),
            ('payment_retry', 'Awaiting Payment Resubmission',
             'Please upload a new valid proof of payment so your package booking can continue.'),
            ('confirmed', 'Order Confirmed',
             'Your event package order and details are confirmed.'),
            ('preparing', 'Preparation Ongoing',
             'Your package inclusions and cake are being prepared.'),
            ('ready_for_pickup', 'Ready for Pickup',
             'Your package is ready for pickup or dispatch.'),
            ('out_for_delivery', 'Out for Delivery',
             'Your package order is already on the way.'),
            ('completed', 'Completed', 'Your package order has been completed.'),
        ]
    else:
        flow = [
            ('pending', 'Pending Approval',
             'Your cake order has been received and is awaiting payment approval.'),
            ('payment_retry', 'Awaiting Payment Resubmission',
             'Please upload a new valid proof of payment so your cake order can continue.'),
            ('confirmed', 'Order Confirmed', 'Your cake order is confirmed.'),
            ('preparing', 'Preparing Cake',
             'The baking team is preparing your order.'),
            ('ready_for_pickup', 'Ready for Pickup',
             'Your cake is ready for pickup or release.'),
            ('out_for_delivery', 'Out for Delivery',
             'Your order is already on the way.'),
            ('completed', 'Completed', 'Your order has been completed.'),
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

    cake_orders = _get_customer_cake_orders_queryset(user)
    package_orders = _get_customer_package_orders_queryset(user)
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
    cakes = list(_get_public_cake_queryset().annotate(
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
    top_cake = _get_public_cake_queryset().annotate(
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
        {'value': _get_public_cake_queryset().count(), 'label': 'Active Cakes'},
        {'value': _get_public_package_queryset().count(), 'label': 'Live Packages'},
        {'value': CakeOrder.objects.count() + PackageOrder.objects.count(),
         'label': 'Orders Logged'},
    ]


def _build_home_hero_collage():
    uploaded_images = list(
        HomeHeroImage.objects.filter(is_active=True).order_by(
            'display_order', 'id')[:4]
    )
    if uploaded_images:
        return [
            {
                'image_url': hero_image.image.url,
                'title': hero_image.title,
            }
            for hero_image in uploaded_images
            if hero_image.image
        ]

    fallback_images = []
    fallback_cakes = _get_public_cake_queryset().exclude(
        Q(image='') | Q(image__isnull=True)
    ).order_by('name')[:2]
    fallback_packages = _get_public_package_queryset().exclude(
        Q(image='') | Q(image__isnull=True)
    ).order_by('name')[:2]

    for cake in fallback_cakes:
        fallback_images.append({
            'image_url': cake.image.url,
            'title': cake.name,
        })
    for package in fallback_packages:
        fallback_images.append({
            'image_url': package.image.url,
            'title': package.name,
        })

    return fallback_images[:4]


def _build_home_strip_image():
    strip_image = HomeStripImage.objects.filter(
        is_active=True,
    ).order_by('display_order', 'id').first()

    if not strip_image or not strip_image.image:
        return None

    return {
        'image_url': strip_image.image.url,
        'title': strip_image.title,
    }


def _get_homepage_testimonials(limit=3):
    return list(
        Testimonial.objects.select_related(
            'cake_order__cake',
            'package_order__package',
        ).filter(
            status=Testimonial.STATUS_APPROVED,
            is_archived=False,
        ).order_by('-reviewed_at', '-created_at')[:limit]
    )


def _get_order_testimonial(order_type, order):
    if order is None:
        return None

    if order_type == 'cake':
        return Testimonial.objects.select_related(
            'reviewed_by',
            'cake_order__cake',
        ).filter(cake_order=order).first()

    return Testimonial.objects.select_related(
        'reviewed_by',
        'package_order__package',
    ).filter(package_order=order).first()


def _can_submit_testimonial(order, testimonial=None):
    if order is None or order.order_status != 'completed':
        return False

    if testimonial is None:
        return True

    return testimonial.status == Testimonial.STATUS_REJECTED and not testimonial.is_archived


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
    featured_cakes = list(_get_public_cake_queryset().annotate(
        order_count=Count('orders')).order_by('-order_count', 'name')[:4])
    featured_packages = list(_get_public_package_queryset().annotate(
        order_count=Count('orders')).order_by('-order_count', 'name')[:3])

    context = {
        'hero_collage_images': _build_home_hero_collage(),
        'home_strip_image': _build_home_strip_image(),
        'hero_stats': _build_home_stats(),
        'recommendation_headline': recommendation_profile['headline'],
        'recommendation_subheadline': recommendation_profile['subheadline'],
        'recommendation_profile': recommendation_profile,
        'recommended_cakes': recommended_cakes,
        'recommended_packages': recommended_packages,
        'featured_cakes': featured_cakes,
        'featured_packages': featured_packages,
        'home_insights': _build_home_insights(recommendation_profile),
        'homepage_testimonials': _get_homepage_testimonials(),
    }
    return render(request, 'hanilies/home.html', context)


def about(request):
    """About page"""
    about_images = _build_about_page_image_context()
    team_members = [
        {
            'name': 'Teresa Rabillas',
            'role': 'Founder & Head Baker',
            'image': about_images[AboutPageImage.SLOT_TEAM_TERESA],
        },
        {
            'name': 'Maria Santos',
            'role': 'Head Baker',
            'image': about_images[AboutPageImage.SLOT_TEAM_MARIA],
        },
        {
            'name': 'John Reyes',
            'role': 'Sales Manager',
            'image': about_images[AboutPageImage.SLOT_TEAM_JOHN],
        },
        {
            'name': 'Anna Lim',
            'role': 'Customer Service',
            'image': about_images[AboutPageImage.SLOT_TEAM_ANNA],
        },
    ]
    return render(request, 'hanilies/about.html', {
        'about_story_image': about_images[AboutPageImage.SLOT_STORY],
        'about_team_members': team_members,
    })


def contact(request):
    """Public contact page with inquiry form."""
    initial = {}
    if request.user.is_authenticated:
        full_name = request.user.get_full_name().strip()
        initial['name'] = full_name or request.user.username
        contact_detail = request.user.email
        profile = getattr(request.user, 'profile', None)
        if profile and profile.phone:
            contact_detail = profile.phone or contact_detail
        if contact_detail:
            initial['contact_detail'] = contact_detail

    if request.method == 'POST':
        form = ContactInquiryForm(request.POST)
        if form.is_valid():
            ContactInquiry.objects.create(
                user=request.user if request.user.is_authenticated else None,
                name=form.cleaned_data['name'],
                contact_detail=form.cleaned_data['contact_detail'],
                message=form.cleaned_data['message'],
            )
            messages.success(
                request,
                'Thank you for your message. Hanilies Cakeshoppe will review it and get back to you soon.',
            )
            return redirect(f"{reverse('contact')}?sent=1#contact-form")
    else:
        form = ContactInquiryForm(initial=initial)

    return render(request, 'hanilies/contact.html', {
        'form': form,
        'contact_success': request.GET.get('sent') == '1',
    })


def cakes(request):
    """Cakes listing page"""
    cake_list = _get_public_cake_queryset().order_by('name')
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
    package_list = _get_public_package_queryset(
    ).prefetch_related('thumbnails').order_by('name')
    selected_type = request.GET.get('type', '').strip()
    search_term = request.GET.get('q', '').strip()

    if selected_type:
        package_list = package_list.filter(package_type=selected_type)
    if search_term:
        package_list = package_list.filter(
            Q(name__icontains=search_term) | Q(description__icontains=search_term))

    package_list = list(package_list)
    for package in package_list:
        package.package_inclusion_items = _get_package_inclusion_items(package)

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
    if request.user.is_authenticated:
        return _redirect_authenticated_user(request.user)

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        lockout_remaining = _get_login_lockout_remaining(request, username)
        if lockout_remaining:
            return render(request, 'hanilies/login.html', {
                'error': _build_login_lockout_message(lockout_remaining),
            })

        user = authenticate(request, username=username, password=password)

        if user is not None:
            _clear_login_throttle(request, username)
            login(request, user)
            _log_staff_activity(
                user,
                'User login',
                f'User "{user.username}" logged in.',
                'user',
                user.id,
            )
            return _redirect_authenticated_user(user)
        else:
            lockout_seconds = _record_failed_login_attempt(request, username)
            error_message = (
                _build_login_lockout_message(lockout_seconds)
                if lockout_seconds
                else 'Invalid username or password'
            )
            return render(request, 'hanilies/login.html', {'error': error_message})

    return render(request, 'hanilies/login.html')


def register_view(request):
    """User registration page"""
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''
        firstname = (request.POST.get('firstname') or '').strip()
        lastname = (request.POST.get('lastname') or '').strip()
        phone = (request.POST.get('phone') or '').strip()

        if password != confirm_password:
            return render(request, 'hanilies/register.html', {'error': 'Passwords do not match'})

        if User.objects.filter(username=username).exists():
            return render(request, 'hanilies/register.html', {'error': 'Username already exists'})

        if User.objects.filter(email=email).exists():
            return render(request, 'hanilies/register.html', {'error': 'Email already registered'})

        candidate_user = User(
            username=username,
            email=email,
            first_name=firstname,
            last_name=lastname,
        )
        password_errors = _get_password_validation_errors(
            password, user=candidate_user)
        if password_errors:
            return render(request, 'hanilies/register.html', {'error': ' '.join(password_errors)})

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
        _send_registration_confirmation_email(request, user)

        login(request, user)
        messages.success(
            request, 'Registration successful! Welcome to Hanilies Cakeshoppe!')
        return redirect('profile')

    return render(request, 'hanilies/register.html')


def logout_view(request):
    """Log out user"""
    logged_out_user = request.user if request.user.is_authenticated else None
    storage = messages.get_messages(request)
    storage.used = True
    if logged_out_user is not None:
        _log_staff_activity(
            logged_out_user,
            'User logout',
            f'User "{logged_out_user.username}" logged out.',
            'user',
            logged_out_user.id,
        )
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

    allowed_sections = {'profile', 'orders', 'notifications'}
    allowed_tabs = {'personal', 'password', 'preferences'}
    active_profile_section = request.GET.get('section', 'profile')
    active_profile_tab = request.GET.get('tab', 'personal')

    if active_profile_section not in allowed_sections:
        active_profile_section = 'profile'
    if active_profile_tab not in allowed_tabs:
        active_profile_tab = 'personal'

    def build_profile_url(section='profile', tab='personal'):
        query = {'section': section if section in allowed_sections else 'profile'}
        if query['section'] == 'profile':
            query['tab'] = tab if tab in allowed_tabs else 'personal'
        return f"{reverse('profile')}?{urlencode(query)}"

    profile_defaults = _get_profile_defaults(request.user)

    if request.method == 'POST':
        user = request.user
        profile_defaults.update({
            'delivery_street_address': request.POST.get('address_line_1', '').strip(),
            'delivery_barangay': request.POST.get('address_barangay', '').strip(),
            'delivery_city': request.POST.get('address_city', '').strip(),
            'delivery_landmark': request.POST.get('address_landmark', '').strip(),
        })
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)

        address_data, address_error = _validate_structured_delivery_address(
            request.POST.get('address_line_1'),
            request.POST.get('address_barangay'),
            request.POST.get('address_city'),
            request.POST.get('address_landmark'),
            required=False,
        )

        if address_error:
            messages.error(request, address_error)
        else:
            user.save()

            if hasattr(user, 'profile'):
                user.profile.phone = request.POST.get(
                    'phone', user.profile.phone)
                user.profile.address = address_data['delivery_address']
                user.profile.save()

            messages.success(request, 'Profile updated successfully!')
            return redirect(build_profile_url(section='profile', tab='personal'))

    cake_orders = _get_customer_cake_orders_queryset(
        request.user).select_related('cake')
    package_orders = _get_customer_package_orders_queryset(
        request.user).select_related('package')
    total_spent = (
        cake_orders.aggregate(total=Sum('total_price')).get(
            'total') or Decimal('0.00')
    ) + (
        package_orders.aggregate(total=Sum('total_price')).get(
            'total') or Decimal('0.00')
    )
    recent_orders = sorted(
        [
            {
                'order_type': 'cake',
                'order': order,
                'title': order.cake.name if order.cake else 'Custom Cake',
                'schedule_label': order.delivery_date,
            }
            for order in cake_orders[:3]
        ] + [
            {
                'order_type': 'package',
                'order': order,
                'title': order.package.name if order.package else 'Custom Package',
                'schedule_label': order.event_date,
            }
            for order in package_orders[:3]
        ],
        key=lambda item: item['order'].created_at,
        reverse=True,
    )[:5]
    recent_notifications = list(
        Notification.objects.filter(user=request.user).select_related(
            'cake_order', 'package_order', 'payment'
        )[:6]
    )
    context = {
        'order_count': cake_orders.count() + package_orders.count(),
        'total_spent': total_spent,
        'profile_defaults': profile_defaults,
        'delivery_area_choices': DELIVERY_SERVICE_AREA_CHOICES,
        'recent_orders': recent_orders,
        'recent_notifications': recent_notifications,
        'unread_notification_count': sum(
            1 for notification in recent_notifications if not notification.is_read),
        'active_profile_section': active_profile_section,
        'active_profile_tab': active_profile_tab,
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
        profile_password_url = f"{reverse('profile')}?{urlencode({'section': 'profile', 'tab': 'password'})}"

        if not user.check_password(current_password):
            messages.error(request, 'Current password is incorrect')
            return redirect(profile_password_url)

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match')
            return redirect(profile_password_url)

        password_errors = _get_password_validation_errors(
            new_password, user=user)
        if password_errors:
            for password_error in password_errors:
                messages.error(request, password_error)
            return redirect(profile_password_url)

        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user)

        messages.success(request, 'Password changed successfully!')
        return redirect(profile_password_url)

    return redirect(f"{reverse('profile')}?{urlencode({'section': 'profile', 'tab': 'password'})}")


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
        return redirect(f"{reverse('profile')}?{urlencode({'section': 'profile', 'tab': 'preferences'})}")

    return redirect(f"{reverse('profile')}?{urlencode({'section': 'profile', 'tab': 'preferences'})}")


@login_required
def order_tracking(request):
    """Track order status"""
    cake_orders = list(
        _get_customer_cake_orders_queryset(request.user).select_related(
            'cake').prefetch_related('payments').order_by('-created_at')
    )
    package_orders = list(
        _get_customer_package_orders_queryset(request.user).select_related(
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
    selected_testimonial = None
    can_submit_testimonial = False
    if selected_order is not None:
        selected_payments = list(_get_order_payments_queryset(selected_order))
        selected_payment = _get_order_primary_payment(selected_order)
        if selected_type == 'cake':
            selected_customization = getattr(
                selected_order, 'customization', None)
        selected_refund_request = getattr(
            selected_order, 'refund_request', None)
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
        selected_testimonial = _get_order_testimonial(
            selected_type, selected_order)
        can_submit_testimonial = _can_submit_testimonial(
            selected_order, selected_testimonial)

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
        'selected_testimonial': selected_testimonial,
        'can_submit_testimonial': can_submit_testimonial,
    }
    return render(request, 'hanilies/order_tracking.html', context)


@login_required
def order_tracking_print(request, order_type, order_id):
    order = get_object_or_404(
        _get_customer_order_queryset(request.user, order_type),
        id=order_id,
    )
    selected_payment = _get_order_primary_payment(order)
    selected_payments = list(_get_order_payments_queryset(order))
    selected_customization = None
    if order_type == 'cake':
        selected_customization = getattr(order, 'customization', None)

    context = {
        'selected_order': order,
        'selected_order_type': order_type,
        'selected_payment': selected_payment,
        'selected_payments': selected_payments,
        'selected_customization': selected_customization,
        'selected_refund_request': getattr(order, 'refund_request', None),
        'tracking_url': f"{reverse('order_tracking')}?type={order_type}&id={order.id}",
    }
    return render(request, 'hanilies/order_tracking_print.html', context)


@login_required
@require_POST
def submit_testimonial(request, order_type, order_id):
    order = get_object_or_404(
        _get_customer_order_queryset(request.user, order_type),
        id=order_id,
    )
    tracking_url = f"{reverse('order_tracking')}?type={order_type}&id={order.id}"

    if order.order_status != 'completed':
        messages.error(
            request, 'Testimonials can only be submitted after the order is completed.')
        return redirect(tracking_url)

    message = (request.POST.get('message') or '').strip()
    rating_raw = (request.POST.get('rating') or '').strip()

    if not message:
        messages.error(request, 'Please write a short testimonial message.')
        return redirect(tracking_url)

    try:
        rating = int(rating_raw)
    except (TypeError, ValueError):
        rating = 0

    if rating < 1 or rating > 5:
        messages.error(request, 'Please choose a rating from 1 to 5 stars.')
        return redirect(tracking_url)

    testimonial = _get_order_testimonial(order_type, order)
    if testimonial is not None:
        if testimonial.is_archived:
            messages.info(
                request, 'A testimonial record for this order was archived. Please contact the shop if it needs to be reviewed again.')
            return redirect(tracking_url)

        if testimonial.status != Testimonial.STATUS_REJECTED:
            messages.info(
                request, 'A testimonial for this order is already on file.')
            return redirect(tracking_url)

    customer_name = (
        str(order.contact_name or '').strip()
        or request.user.get_full_name().strip()
        or request.user.username
    )

    if testimonial is None:
        testimonial = Testimonial.objects.create(
            user=request.user,
            cake_order=order if order_type == 'cake' else None,
            package_order=order if order_type == 'package' else None,
            customer_name=customer_name,
            rating=rating,
            message=message,
            status=Testimonial.STATUS_PENDING,
        )
        activity_action = 'testimonial_submitted'
        activity_description = (
            f'Submitted testimonial #{testimonial.id} for {_get_order_label(order)} #{order.id}.'
        )
    else:
        testimonial.user = request.user
        testimonial.customer_name = customer_name
        testimonial.rating = rating
        testimonial.message = message
        testimonial.status = Testimonial.STATUS_PENDING
        testimonial.admin_note = ''
        testimonial.reviewed_by = None
        testimonial.reviewed_at = None
        testimonial.save(update_fields=[
            'user',
            'customer_name',
            'rating',
            'message',
            'status',
            'admin_note',
            'reviewed_by',
            'reviewed_at',
            'updated_at',
        ])
        activity_action = 'testimonial_resubmitted'
        activity_description = (
            f'Resubmitted testimonial #{testimonial.id} for {_get_order_label(order)} #{order.id}.'
        )

    actor_role = request.user.profile.get_role_display() if hasattr(
        request.user, 'profile') else 'Customer'
    ActivityLog.objects.create(
        actor=request.user,
        actor_role=actor_role,
        action=activity_action,
        target_type='testimonial',
        target_id=testimonial.id,
        description=activity_description,
    )
    messages.success(
        request, 'Thank you. Your testimonial has been submitted for admin review.')
    return redirect(tracking_url)


@login_required
@require_POST
def resubmit_payment_proof(request, order_type, order_id, payment_id):
    if order_type == 'cake':
        order = get_object_or_404(
            _get_customer_cake_orders_queryset(request.user), id=order_id)
    elif order_type == 'package':
        order = get_object_or_404(
            _get_customer_package_orders_queryset(request.user), id=order_id)
    else:
        raise PermissionDenied

    payment = get_object_or_404(
        _get_order_payments_queryset(order),
        id=payment_id,
        payment_method='gcash',
        payment_purpose__in=['deposit', 'full'],
    )
    tracking_url = f"{reverse('order_tracking')}?type={order_type}&id={order.id}"

    if payment.payment_status != 'rejected' or order.order_status != 'payment_retry':
        messages.error(request, 'This payment is not awaiting resubmission.')
        return redirect(tracking_url)

    reference_number = request.POST.get('reference_number', '').strip()
    submitted_amount = request.POST.get('payment_amount', '').strip()
    proof_image = request.FILES.get('proof_image')
    normalized_reference, payment_error = _validate_checkout_payment_submission(
        reference_number,
        proof_image,
        payment.amount,
        submitted_amount=submitted_amount,
        exclude_payment_id=payment.id,
    )
    if payment_error:
        messages.error(request, payment_error)
        return redirect(tracking_url)

    previous_status = payment.payment_status
    if payment.proof_image:
        payment.proof_image.delete(save=False)
    payment.proof_image = proof_image
    payment.payment_status = 'verifying'
    payment.paid_at = None
    payment.notes = 'Customer resubmitted proof of payment for review.'
    payment.save(update_fields=['proof_image', 'payment_status',
                 'paid_at', 'notes', 'updated_at'])
    _create_payment_status_notification(payment, previous_status)
    _set_order_pending_after_resubmission(order)

    messages.success(
        request, 'Payment submitted successfully. Please wait for verification.')
    return redirect(tracking_url)


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
        messages.info(
            request, 'A cancellation request for this order is already on file.')
        return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")

    cancellation_quote = _build_cancellation_quote(order_type, order)
    if not cancellation_quote.get('allowed'):
        messages.error(request, cancellation_quote.get(
            'reason', 'This order cannot be cancelled at the moment.'))
        return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")

    reason = request.POST.get('reason', '').strip()
    if not reason:
        messages.error(
            request, 'Please provide a reason for the cancellation request.')
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
    messages.success(
        request, 'Your cancellation request has been submitted for admin review.')
    return redirect(f"{reverse('order_tracking')}?type={order_type}&id={order.id}")


@login_required
def cake_customize(request):
    """Customize a cake"""
    selected_cake_id = request.POST.get(
        'cake_id') if request.method == 'POST' else request.GET.get('cake_id')
    cake_queryset = _get_public_cake_queryset()
    if not cake_queryset.exists():
        messages.error(
            request, 'No active cakes are available yet. Please add cakes from the admin panel first.')
        return redirect('cakes')

    selected_cake = get_object_or_404(
        cake_queryset, id=selected_cake_id) if selected_cake_id else cake_queryset.order_by('name').first()
    cake_option_groups = _get_cake_storefront_options(selected_cake)
    cake_tier_options = cake_option_groups['sizes']
    cake_size_options = cake_option_groups['cake_sizes']
    show_cake_size_options = cake_size_options != cake_tier_options
    cake_size_selection_options = cake_tier_options
    if show_cake_size_options:
        cake_size_selection_options = _merge_option_item_lists(
            cake_tier_options,
            cake_size_options,
            'select',
        )
    theme_options = _get_cake_theme_options_for_category(
        selected_cake.category)
    decoration_option_lookup = _build_checkbox_option_lookup(
        cake_option_groups['decorations'])
    defaults = _get_profile_defaults(request.user)
    defaults.setdefault('delivery_date', '')
    cake_order_window = build_cake_booking_window()
    selected_payment_method = 'cod'
    default_cake_tier_option = _get_default_option(cake_tier_options)
    default_cake_size_option = _get_default_option(cake_size_options)
    default_cake_shape_option = _get_default_option(cake_option_groups['shapes'])
    default_cake_flavor_option = _get_default_option(cake_option_groups['flavors'])
    cake_form_values = {
        'quantity': '1',
        'color_palette': '',
        'message_on_cake': '',
        'special_instructions': '',
    }
    selected_cake_tier_value = ''
    selected_cake_size_value = ''
    selected_cake_shape_value = ''
    selected_cake_flavor_value = ''
    selected_cake_frosting_values = []
    selected_cake_filling_values = []
    selected_decoration_values = []

    cake_flow_key = _get_checkout_flow_key('cake', selected_cake.id)
    cake_checkout_meta = _get_or_create_checkout_meta(
        request, cake_flow_key, 'cake')

    if request.method == 'POST':
        defaults.update({
            'contact_name': request.POST.get('contact_name', '').strip(),
            'contact_phone': request.POST.get('contact_phone', '').strip(),
            'contact_email': request.POST.get('contact_email', '').strip(),
            'delivery_date': request.POST.get('delivery_date', '').strip(),
            'delivery_street_address': request.POST.get('delivery_street_address', '').strip(),
            'delivery_barangay': request.POST.get('delivery_barangay', '').strip(),
            'delivery_city': request.POST.get('delivery_city', '').strip(),
            'delivery_landmark': request.POST.get('delivery_landmark', '').strip(),
        })
        cake_form_values.update({
            'quantity': request.POST.get('quantity', '1').strip() or '1',
            'color_palette': request.POST.get('color_palette', '').strip(),
            'message_on_cake': request.POST.get('message_on_cake', '').strip(),
            'special_instructions': request.POST.get('special_instructions', '').strip(),
        })
        selected_cake_tier_value = request.POST.get('tier', '').strip()
        selected_cake_size_value = request.POST.get('size', '').strip()
        selected_cake_shape_value = request.POST.get('shape', '').strip()
        selected_cake_flavor_value = request.POST.get('flavor', '').strip()
        selected_cake_frosting_values = request.POST.getlist('frosting')
        selected_cake_filling_values = request.POST.getlist('filling')
        selected_decoration_values = request.POST.getlist('decorations')
        quantity = max(int(cake_form_values['quantity'] or 1), 1)
        selected_decorations = selected_decoration_values
        decoration_labels, decoration_total = _get_selected_option_labels(
            selected_decorations, decoration_option_lookup)
        selected_tier = _resolve_selected_option(
            selected_cake_tier_value, cake_tier_options) if selected_cake_tier_value else None
        effective_tier = selected_tier or default_cake_tier_option
        selected_size = _resolve_selected_option(
            selected_cake_size_value, cake_size_options) if selected_cake_size_value and show_cake_size_options else None
        effective_size = selected_size or default_cake_size_option
        selected_shape = _resolve_selected_option(
            selected_cake_shape_value, cake_option_groups['shapes']) if selected_cake_shape_value else None
        effective_shape = selected_shape or default_cake_shape_option
        selected_flavor = _resolve_selected_option(
            selected_cake_flavor_value, cake_option_groups['flavors']) if selected_cake_flavor_value else None
        effective_flavor = selected_flavor or default_cake_flavor_option
        selected_frostings, frosting_total = _get_selected_options(
            selected_cake_frosting_values, cake_option_groups['frostings'])
        selected_fillings, filling_total = _get_selected_options(
            selected_cake_filling_values, cake_option_groups['fillings'])
        customization_total = sum(
            [
                _get_single_select_price_adjustment(selected_tier, cake_tier_options),
                _get_single_select_price_adjustment(selected_size, cake_size_options),
                _get_single_select_price_adjustment(selected_shape, cake_option_groups['shapes']),
                _get_single_select_price_adjustment(selected_flavor, cake_option_groups['flavors']),
            ]
        ) + frosting_total + filling_total
        total_price = (selected_cake.price * quantity) + \
            customization_total + decoration_total
        payment_method = request.POST.get('payment_method', 'cod')
        deposit_amount, balance_due = _calculate_deposit_breakdown(total_price)
        reference_number = request.POST.get('reference_number', '').strip()
        submitted_amount = request.POST.get('payment_amount', '').strip()
        proof_image = request.FILES.get('proof_image')
        delivery_date_value = request.POST.get('delivery_date', '').strip()
        expected_payment_amount = total_price if payment_method == 'gcash' else deposit_amount

        if payment_method not in PAYMENT_PLAN_LABELS:
            payment_method = 'cod'
            expected_payment_amount = deposit_amount

        selected_payment_method = payment_method

        delivery_address_data, address_error = _validate_structured_delivery_address(
            request.POST.get('delivery_street_address'),
            request.POST.get('delivery_barangay'),
            request.POST.get('delivery_city'),
            request.POST.get('delivery_landmark'),
        )
        delivery_date_form = CakeBookingDateForm({
            'delivery_date': delivery_date_value,
        })
        normalized_reference, payment_error = _validate_checkout_payment_submission(
            reference_number,
            proof_image,
            expected_payment_amount,
            submitted_amount=submitted_amount,
        )
        if address_error:
            messages.error(request, address_error)
        elif not delivery_date_form.is_valid():
            messages.error(request, delivery_date_form.non_field_errors()[
                           0] if delivery_date_form.non_field_errors() else delivery_date_form.errors['delivery_date'][0])
        elif payment_error:
            messages.error(request, payment_error)
        else:
            cake_order = CakeOrder.objects.create(
                user=request.user,
                cake=selected_cake,
                quantity=quantity,
                total_price=total_price,
                order_number=cake_checkout_meta['order_number'],
                payment_plan=payment_method,
                deposit_amount=total_price if payment_method == 'gcash' else deposit_amount,
                balance_due=Decimal(
                    '0.00') if payment_method == 'gcash' else balance_due,
                theme=(request.POST.get('theme', '').strip()
                       or theme_options[0]),
                size=_build_cake_size_label(effective_tier, effective_size) or request.POST.get(
                    'size', '').strip(),
                shape=(effective_shape['label'] if effective_shape else request.POST.get(
                    'shape', '').strip()) or 'Round',
                flavor=(effective_flavor['label'] if effective_flavor else request.POST.get(
                    'flavor', '').strip()) or 'Chocolate',
                frosting=_join_selected_option_labels(selected_frostings),
                filling=_join_selected_option_labels(selected_fillings),
                color_palette=cake_form_values['color_palette'],
                message_on_cake=cake_form_values['message_on_cake'],
                special_instructions=cake_form_values['special_instructions'],
                delivery_date=_parse_delivery_datetime(
                    delivery_date_form.cleaned_data['delivery_date'].isoformat()),
                delivery_address=delivery_address_data['delivery_address'],
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
                normalized_reference,
                proof_image,
            )
            _clear_checkout_meta(request, cake_flow_key)
            messages.success(
                request,
                (
                    f'Cake order {cake_order.order_number} was placed successfully. '
                    'Payment submitted successfully. Please wait for verification.'
                ),
            )
            return redirect(f"{reverse('order_tracking')}?type=cake&id={cake_order.id}")

    cake_order_label = f'{selected_cake.name} cake order'
    base_deposit_amount, _ = _calculate_deposit_breakdown(selected_cake.price)
    cake_tier_display_options = _apply_storefront_price_adjustments(
        cake_tier_options,
        use_first_option_as_base=True,
    )
    cake_size_display_options = _apply_storefront_price_adjustments(
        cake_size_options,
        use_first_option_as_base=True,
    )
    cake_shape_display_options = _apply_storefront_price_adjustments(
        cake_option_groups['shapes'],
        use_first_option_as_base=True,
    )
    cake_flavor_display_options = _apply_storefront_price_adjustments(
        cake_option_groups['flavors'],
        use_first_option_as_base=True,
    )
    cake_frosting_display_options = _apply_storefront_price_adjustments(
        cake_option_groups['frostings'],
    )
    cake_filling_display_options = _apply_storefront_price_adjustments(
        cake_option_groups['fillings'],
    )
    decoration_display_options = _apply_storefront_price_adjustments(
        cake_option_groups['decorations'],
    )
    posted_theme = request.POST.get(
        'theme', '').strip() if request.method == 'POST' else ''
    selected_theme = posted_theme if posted_theme in theme_options else (
        theme_options[0] if theme_options else '')
    context = {
        'cake': selected_cake,
        'cakes': cake_queryset.order_by('name'),
        'cake_tier_options': cake_tier_display_options,
        'cake_size_options': cake_size_display_options,
        'show_cake_size_options': show_cake_size_options,
        'cake_shape_options': cake_shape_display_options,
        'cake_flavor_options': cake_flavor_display_options,
        'cake_frosting_options': cake_frosting_display_options,
        'cake_filling_options': cake_filling_display_options,
        'decoration_options': decoration_display_options,
        'theme_options': theme_options,
        'selected_theme': selected_theme,
        'payment_plan_labels': PAYMENT_PLAN_LABELS,
        'selected_payment_method': selected_payment_method,
        'default_deposit_amount': base_deposit_amount,
        'defaults': defaults,
        'cake_form_values': cake_form_values,
        'selected_cake_tier_value': selected_cake_tier_value,
        'selected_cake_size_value': selected_cake_size_value,
        'selected_cake_shape_value': selected_cake_shape_value,
        'selected_cake_flavor_value': selected_cake_flavor_value,
        'default_cake_tier_label': default_cake_tier_option['label'] if default_cake_tier_option else '',
        'default_cake_size_label': default_cake_size_option['label'] if default_cake_size_option else '',
        'default_cake_shape_label': default_cake_shape_option['label'] if default_cake_shape_option else '',
        'default_cake_flavor_label': default_cake_flavor_option['label'] if default_cake_flavor_option else '',
        'selected_cake_frosting_values': selected_cake_frosting_values,
        'selected_cake_filling_values': selected_cake_filling_values,
        'selected_decoration_values': selected_decoration_values,
        'cake_order_window': cake_order_window,
        'delivery_area_choices': DELIVERY_SERVICE_AREA_CHOICES,
        'gcash_account': get_gcash_profile(),
        'gcash_preview': _build_checkout_gcash_preview(
            request,
            base_deposit_amount,
            cake_order_label,
        ),
        'checkout_order_number': cake_checkout_meta['order_number'],
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
    package_option_groups = _get_package_storefront_options(selected_package)
    selected_addon_quantities = draft.get('selected_addon_quantities', {})
    selected_addons = set(draft.get('selected_addons', []))
    selected_inclusion_quantities = draft.get(
        'selected_inclusion_quantities', {})
    selected_inclusions = set(draft.get('selected_inclusions', []))
    addon_options = []
    for option in package_option_groups['addons']:
        option_key = option.get('key')
        option_copy = dict(option)
        selected_quantity = _parse_positive_int(
            selected_addon_quantities.get(option_key),
            default=1 if option_key in selected_addons else 0,
            minimum=0,
        )
        option_copy['selected_quantity'] = selected_quantity
        option_copy['is_selected'] = selected_quantity > 0
        addon_options.append(option_copy)
    addon_option_lookup = _build_checkbox_option_lookup(
        package_option_groups['addons'])
    package_inclusion_items = _get_package_inclusion_items(selected_package)
    included_package_items, optional_package_items = _split_package_inclusion_items(
        package_inclusion_items,
    )
    package_inclusion_options = []
    for item in optional_package_items:
        item_key = item.get('key')
        item_copy = dict(item)
        default_quantity = _parse_positive_int(
            item.get('quantity'), default=1, minimum=1)
        selected_quantity = _parse_positive_int(
            selected_inclusion_quantities.get(item_key),
            default=default_quantity if item_key in selected_inclusions else 0,
            minimum=0,
        )
        item_copy['default_quantity'] = default_quantity
        item_copy['selected_quantity'] = selected_quantity
        item_copy['is_selected'] = selected_quantity > 0
        package_inclusion_options.append(item_copy)

    if request.method == 'POST':
        event_type = selected_package.package_type
        if event_type not in PUBLIC_EVENT_TYPE_VALUES:
            messages.error(
                request, 'Selected event type is no longer available for package bookings.')
            context = {
                'package': selected_package,
                'packages': package_queryset.order_by('name'),
                'event_types': PUBLIC_EVENT_TYPES,
                'included_package_items': included_package_items,
                'package_inclusion_options': package_inclusion_options,
                'addon_options': addon_options,
                'package_inclusion_items': package_inclusion_items,
                'draft': draft,
            }
            return render(request, 'hanilies/package_order.html', context)

        selected_inclusions, selected_inclusion_quantities, inclusion_labels, inclusion_total = _build_selected_package_inclusions(
            request.POST,
            optional_package_items,
        )
        selected_addons, selected_addon_quantities, addon_labels, addon_total = _build_selected_package_addons(
            request.POST,
            addon_option_lookup,
        )
        updated_draft = {
            'package_id': str(selected_package.id),
            'event_type': event_type,
            'selected_inclusions': selected_inclusions,
            'selected_inclusion_quantities': selected_inclusion_quantities,
            'selected_inclusion_labels': inclusion_labels,
            'inclusions_total': str(inclusion_total),
            'selected_addons': selected_addons,
            'selected_addon_quantities': selected_addon_quantities,
            'selected_addon_labels': addon_labels,
            'addons_total': str(addon_total),
            'base_total': str(selected_package.base_price + inclusion_total + addon_total),
        }
        existing_draft = _get_package_draft(request)
        existing_draft.update(updated_draft)
        _set_package_draft(request, existing_draft)
        return redirect('package_cake_customize')

    context = {
        'package': selected_package,
        'packages': package_queryset.order_by('name'),
        'event_types': PUBLIC_EVENT_TYPES,
        'included_package_items': included_package_items,
        'package_inclusion_options': package_inclusion_options,
        'addon_options': addon_options,
        'package_inclusion_items': package_inclusion_items,
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
        _get_public_package_queryset(), id=package_id)
    package_option_groups = _get_package_storefront_options(selected_package)
    decoration_option_lookup = _build_checkbox_option_lookup(
        package_option_groups['cake_decorations'])

    if request.method == 'POST':
        size_key = request.POST.get('cake_size', '')
        selected_decorations = request.POST.getlist('cake_decorations')
        decoration_labels, decoration_total = _get_selected_option_labels(
            selected_decorations, decoration_option_lookup)
        size_option = _resolve_selected_option(
            size_key, package_option_groups['cake_sizes'])
        shape_option = _resolve_selected_option(
            request.POST.get('shape'), package_option_groups['cake_shapes'])
        flavor_option = _resolve_selected_option(
            request.POST.get('flavor'), package_option_groups['cake_flavors'])
        selected_frosting_keys = request.POST.getlist('frosting')
        selected_filling_keys = request.POST.getlist('filling')
        frosting_options, frosting_total = _get_selected_options(
            selected_frosting_keys, package_option_groups['cake_frostings'])
        filling_options, filling_total = _get_selected_options(
            selected_filling_keys, package_option_groups['cake_fillings'])
        cake_custom_total = sum(
            option['price']
            for option in [size_option, shape_option, flavor_option]
            if option
        ) + frosting_total + filling_total + decoration_total

        draft.update({
            'cake_theme': request.POST.get('theme', '').strip(),
            'cake_flavor': flavor_option['label'] if flavor_option else request.POST.get('flavor', '').strip(),
            'cake_frosting': _join_selected_option_labels(frosting_options),
            'cake_filling': _join_selected_option_labels(filling_options),
            'cake_frosting_keys': selected_frosting_keys,
            'cake_filling_keys': selected_filling_keys,
            'cake_size_key': size_option['value'] if size_option else size_key,
            'cake_size_label': size_option['label'] if size_option else size_key,
            'cake_shape': shape_option['label'] if shape_option else request.POST.get('shape', '').strip(),
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
        'size_options': package_option_groups['cake_sizes'],
        'shape_options': package_option_groups['cake_shapes'],
        'flavor_options': package_option_groups['cake_flavors'],
        'frosting_options': package_option_groups['cake_frostings'],
        'filling_options': package_option_groups['cake_fillings'],
        'decoration_options': package_option_groups['cake_decorations'],
        'selected_package_frosting_values': draft.get('cake_frosting_keys') or _split_saved_multi_select_text(draft.get('cake_frosting', '')),
        'selected_package_filling_values': draft.get('cake_filling_keys') or _split_saved_multi_select_text(draft.get('cake_filling', '')),
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
        _get_public_package_queryset(), id=package_id)
    defaults = _get_profile_defaults(request.user)
    package_base_total = _parse_decimal(selected_package.base_price)
    inclusions_total = _parse_decimal(draft.get('inclusions_total', '0.00'))
    addons_total = _parse_decimal(draft.get('addons_total', '0.00'))
    stored_subtotal = _parse_decimal(
        draft.get('base_total', selected_package.base_price))
    subtotal = package_base_total + inclusions_total + addons_total
    if not draft.get('inclusions_total') and not draft.get('addons_total'):
        subtotal = stored_subtotal
    custom_total = _parse_decimal(draft.get('cake_custom_total', '0.00'))
    grand_total = subtotal + custom_total
    deposit_amount, balance_due = _calculate_deposit_breakdown(grand_total)
    package_flow_key = _get_checkout_flow_key('package', package_id)
    package_checkout_meta = _get_or_create_checkout_meta(
        request, package_flow_key, 'package')
    package_order_window = build_package_booking_window()
    form_values = {
        'event_date': '',
        'event_time': '',
        'venue': defaults.get('delivery_address', ''),
        'contact_name': defaults.get('contact_name', ''),
        'contact_phone': defaults.get('contact_phone', ''),
        'contact_email': defaults.get('contact_email', ''),
        'payment_method': 'cod',
    }

    if request.method == 'POST':
        event_type = request.POST.get(
            'event_type', draft.get('event_type', selected_package.package_type))
        payment_method = request.POST.get('payment_method', 'cod')
        reference_number = request.POST.get('reference_number', '').strip()
        submitted_amount = request.POST.get('payment_amount', '').strip()
        proof_image = request.FILES.get('proof_image')
        design_reference = request.FILES.get('design_reference')
        expected_payment_amount = grand_total if payment_method == 'gcash' else deposit_amount
        form_values.update({
            'event_date': request.POST.get('event_date', '').strip(),
            'event_time': request.POST.get('event_time', '').strip(),
            'venue': request.POST.get('venue', '').strip(),
            'contact_name': request.POST.get('contact_name', '').strip(),
            'contact_phone': request.POST.get('contact_phone', '').strip(),
            'contact_email': request.POST.get('contact_email', '').strip(),
            'payment_method': payment_method,
        })

        if payment_method not in PAYMENT_PLAN_LABELS:
            payment_method = 'cod'
            expected_payment_amount = deposit_amount
            form_values['payment_method'] = payment_method

        if event_type not in PUBLIC_EVENT_TYPE_VALUES:
            messages.error(
                request, 'Selected event type is no longer available for package bookings.')
        else:
            normalized_reference, payment_error = _validate_checkout_payment_submission(
                reference_number,
                proof_image,
                expected_payment_amount,
                submitted_amount=submitted_amount,
            )
            design_reference_error = _validate_optional_design_reference_upload(
                design_reference)
            event_date_form = PackageBookingDateForm({
                'event_date': form_values['event_date'],
            })
            if not event_date_form.is_valid():
                messages.error(request, event_date_form.non_field_errors()[
                               0] if event_date_form.non_field_errors() else event_date_form.errors['event_date'][0])
            elif payment_error:
                messages.error(request, payment_error)
            elif design_reference_error:
                messages.error(request, design_reference_error)
            else:
                package_order = PackageOrder.objects.create(
                    user=request.user,
                    package=selected_package,
                    total_price=grand_total,
                    order_number=package_checkout_meta['order_number'],
                    payment_plan=payment_method,
                    deposit_amount=grand_total if payment_method == 'gcash' else deposit_amount,
                    balance_due=Decimal(
                        '0.00') if payment_method == 'gcash' else balance_due,
                    event_type=event_type,
                    event_date=event_date_form.cleaned_data['event_date'],
                    event_time=form_values['event_time'] or None,
                    venue=form_values['venue'],
                    contact_name=form_values['contact_name'],
                    contact_phone=form_values['contact_phone'],
                    contact_email=form_values['contact_email'],
                    selected_addons='\n'.join(
                        [
                            *draft.get('selected_inclusion_labels', []),
                            *draft.get('selected_addon_labels', []),
                        ]),
                    cake_flavor=draft.get('cake_flavor', ''),
                    cake_frosting=draft.get('cake_frosting', ''),
                    cake_filling=draft.get('cake_filling', ''),
                    cake_message=draft.get('cake_message', ''),
                    design_reference=design_reference,
                )

                _create_checkout_payments(
                    package_order,
                    payment_method,
                    normalized_reference,
                    proof_image,
                )

                _clear_checkout_meta(request, package_flow_key)
                _clear_package_draft(request)
                messages.success(
                    request,
                    (
                        f'Package order {package_order.order_number} was placed successfully. '
                        'Payment submitted successfully. Please wait for verification.'
                    ),
                )
                return redirect(f"{reverse('order_tracking')}?type=package&id={package_order.id}")

    package_order_label = f'{selected_package.name} package booking'
    context = {
        'package': selected_package,
        'draft': draft,
        'payment_plan_labels': PAYMENT_PLAN_LABELS,
        'defaults': defaults,
        'form_values': form_values,
        'package_order_window': package_order_window,
        'package_base_total': package_base_total,
        'inclusions_total': inclusions_total,
        'addons_total': addons_total,
        'subtotal': subtotal,
        'custom_total': custom_total,
        'grand_total': grand_total,
        'deposit_amount': deposit_amount,
        'balance_due': balance_due,
        'gcash_account': get_gcash_profile(),
        'gcash_preview': _build_checkout_gcash_preview(
            request,
            deposit_amount,
            package_order_label,
        ),
        'checkout_order_number': package_checkout_meta['order_number'],
        'payment_qr_preview_url': reverse('payment_qr_preview'),
    }
    return render(request, 'hanilies/package_payment.html', context)


# ============================================
# ADMIN HELPER FUNCTIONS
# ============================================

def get_admin_menu(request):
    """Generate grouped admin sidebar sections filtered by the current user's role."""
    grouped_items = {}
    for item in ADMIN_MENU_ITEMS:
        if not _user_has_any_role(request.user, item['roles']):
            continue
        section = item.get('section', 'General')
        grouped_items.setdefault(section, []).append({
            'name': item['name'],
            'url': item['url'],
            'icon': item['icon'],
        })

    return [
        {
            'title': section,
            'items': items,
        }
        for section, items in grouped_items.items()
    ]


def is_admin_user(user):
    """Check if user has admin access"""
    return _user_has_any_role(user, STAFF_ROLE_VALUES)


# ============================================
# ADMIN DASHBOARD
# ============================================

def _mark_contact_inquiry_as_read(inquiry):
    if inquiry.is_read:
        return False

    inquiry.is_read = True
    inquiry.read_at = timezone.now()
    inquiry.save(update_fields=['is_read', 'read_at', 'updated_at'])
    return True


def _build_admin_contact_inquiry_reply_redirect(inquiry, return_url, anchor='reply-panel'):
    detail_url = reverse('admin_contact_inquiry_view', args=[inquiry.id])
    if return_url:
        detail_url = f"{detail_url}?{urlencode({'next': return_url})}"
    return f'{detail_url}#{anchor}'


def _render_admin_contact_inquiry_detail(request, inquiry, reply_form=None, status_code=200):
    return_url = _get_safe_admin_return_url(request, 'admin_contact_inquiries')
    active_reply_form = reply_form or AdminContactInquiryReplyForm()
    reply_delivery_text = (
        f'This reply will be emailed to {inquiry.reply_email}.'
        if inquiry.has_email_contact
        else 'This inquiry does not include a valid email address, so the reply will be saved here for manual follow-up.'
    )

    return render(request, 'admin/contact_inquiries/detail.html', {
        'inquiry': inquiry,
        'reply_form': active_reply_form,
        'reply_send_label': 'Send Reply' if inquiry.has_email_contact else 'Save Reply Note',
        'reply_delivery_text': reply_delivery_text,
        'return_url': return_url,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    }, status=status_code)


@login_required
def admin_contact_inquiries(request):
    """Review public customer contact inquiries."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    inquiries = ContactInquiry.objects.filter(
        is_archived=is_archived_view,
    ).order_by('is_read', '-created_at')
    inquiries_page, inquiries_pagination = _paginate_admin_queryset(
        request, inquiries, 'page'
    )

    return render(request, 'admin/contact_inquiries/list.html', {
        'inquiries_page': inquiries_page,
        'inquiries_pagination': inquiries_pagination,
        'is_archived_view': is_archived_view,
        'unread_inquiry_count': ContactInquiry.objects.filter(is_archived=False, is_read=False).count(),
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_contact_inquiry_view(request, inquiry_id):
    """View a single public customer inquiry."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    inquiry = get_object_or_404(ContactInquiry, id=inquiry_id)
    _mark_contact_inquiry_as_read(inquiry)

    return _render_admin_contact_inquiry_detail(request, inquiry)


@login_required
@require_POST
def admin_contact_inquiry_reply(request, inquiry_id):
    """Send or save an admin reply for a public customer inquiry."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    inquiry = get_object_or_404(ContactInquiry, id=inquiry_id)
    return_url = _get_safe_admin_return_url(request, 'admin_contact_inquiries')
    reply_form = AdminContactInquiryReplyForm(request.POST)

    if not reply_form.is_valid():
        _mark_contact_inquiry_as_read(inquiry)
        return _render_admin_contact_inquiry_detail(request, inquiry, reply_form=reply_form)

    reply_message = reply_form.cleaned_data['reply_message']
    if inquiry.has_email_contact:
        send_mail(
            'Reply from Hanilies Cakeshoppe',
            (
                f'Hello {inquiry.name},\n\n'
                f'{reply_message}\n\n'
                'If you need more help, please contact Hanilies Cakeshoppe again through the website.'
            ),
            settings.DEFAULT_FROM_EMAIL,
            [inquiry.reply_email],
            fail_silently=False,
        )

    _mark_contact_inquiry_as_read(inquiry)
    inquiry.admin_reply = reply_message
    inquiry.replied_at = timezone.now()
    inquiry.replied_by = request.user
    inquiry.save(update_fields=['admin_reply', 'replied_at', 'replied_by', 'updated_at'])
    _log_staff_activity(
        request.user,
        'contact_inquiry_replied',
        f'Replied to inquiry #{inquiry.id}.',
        'contact_inquiry',
        inquiry.id,
    )

    if inquiry.has_email_contact:
        messages.success(request, f'Reply sent to {inquiry.reply_email} for inquiry #{inquiry.id}.')
    else:
        messages.success(request, f'Reply saved on inquiry #{inquiry.id} for manual follow-up.')

    return redirect(_build_admin_contact_inquiry_reply_redirect(inquiry, return_url))


@login_required
@require_POST
def admin_contact_inquiry_update(request, inquiry_id):
    """Update inquiry read or archive state."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    inquiry = get_object_or_404(ContactInquiry, id=inquiry_id)
    action = (request.POST.get('action') or '').strip().lower()
    return_url = _get_safe_admin_return_url(request, 'admin_contact_inquiries')

    if action == 'mark_read':
        if inquiry.is_read:
            messages.info(request, f'Inquiry #{inquiry.id} is already marked as read.')
            return redirect(return_url)
        inquiry.is_read = True
        inquiry.read_at = timezone.now()
        inquiry.save(update_fields=['is_read', 'read_at', 'updated_at'])
        _log_staff_activity(
            request.user,
            'contact_inquiry_read',
            f'Marked inquiry #{inquiry.id} as read.',
            'contact_inquiry',
            inquiry.id,
        )
        messages.success(request, f'Inquiry #{inquiry.id} marked as read.')
        return redirect(return_url)

    if action == 'mark_unread':
        if inquiry.admin_reply and inquiry.replied_at:
            messages.info(request, f'Inquiry #{inquiry.id} already has a saved reply status.')
            return redirect(return_url)
        if not inquiry.is_read:
            messages.info(request, f'Inquiry #{inquiry.id} is already marked as new.')
            return redirect(return_url)
        inquiry.is_read = False
        inquiry.read_at = None
        inquiry.save(update_fields=['is_read', 'read_at', 'updated_at'])
        _log_staff_activity(
            request.user,
            'contact_inquiry_unread',
            f'Marked inquiry #{inquiry.id} as new.',
            'contact_inquiry',
            inquiry.id,
        )
        messages.success(request, f'Inquiry #{inquiry.id} marked as new.')
        return redirect(return_url)

    if action == 'archive':
        if inquiry.is_archived:
            messages.info(request, f'Inquiry #{inquiry.id} is already archived.')
            return redirect(return_url)
        _archive_model_instance(inquiry)
        _log_staff_activity(
            request.user,
            'contact_inquiry_archived',
            f'Archived inquiry #{inquiry.id}.',
            'contact_inquiry',
            inquiry.id,
        )
        messages.success(request, f'Inquiry #{inquiry.id} archived successfully!')
        return redirect(return_url)

    if action == 'restore':
        if not inquiry.is_archived:
            messages.info(request, f'Inquiry #{inquiry.id} is already active.')
            return redirect(return_url)
        _restore_model_instance(inquiry)
        _log_staff_activity(
            request.user,
            'contact_inquiry_restored',
            f'Restored inquiry #{inquiry.id}.',
            'contact_inquiry',
            inquiry.id,
        )
        messages.success(request, f'Inquiry #{inquiry.id} restored successfully!')
        return redirect(return_url)

    messages.error(request, 'Unknown inquiry action.')
    return redirect(return_url)


@login_required
@require_POST
def admin_contact_inquiry_delete(request, inquiry_id):
    """Permanently delete a public customer inquiry."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    inquiry = get_object_or_404(ContactInquiry, id=inquiry_id)
    inquiry_id_value = inquiry.id
    inquiry_name = inquiry.name
    inquiry.delete()
    _log_staff_activity(
        request.user,
        'contact_inquiry_deleted',
        f'Deleted inquiry #{inquiry_id_value} from {inquiry_name}.',
        'contact_inquiry',
        inquiry_id_value,
    )
    messages.success(request, f'Inquiry #{inquiry_id_value} deleted successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_contact_inquiries'))


@login_required
def admin_about_images(request):
    """List and manage About page images."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    _ensure_about_page_image_records()
    images_by_slot = {item.slot: item for item in AboutPageImage.objects.all()}
    about_images = []
    for slot_detail in ABOUT_PAGE_IMAGE_SLOT_DETAILS:
        image_record = images_by_slot.get(slot_detail['slot'])
        default_payload = ABOUT_PAGE_IMAGE_DEFAULTS[slot_detail['slot']]
        about_images.append({
            'record': image_record,
            'slot': slot_detail['slot'],
            'title': slot_detail['title'],
            'usage': slot_detail['usage'],
            'preview_url': image_record.image.url if image_record and image_record.image else default_payload['image_url'],
            'uses_default_image': not bool(image_record and image_record.image),
        })

    return render(request, 'admin/about_images/list.html', {
        'about_images': about_images,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_about_image_edit(request, image_id):
    """Edit an About page image slot."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    about_image = get_object_or_404(AboutPageImage, id=image_id)
    slot_title = dict(AboutPageImage.SLOT_CHOICES).get(about_image.slot, 'About Image')

    if request.method == 'POST':
        if 'image' in request.FILES:
            if about_image.image:
                about_image.image.delete(save=False)
            about_image.image = request.FILES['image']
            about_image.save(update_fields=['image', 'updated_at'])
            _log_staff_activity(
                request.user,
                'about_image_updated',
                f'Updated About page image slot "{slot_title}".',
                'about_page_image',
                about_image.id,
            )
            messages.success(request, f'About page image "{slot_title}" updated successfully!')
            return redirect('admin_about_images')

        messages.error(request, 'Please upload an image to replace the current About page photo.')

    default_payload = ABOUT_PAGE_IMAGE_DEFAULTS.get(about_image.slot, {})
    preview_url = about_image.image.url if about_image.image else default_payload.get('image_url', '')
    return render(request, 'admin/about_images/edit.html', {
        'about_image': about_image,
        'slot_title': slot_title,
        'preview_url': preview_url,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


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
    start_of_week = today - timedelta(days=6)
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
    pending_cake_approvals = CakeOrder.objects.filter(
        order_status__in=['pending', 'payment_retry'],
        is_archived=False,
    ).count()
    pending_package_approvals = PackageOrder.objects.filter(
        order_status__in=['pending', 'payment_retry'],
        is_archived=False,
    ).count()
    pending_payments = Payment.objects.filter(
        payment_status__in=['pending', 'verifying'],
    ).count()
    pending_refunds = RefundRequest.objects.filter(status='requested').count()
    pending_testimonials = Testimonial.objects.filter(
        status=Testimonial.STATUS_PENDING,
        is_archived=False,
    ).count()
    total_cakes = _get_public_cake_queryset().count()
    total_cake_orders = CakeOrder.objects.count()
    total_packages = _get_public_package_queryset().count()
    total_package_orders = PackageOrder.objects.count()
    total_users = User.objects.filter(is_active=True).count()

    role_value = role.role if role else 'admin'

    def user_allowed(allowed_roles):
        return request.user.is_superuser or role_value in allowed_roles

    can_view_audit_trail = user_allowed(AUDIT_TRAIL_ROLE_VALUES)
    can_manage_users = user_allowed(USER_MANAGEMENT_ROLE_VALUES)
    can_review_testimonials = user_allowed(FULL_ACCESS_ROLE_VALUES)
    can_view_payments = user_allowed(PAYMENT_REVIEW_ROLE_VALUES)
    can_view_cakes = user_allowed(CAKE_PRODUCT_ROLE_VALUES)
    can_view_packages = user_allowed(PACKAGE_PRODUCT_ROLE_VALUES)
    can_view_cake_orders = user_allowed(CAKE_ORDER_ROLE_VALUES)
    can_view_package_orders = user_allowed(PACKAGE_ORDER_ROLE_VALUES)
    can_view_refunds = user_allowed(PAYMENT_REVIEW_ROLE_VALUES)
    can_view_sales_reports = user_allowed(SALES_REPORT_ROLE_VALUES)
    can_view_stock_reports = user_allowed(STOCK_REPORT_ROLE_VALUES)

    order_sales_cards = []
    order_sales_report_rows = []
    if can_view_sales_reports:
        cake_order_sales_today = CakeOrder.objects.filter(
            is_archived=False,
            created_at__date=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        package_order_sales_today = PackageOrder.objects.filter(
            is_archived=False,
            created_at__date=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        order_sales_week = CakeOrder.objects.filter(
            is_archived=False,
            created_at__date__gte=start_of_week,
            created_at__date__lte=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        order_sales_week += PackageOrder.objects.filter(
            is_archived=False,
            created_at__date__gte=start_of_week,
            created_at__date__lte=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        order_sales_month = CakeOrder.objects.filter(
            is_archived=False,
            created_at__date__gte=start_of_month,
            created_at__date__lte=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        order_sales_month += PackageOrder.objects.filter(
            is_archived=False,
            created_at__date__gte=start_of_month,
            created_at__date__lte=today,
        ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
        order_sales_cards = [
            {
                'title': 'Cake Order Sales Today',
                'value': f'P{cake_order_sales_today:.2f}',
                'copy': 'Booked cake order sales created today.',
                'chip': 'Cake orders',
                'icon': 'birthday-cake',
                'url': reverse('admin_order_sales_report'),
            },
            {
                'title': 'Package Order Sales Today',
                'value': f'P{package_order_sales_today:.2f}',
                'copy': 'Booked package order sales created today.',
                'chip': 'Package orders',
                'icon': 'gift',
                'url': reverse('admin_order_sales_report'),
            },
            {
                'title': 'This Week Order Sales',
                'value': f'P{order_sales_week:.2f}',
                'copy': 'Combined cake and package order totals this week.',
                'chip': 'Weekly activity',
                'icon': 'chart-line',
                'url': reverse('admin_order_sales_report'),
            },
            {
                'title': 'This Month Order Sales',
                'value': f'P{order_sales_month:.2f}',
                'copy': 'Combined cake and package order totals this month.',
                'chip': 'Monthly activity',
                'icon': 'calendar-alt',
                'url': reverse('admin_order_sales_report'),
            },
        ]
        order_sales_report_rows = _build_order_sales_report_rows(limit=8)

    stock_report_cards = []
    stock_report_rows = []
    if can_view_stock_reports:
        all_stock_rows = _build_stock_report_rows(limit=None)
        stock_report_rows = all_stock_rows[:6]
        available_stock_count = sum(1 for row in all_stock_rows if row['health_key'] == 'available')
        low_stock_count = sum(1 for row in all_stock_rows if row['health_key'] == 'low')
        out_of_stock_count = sum(1 for row in all_stock_rows if row['health_key'] == 'out')
        stock_units_on_hand = sum(row['stock_value'] for row in all_stock_rows)
        stock_report_cards = [
            {
                'title': 'Available Products',
                'value': available_stock_count,
                'copy': 'Products with healthy stock on hand.',
                'chip': 'Available',
                'icon': 'boxes-stacked',
                'url': reverse('admin_stock_report'),
            },
            {
                'title': 'Needs Replenishment',
                'value': low_stock_count,
                'copy': f'Products at or below {LOW_STOCK_THRESHOLD} stock.',
                'chip': 'Replenish soon',
                'icon': 'triangle-exclamation',
                'url': reverse('admin_stock_report'),
            },
            {
                'title': 'Out of Stock',
                'value': out_of_stock_count,
                'copy': 'Products that can no longer cover new sold units.',
                'chip': 'Critical',
                'icon': 'circle-xmark',
                'url': reverse('admin_stock_report'),
            },
            {
                'title': 'Units on Hand',
                'value': stock_units_on_hand,
                'copy': 'Total tracked stock across cake and package products.',
                'chip': 'Inventory total',
                'icon': 'warehouse',
                'url': reverse('admin_stock_report'),
            },
        ]

    priority_cards = []
    if can_view_payments:
        priority_cards.append({
            'title': 'Pending Payments',
            'value': pending_payments,
            'copy': 'Payments still waiting for admin or cashier verification.',
            'chip': 'Needs review',
            'chip_negative': True,
            'icon': 'clock',
            'url': reverse('admin_payments'),
            'tone': 'urgent',
        })
    if can_view_cake_orders:
        priority_cards.append({
            'title': 'Cake Orders',
            'value': CakeOrder.objects.count(),
            'copy': f'{pending_cake_approvals} cake orders currently need approval or payment follow-up.',
            'chip': 'Order queue',
            'icon': 'shopping-cart',
            'url': reverse('admin_cake_orders'),
            'tone': '',
        })
    if can_view_package_orders:
        priority_cards.append({
            'title': 'Package Orders',
            'value': PackageOrder.objects.count(),
            'copy': f'{pending_package_approvals} package orders currently need approval or payment follow-up.',
            'chip': 'Event pipeline',
            'icon': 'calendar-check',
            'url': reverse('admin_package_orders'),
            'tone': '',
        })
    if can_view_payments:
        priority_cards.append({
            'title': "Today's Sales",
            'value': f'P{total_sales_today:.2f}',
            'copy': f'Paid transactions recorded for {today.strftime("%B %d, %Y")}.',
            'chip': 'Paid today',
            'icon': 'peso-sign',
            'url': reverse('admin_payments'),
            'tone': 'sales',
        })

    secondary_cards = []
    if can_view_cakes:
        secondary_cards.append({
            'title': 'Total Cakes',
            'value': total_cakes,
            'chip': 'Active products',
            'icon': 'birthday-cake',
            'url': reverse('admin_cakes'),
            'tone': 'neutral',
        })
    if can_view_packages:
        secondary_cards.append({
            'title': 'Total Packages',
            'value': total_packages,
            'chip': 'Active packages',
            'icon': 'gift',
            'url': reverse('admin_packages'),
            'tone': 'neutral',
        })
    if can_view_payments:
        secondary_cards.extend([
            {
                'title': "This Week's Sales",
                'value': f'P{total_sales_week:.2f}',
                'chip': 'Paid this week',
                'icon': 'chart-line',
                'url': reverse('admin_payments'),
                'tone': 'sales',
            },
            {
                'title': "This Month's Sales",
                'value': f'P{total_sales_month:.2f}',
                'chip': 'Paid this month',
                'icon': 'calendar-alt',
                'url': reverse('admin_payments'),
                'tone': 'sales',
            },
        ])
    if can_manage_users:
        secondary_cards.append({
            'title': 'Total Users',
            'value': total_users,
            'chip': 'Registered users',
            'icon': 'users',
            'url': reverse('admin_users'),
            'tone': '',
        })

    quick_actions = []
    if can_view_payments:
        quick_actions.append({
            'title': 'Verify Payments',
            'copy': 'Review GCash submissions and collect balances.',
            'icon': 'credit-card',
            'url': reverse('admin_payments'),
            'priority': True,
        })
    if can_view_cake_orders:
        quick_actions.append({
            'title': 'View Cake Orders',
            'copy': 'Open the current cake order queue immediately.',
            'icon': 'list-check',
            'url': reverse('admin_cake_orders'),
            'priority': False,
        })
    if can_view_package_orders:
        quick_actions.append({
            'title': 'View Package Orders',
            'copy': 'Check the live package and event booking queue.',
            'icon': 'calendar-week',
            'url': reverse('admin_package_orders'),
            'priority': False,
        })
    if can_view_cakes:
        quick_actions.append({
            'title': 'Add New Cake',
            'copy': 'Create a new cake listing for the storefront.',
            'icon': 'plus',
            'url': reverse('admin_cake_add'),
            'priority': False,
        })
    if can_view_packages:
        quick_actions.append({
            'title': 'Add New Package',
            'copy': 'Publish another event package offering.',
            'icon': 'gift',
            'url': reverse('admin_package_add'),
            'priority': False,
        })
    if can_manage_users:
        quick_actions.append({
            'title': 'Manage Users',
            'copy': 'Review accounts, roles, and staff access.',
            'icon': 'users-cog',
            'url': reverse('admin_users'),
            'priority': False,
        })
    if can_review_testimonials:
        quick_actions.append({
            'title': 'Review Testimonials',
            'copy': 'Approve or hide recent customer feedback.',
            'icon': 'comments',
            'url': reverse('admin_testimonials'),
            'priority': False,
        })

    attention_items = []
    if can_view_payments:
        attention_items.append({
            'title': 'Payments Waiting for Verification',
            'copy': 'Pending and verifying payment submissions.',
            'value': pending_payments,
            'url': reverse('admin_payments'),
            'urgent': True,
        })
    if can_view_refunds:
        attention_items.append({
            'title': 'Refund Requests',
            'copy': 'Customer cancellation or refund requests awaiting review.',
            'value': pending_refunds,
            'url': reverse('admin_refunds'),
            'urgent': False,
        })
    if can_view_cake_orders:
        attention_items.append({
            'title': 'Cake Orders Requiring Action',
            'copy': 'Pending approval or payment resubmission follow-up.',
            'value': pending_cake_approvals,
            'url': reverse('admin_cake_orders'),
            'urgent': False,
        })
    if can_view_package_orders:
        attention_items.append({
            'title': 'Package Orders Requiring Action',
            'copy': 'Pending approval or payment resubmission follow-up.',
            'value': pending_package_approvals,
            'url': reverse('admin_package_orders'),
            'urgent': False,
        })
    if can_review_testimonials:
        attention_items.append({
            'title': 'Testimonials Pending Review',
            'copy': 'Customer feedback waiting for moderation.',
            'value': pending_testimonials,
            'url': reverse('admin_testimonials'),
            'urgent': False,
        })

    hero_summary_items = []
    if can_view_payments:
        hero_summary_items.append({
            'label': 'Needs Attention',
            'value': pending_payments + pending_refunds + (pending_testimonials if can_review_testimonials else 0),
        })
        hero_summary_items.append({
            'label': 'Today Sales',
            'value': f'P{total_sales_today:.2f}',
        })
    if can_view_cake_orders or can_view_package_orders:
        hero_summary_items.append({
            'label': 'Visible Orders',
            'value': (
                (total_cake_orders if can_view_cake_orders else 0)
                + (total_package_orders if can_view_package_orders else 0)
            ),
        })
    if can_view_cakes or can_view_packages:
        hero_summary_items.append({
            'label': 'Active Catalog',
            'value': (
                (total_cakes if can_view_cakes else 0)
                + (total_packages if can_view_packages else 0)
            ),
        })
    if can_manage_users and len(hero_summary_items) < 4:
        hero_summary_items.append({
            'label': 'Active Users',
            'value': total_users,
        })
    hero_summary_items = hero_summary_items[:4]

    context = {
        'admin_menu': admin_menu,
        'role': role_value,
        'role_display': role.get_role_display() if role else 'Administrator',
        'total_cakes': total_cakes,
        'total_cake_orders': total_cake_orders,
        'total_packages': total_packages,
        'total_package_orders': total_package_orders,
        'total_users': total_users,
        'pending_payments': pending_payments,
        'pending_refunds': pending_refunds,
        'pending_cake_approvals': pending_cake_approvals,
        'pending_package_approvals': pending_package_approvals,
        'pending_testimonials': pending_testimonials,
        'total_sales_today': total_sales_today,
        'total_sales_week': total_sales_week,
        'total_sales_month': total_sales_month,
        'recent_activity_logs': ActivityLog.objects.select_related('actor').filter(is_archived=False)[:5],
        'recent_cake_orders': CakeOrder.objects.filter(is_archived=False).order_by('-created_at')[:5] if can_view_cake_orders else [],
        'recent_package_orders': PackageOrder.objects.filter(is_archived=False).order_by('-created_at')[:5] if can_view_package_orders else [],
        'now': timezone.now(),
        'can_view_audit_trail': can_view_audit_trail,
        'can_view_cake_orders': can_view_cake_orders,
        'can_view_package_orders': can_view_package_orders,
        'can_view_payments': can_view_payments,
        'can_view_stock_reports': can_view_stock_reports,
        'priority_cards': priority_cards[:4],
        'secondary_cards': secondary_cards[:5],
        'quick_actions': quick_actions[:6],
        'attention_items': attention_items[:5],
        'hero_summary_items': hero_summary_items,
        'order_sales_cards': order_sales_cards,
        'order_sales_report_rows': order_sales_report_rows,
        'stock_report_cards': stock_report_cards,
        'stock_report_rows': stock_report_rows,
    }

    return render(request, 'admin/dashboard.html', context)


@login_required
def admin_order_sales_report(request):
    access_denied = _require_admin_roles(request, SALES_REPORT_ROLE_VALUES)
    if access_denied:
        return access_denied

    today = timezone.localdate()
    start_of_week = today - timedelta(days=6)
    start_of_month = today.replace(day=1)
    cake_order_sales_today = CakeOrder.objects.filter(
        is_archived=False,
        created_at__date=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
    package_order_sales_today = PackageOrder.objects.filter(
        is_archived=False,
        created_at__date=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
    order_sales_week = CakeOrder.objects.filter(
        is_archived=False,
        created_at__date__gte=start_of_week,
        created_at__date__lte=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
    order_sales_week += PackageOrder.objects.filter(
        is_archived=False,
        created_at__date__gte=start_of_week,
        created_at__date__lte=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
    order_sales_month = CakeOrder.objects.filter(
        is_archived=False,
        created_at__date__gte=start_of_month,
        created_at__date__lte=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')
    order_sales_month += PackageOrder.objects.filter(
        is_archived=False,
        created_at__date__gte=start_of_month,
        created_at__date__lte=today,
    ).exclude(order_status='cancelled').aggregate(total=Sum('total_price'))['total'] or Decimal('0.00')

    order_sales_cards = [
        {
            'title': 'Cake Order Sales Today',
            'value': f'P{cake_order_sales_today:.2f}',
            'copy': 'Booked cake order sales created today.',
            'chip': 'Cake orders',
            'icon': 'birthday-cake',
        },
        {
            'title': 'Package Order Sales Today',
            'value': f'P{package_order_sales_today:.2f}',
            'copy': 'Booked package order sales created today.',
            'chip': 'Package orders',
            'icon': 'gift',
        },
        {
            'title': 'This Week Order Sales',
            'value': f'P{order_sales_week:.2f}',
            'copy': 'Combined cake and package order totals this week.',
            'chip': 'Weekly activity',
            'icon': 'chart-line',
        },
        {
            'title': 'This Month Order Sales',
            'value': f'P{order_sales_month:.2f}',
            'copy': 'Combined cake and package order totals this month.',
            'chip': 'Monthly activity',
            'icon': 'calendar-alt',
        },
    ]

    return render(request, 'admin/reports/order_sales.html', {
        'admin_menu': get_admin_menu(request),
        'order_sales_cards': order_sales_cards,
        'order_sales_report_rows': _build_order_sales_report_rows(limit=None),
        'can_view_payments': _user_has_any_role(request.user, PAYMENT_REVIEW_ROLE_VALUES),
        'today': today,
    })


@login_required
def admin_stock_report(request):
    access_denied = _require_admin_roles(request, STOCK_REPORT_ROLE_VALUES)
    if access_denied:
        return access_denied

    stock_rows = _build_stock_report_rows(limit=None)
    stock_report_cards = [
        {
            'title': 'Available Products',
            'value': sum(1 for row in stock_rows if row['health_key'] == 'available'),
            'copy': 'Products with healthy stock on hand.',
            'chip': 'Available',
            'icon': 'boxes-stacked',
        },
        {
            'title': 'Needs Replenishment',
            'value': sum(1 for row in stock_rows if row['health_key'] == 'low'),
            'copy': f'Products at or below {LOW_STOCK_THRESHOLD} stock.',
            'chip': 'Replenish soon',
            'icon': 'triangle-exclamation',
        },
        {
            'title': 'Out of Stock',
            'value': sum(1 for row in stock_rows if row['health_key'] == 'out'),
            'copy': 'Products that need immediate restocking.',
            'chip': 'Critical',
            'icon': 'circle-xmark',
        },
        {
            'title': 'Units on Hand',
            'value': sum(row['stock_value'] for row in stock_rows),
            'copy': 'Total tracked stock across cake and package products.',
            'chip': 'Inventory total',
            'icon': 'warehouse',
        },
    ]

    return render(request, 'admin/reports/stock_report.html', {
        'admin_menu': get_admin_menu(request),
        'stock_report_cards': stock_report_cards,
        'stock_report_rows': stock_rows,
    })


# ============================================
# ADMIN HOMEPAGE HERO
# ============================================

@login_required
def admin_home_hero_images(request):
    """List homepage hero collage images."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    hero_images = HomeHeroImage.objects.order_by('display_order', 'id')
    return render(request, 'admin/hero_images/list.html', {
        'hero_images': hero_images,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_home_hero_add(request):
    """Add a homepage hero collage image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/hero_images/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        if 'image' not in request.FILES:
            messages.error(request, 'Please upload a celebration image.')
            return render(request, 'admin/hero_images/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        try:
            hero_image = HomeHeroImage.objects.create(
                title=title,
                image=request.FILES['image'],
                display_order=int(request.POST.get('display_order') or 0),
                is_active=request.POST.get('is_active') == 'on',
            )
        except ValueError:
            messages.error(request, 'Display order must be a whole number.')
            return render(request, 'admin/hero_images/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        _log_staff_activity(
            request.user,
            'home_hero_created',
            f'Added homepage hero image "{hero_image.title}".',
            'home_hero_image',
            hero_image.id,
        )
        messages.success(
            request, f'Homepage hero image "{hero_image.title}" added successfully!')
        return redirect('admin_home_hero_images')

    return render(request, 'admin/hero_images/add.html', {
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_home_hero_edit(request, hero_image_id):
    """Edit a homepage hero collage image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    hero_image = get_object_or_404(HomeHeroImage, id=hero_image_id)

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/hero_images/edit.html', {
                'hero_image': hero_image,
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        try:
            hero_image.title = title
            hero_image.display_order = int(
                request.POST.get('display_order') or 0)
            hero_image.is_active = request.POST.get('is_active') == 'on'

            if 'image' in request.FILES:
                if hero_image.image:
                    hero_image.image.delete(save=False)
                hero_image.image = request.FILES['image']

            hero_image.save()
        except ValueError:
            messages.error(request, 'Display order must be a whole number.')
            return render(request, 'admin/hero_images/edit.html', {
                'hero_image': hero_image,
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        _log_staff_activity(
            request.user,
            'home_hero_updated',
            f'Updated homepage hero image "{hero_image.title}".',
            'home_hero_image',
            hero_image.id,
        )
        messages.success(
            request, f'Homepage hero image "{hero_image.title}" updated successfully!')
        return redirect('admin_home_hero_images')

    return render(request, 'admin/hero_images/edit.html', {
        'hero_image': hero_image,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
@require_POST
def admin_home_hero_delete(request, hero_image_id):
    """Delete a homepage hero collage image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    hero_image = get_object_or_404(HomeHeroImage, id=hero_image_id)
    hero_title = hero_image.title
    if hero_image.image:
        hero_image.image.delete(save=False)
    hero_image.delete()
    _log_staff_activity(
        request.user,
        'home_hero_deleted',
        f'Deleted homepage hero image "{hero_title}".',
        'home_hero_image',
        hero_image_id,
    )
    messages.success(
        request, f'Homepage hero image "{hero_title}" deleted successfully!')
    return redirect('admin_home_hero_images')


@login_required
def admin_home_strip_images(request):
    """List homepage strip images."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    strip_images = HomeStripImage.objects.order_by('display_order', 'id')
    return render(request, 'admin/home_strip/list.html', {
        'strip_images': strip_images,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_home_strip_add(request):
    """Add a homepage strip image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/home_strip/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        if 'image' not in request.FILES:
            messages.error(request, 'Please upload a strip image.')
            return render(request, 'admin/home_strip/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        try:
            strip_image = HomeStripImage.objects.create(
                title=title,
                image=request.FILES['image'],
                display_order=int(request.POST.get('display_order') or 0),
                is_active=request.POST.get('is_active') == 'on',
            )
        except ValueError:
            messages.error(request, 'Display order must be a whole number.')
            return render(request, 'admin/home_strip/add.html', {
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        _log_staff_activity(
            request.user,
            'home_strip_created',
            f'Added homepage strip image "{strip_image.title}".',
            'home_strip_image',
            strip_image.id,
        )
        messages.success(
            request, f'Homepage strip image "{strip_image.title}" added successfully!')
        return redirect('admin_home_strip_images')

    return render(request, 'admin/home_strip/add.html', {
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_home_strip_edit(request, strip_image_id):
    """Edit a homepage strip image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    strip_image = get_object_or_404(HomeStripImage, id=strip_image_id)

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/home_strip/edit.html', {
                'strip_image': strip_image,
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        try:
            strip_image.title = title
            strip_image.display_order = int(
                request.POST.get('display_order') or 0)
            strip_image.is_active = request.POST.get('is_active') == 'on'

            if 'image' in request.FILES:
                if strip_image.image:
                    strip_image.image.delete(save=False)
                strip_image.image = request.FILES['image']

            strip_image.save()
        except ValueError:
            messages.error(request, 'Display order must be a whole number.')
            return render(request, 'admin/home_strip/edit.html', {
                'strip_image': strip_image,
                'admin_menu': get_admin_menu(request),
                    'hide_demo_panel': True,
    })

        _log_staff_activity(
            request.user,
            'home_strip_updated',
            f'Updated homepage strip image "{strip_image.title}".',
            'home_strip_image',
            strip_image.id,
        )
        messages.success(
            request, f'Homepage strip image "{strip_image.title}" updated successfully!')
        return redirect('admin_home_strip_images')

    return render(request, 'admin/home_strip/edit.html', {
        'strip_image': strip_image,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
@require_POST
def admin_home_strip_delete(request, strip_image_id):
    """Delete a homepage strip image."""
    access_denied = _require_admin_roles(request, HOME_HERO_ROLE_VALUES)
    if access_denied:
        return access_denied

    strip_image = get_object_or_404(HomeStripImage, id=strip_image_id)
    strip_title = strip_image.title
    if strip_image.image:
        strip_image.image.delete(save=False)
    strip_image.delete()
    _log_staff_activity(
        request.user,
        'home_strip_deleted',
        f'Deleted homepage strip image "{strip_title}".',
        'home_strip_image',
        strip_image_id,
    )
    messages.success(
        request, f'Homepage strip image "{strip_title}" deleted successfully!')
    return redirect('admin_home_strip_images')

# ============================================
# ADMIN CAKES
# ============================================


@login_required
def admin_cakes(request):
    """List all cakes"""
    access_denied = _require_admin_roles(
        request, CAKE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    cakes = list(Cake.objects.filter(
        is_archived=is_archived_view).order_by('-created_at'))
    _decorate_products_with_stock_health(cakes)
    return render(request, 'admin/cakes/list.html', {
        'cakes': cakes,
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_add(request):
    """Add a new cake with image upload"""
    access_denied = _require_admin_roles(
        request, CAKE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        try:
            customization_options = _synchronize_cake_size_option_groups(
                _parse_customization_options_payload(
                    request.POST.get('customization_options_payload'),
                    CAKE_CUSTOMIZATION_GROUP_SPECS,
                )
            )
            name = request.POST.get('name')
            category = request.POST.get('category')
            if category not in CAKE_CATEGORY_VALUES:
                messages.error(
                    request, 'Selected cake category is not available.')
                return render(request, 'admin/cakes/add.html', {
                    'admin_menu': get_admin_menu(request),
                    'cake_categories': Cake.CAKE_CATEGORIES,
                    'option_editor_groups': _build_option_editor_groups(
                        _synchronize_cake_size_option_groups(
                            customization_options,
                        ),
                        CAKE_CUSTOMIZATION_GROUP_SPECS,
                        DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
                    ),
                })

            description = request.POST.get('description')
            price = request.POST.get('price')
            stock = _parse_stock_quantity(request.POST.get('stock', 0))
            is_active = request.POST.get('is_active') == 'on'

            cake = Cake(
                name=name,
                category=category,
                description=description,
                price=price,
                stock=stock,
                customization_options=customization_options,
                is_active=is_active,
            )

            if 'image' in request.FILES:
                cake.image = request.FILES['image']

            cake.save()
            customization_options = _apply_option_image_uploads(
                customization_options,
                CAKE_CUSTOMIZATION_GROUP_SPECS,
                request.FILES,
                product_prefix='cake-options',
                object_id=cake.id,
            )
            customization_options = _synchronize_cake_size_option_groups(
                customization_options,
            )
            if customization_options != cake.customization_options:
                cake.customization_options = customization_options
                cake.save(update_fields=['customization_options'])
            if cake.stock > 0:
                _log_staff_activity(
                    request.user,
                    'cake_stock_initialized',
                    f'Set stock for cake "{cake.name}" ({cake.product_code or "Not assigned"}) to {cake.stock}.',
                    'cake',
                    cake.id,
                )
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

        except ValueError as e:
            messages.error(request, str(e))
            return render(request, 'admin/cakes/add.html', {
                'admin_menu': get_admin_menu(request),
                'cake_categories': Cake.CAKE_CATEGORIES,
                'option_editor_groups': _build_option_editor_groups(
                    _synchronize_cake_size_option_groups({}),
                    CAKE_CUSTOMIZATION_GROUP_SPECS,
                    DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
                ),
            })
        except Exception as e:
            messages.error(request, f'Error adding cake: {str(e)}')
            return redirect('admin_cake_add')

    return render(request, 'admin/cakes/add.html', {
        'admin_menu': get_admin_menu(request),
        'cake_categories': Cake.CAKE_CATEGORIES,
        'option_editor_groups': _build_option_editor_groups(
            _synchronize_cake_size_option_groups({}),
            CAKE_CUSTOMIZATION_GROUP_SPECS,
            DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
        ),
    })


@login_required
def admin_cake_edit(request, cake_id):
    """Edit a cake with image upload"""
    access_denied = _require_admin_roles(
        request, CAKE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    cake = get_object_or_404(Cake, id=cake_id)

    if request.method == 'POST':
        try:
            previous_stock = int(cake.stock or 0)
            previous_option_images = _collect_option_image_paths(
                cake.customization_options,
                CAKE_CUSTOMIZATION_GROUP_SPECS,
            )
            customization_options = _synchronize_cake_size_option_groups(
                _parse_customization_options_payload(
                    request.POST.get('customization_options_payload'),
                    CAKE_CUSTOMIZATION_GROUP_SPECS,
                )
            )
            cake.name = request.POST.get('name')
            category = request.POST.get('category')
            if category not in CAKE_CATEGORY_VALUES:
                messages.error(
                    request, 'Selected cake category is not available.')
                return render(request, 'admin/cakes/edit.html', {
                    'cake': cake,
                    'admin_menu': get_admin_menu(request),
                    'cake_categories': Cake.CAKE_CATEGORIES,
                    'option_editor_groups': _build_option_editor_groups(
                        _synchronize_cake_size_option_groups(
                            customization_options,
                        ),
                        CAKE_CUSTOMIZATION_GROUP_SPECS,
                        DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
                    ),
                })

            cake.category = category
            cake.description = request.POST.get('description')
            cake.price = request.POST.get('price')
            cake.stock = _parse_stock_quantity(request.POST.get('stock'))
            cake.customization_options = customization_options
            cake.is_active = request.POST.get('is_active') == 'on'

            if 'image' in request.FILES:
                if cake.image:
                    cake.image.delete(save=False)
                cake.image = request.FILES['image']

            if request.POST.get('remove_image') == 'on' and cake.image:
                cake.image.delete(save=False)
                cake.image = None

            customization_options = _apply_option_image_uploads(
                customization_options,
                CAKE_CUSTOMIZATION_GROUP_SPECS,
                request.FILES,
                product_prefix='cake-options',
                object_id=cake.id,
            )
            customization_options = _synchronize_cake_size_option_groups(
                customization_options,
            )
            cake.customization_options = customization_options

            cake.save()
            updated_option_images = _collect_option_image_paths(
                customization_options,
                CAKE_CUSTOMIZATION_GROUP_SPECS,
            )
            _delete_option_images(
                previous_option_images - updated_option_images)
            if previous_stock != cake.stock:
                _log_staff_activity(
                    request.user,
                    'cake_stock_updated',
                    f'Updated stock for cake "{cake.name}" ({cake.product_code or "Not assigned"}) from {previous_stock} to {cake.stock}.',
                    'cake',
                    cake.id,
                )
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

        except ValueError as e:
            messages.error(request, str(e))
            return render(request, 'admin/cakes/edit.html', {
                'cake': cake,
                'admin_menu': get_admin_menu(request),
                'cake_categories': Cake.CAKE_CATEGORIES,
                'option_editor_groups': _build_option_editor_groups(
                    _synchronize_cake_size_option_groups(
                        cake.customization_options,
                    ),
                    CAKE_CUSTOMIZATION_GROUP_SPECS,
                    DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
                ),
            })
        except Exception as e:
            messages.error(request, f'Error updating cake: {str(e)}')
            return redirect('admin_cake_edit', cake_id=cake_id)

    return render(request, 'admin/cakes/edit.html', {
        'cake': cake,
        'admin_menu': get_admin_menu(request),
        'cake_categories': Cake.CAKE_CATEGORIES,
        'option_editor_groups': _build_option_editor_groups(
            _synchronize_cake_size_option_groups(
                cake.customization_options,
            ),
            CAKE_CUSTOMIZATION_GROUP_SPECS,
            DEFAULT_CAKE_CUSTOMIZATION_OPTIONS,
        ),
    })


@login_required
@require_POST
def admin_cake_delete(request, cake_id):
    """Archive or restore a cake"""
    access_denied = _require_admin_roles(request, CAKE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    cake = get_object_or_404(Cake, id=cake_id)
    cake_name = cake.name
    if cake.is_archived:
        _restore_model_instance(cake, is_active=True)
        _log_staff_activity(
            request.user,
            'cake_restored',
            f'Restored cake "{cake_name}".',
            'cake',
            cake_id,
        )
        messages.success(request, f'Cake "{cake_name}" restored successfully!')
    else:
        _archive_model_instance(cake, is_active=False)
        _log_staff_activity(
            request.user,
            'cake_archived',
            f'Archived cake "{cake_name}".',
            'cake',
            cake_id,
        )
        messages.success(request, f'Cake "{cake_name}" archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_cakes'))


# ============================================
# ADMIN CAKE ORDERS
# ============================================

@login_required
def admin_cake_orders(request):
    """List all cake orders"""
    access_denied = _require_admin_roles(
        request, CAKE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    orders_queryset = _annotate_admin_order_activity(
        CakeOrder.objects.select_related('user', 'cake').filter(
            is_archived=is_archived_view,
        ),
        'cake_order',
    ).order_by('-last_activity_at', '-created_at')
    if _get_user_role_value(request.user) == 'baker':
        orders_queryset = orders_queryset.filter(order_status__in=[
                                                 'confirmed', 'preparing', 'ready_for_pickup', 'out_for_delivery', 'completed'])
    orders, orders_pagination = _paginate_admin_queryset(
        request, orders_queryset, 'page')
    _decorate_admin_orders_with_actions(orders, request)
    return render(request, 'admin/orders/cake_orders.html', {
        'orders': orders,
        'orders_pagination': orders_pagination,
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_view(request, order_id):
    """View order details"""
    access_denied = _require_admin_roles(
        request, CAKE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    order = get_object_or_404(
        CakeOrder.objects.select_related(
            'user', 'cake', 'customization').prefetch_related(_build_admin_order_payment_prefetch()),
        id=order_id,
    )
    if not _can_view_order_for_role(request.user, order):
        messages.error(request, 'Permission denied')
        return redirect('admin_cake_orders')
    back_url = _get_safe_admin_return_url(request, 'admin_cake_orders')
    order_customization = getattr(order, 'customization', None)
    return render(request, 'admin/orders/cake_order_view.html', {
        'order': order,
        'order_customization': order_customization,
        'back_url': back_url,
        'back_label': 'Back to Payments' if back_url.startswith(reverse('admin_payments')) else 'Back to Cake Orders',
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_cake_order_update(request, order_id):
    """Update order status"""
    access_denied = _require_admin_roles(
        request, CAKE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        order = get_object_or_404(CakeOrder, id=order_id)
        if not _can_view_order_for_role(request.user, order):
            messages.error(request, 'Permission denied')
            return redirect(_get_safe_admin_return_url(request, 'admin_cake_orders'))
        previous_status = order.order_status
        new_status = request.POST.get('status')
        allowed_statuses = {value for value,
                            _ in _get_allowed_status_updates(request.user, order)}

        if new_status and new_status != previous_status:
            if new_status not in allowed_statuses:
                messages.error(
                    request, 'You are not allowed to apply that status change.')
                return redirect(_get_safe_admin_return_url(request, 'admin_cake_orders'))
            try:
                if new_status == 'completed':
                    _commit_order_stock(order, request.user)
                elif getattr(order, 'stock_deducted', False):
                    _restore_order_stock(order, request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(_get_safe_admin_return_url(request, 'admin_cake_orders'))
            order.order_status = new_status
            order.save(update_fields=['order_status', 'updated_at'])
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
    return redirect(_get_safe_admin_return_url(request, 'admin_cake_orders'))


@login_required
@require_POST
def admin_cake_order_delete(request, order_id):
    """Archive or restore a cake order"""
    access_denied = _require_admin_roles(
        request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    order = get_object_or_404(CakeOrder, id=order_id)
    order_id_value = order.id
    if order.is_archived:
        _restore_model_instance(order)
        _log_staff_activity(
            request.user,
            'cake_order_restored',
            f'Restored cake order #{order_id_value}.',
            'cake_order',
            order_id_value,
        )
        messages.success(
            request, f'Order #{order_id_value} restored successfully!')
    else:
        _archive_model_instance(order)
        _log_staff_activity(
            request.user,
            'cake_order_archived',
            f'Archived cake order #{order_id_value}.',
            'cake_order',
            order_id_value,
        )
        messages.success(
            request, f'Order #{order_id_value} archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_cake_orders'))


# ============================================
# ADMIN PACKAGES
# ============================================

@login_required
def admin_packages(request):
    """List all packages"""
    access_denied = _require_admin_roles(
        request, PACKAGE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    packages = list(Package.objects.filter(is_archived=is_archived_view).prefetch_related(
        'thumbnails').order_by('-created_at'))
    _decorate_products_with_stock_health(packages)
    return render(request, 'admin/packages/list.html', {
        'packages': packages,
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_add(request):
    """Add a new package"""
    access_denied = _require_admin_roles(
        request, PACKAGE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        try:
            package_type = request.POST.get('package_type')
            stock = _parse_stock_quantity(request.POST.get('stock', 0))
            customization_options = _filter_removed_package_cake_decorations(
                _parse_customization_options_payload(
                    request.POST.get('customization_options_payload'),
                    PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                )
            )
            package_inclusion_items = _resolve_package_inclusion_submission(
                request.POST,
            )
            if not package_inclusion_items:
                raise ValueError(
                    'Add at least one package feature or inclusion.')
            if package_type not in PUBLIC_PACKAGE_TYPE_VALUES:
                messages.error(
                    request, 'Selected package type is no longer available.')
                return render(request, 'admin/packages/add.html', {
                    'admin_menu': get_admin_menu(request),
                    'thumbnail_slots': _build_package_thumbnail_slots(),
                    'package_inclusion_editor_items': _build_package_inclusion_editor_items(
                        package_inclusion_items,
                    ),
                    'option_editor_groups': _build_option_editor_groups(
                        _filter_removed_package_cake_decorations(
                            customization_options,
                        ),
                        PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                    ),
                })

            inclusion_summary = '\n'.join(
                _format_package_inclusion_lines(package_inclusion_items)
            )
            customization_options = {
                **customization_options,
                'included_items': package_inclusion_items,
            }

            package = Package(
                name=request.POST.get('name'),
                package_type=package_type,
                description=request.POST.get('description'),
                base_price=request.POST.get('base_price'),
                stock=stock,
                status=request.POST.get('status', 'active'),
                features=inclusion_summary,
                included_items=inclusion_summary,
                customization_options=customization_options,
                image=request.FILES.get('image'),
            )
            package.save()
            package_inclusion_items = _apply_package_inclusion_image_uploads(
                package_inclusion_items,
                request.FILES,
                object_id=package.id,
            )
            customization_options = _apply_option_image_uploads(
                customization_options,
                PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                request.FILES,
                product_prefix='package-options',
                object_id=package.id,
            )
            customization_options['included_items'] = package_inclusion_items
            if customization_options != package.customization_options:
                package.customization_options = customization_options
                package.save(update_fields=['customization_options'])
            _sync_package_thumbnails(package, request.FILES)
            if package.stock > 0:
                _log_staff_activity(
                    request.user,
                    'package_stock_initialized',
                    f'Set stock for package "{package.name}" ({package.product_code or "Not assigned"}) to {package.stock}.',
                    'package',
                    package.id,
                )
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
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error adding package: {str(e)}')

    return render(request, 'admin/packages/add.html', {
        'admin_menu': get_admin_menu(request),
        'thumbnail_slots': _build_package_thumbnail_slots(),
        'package_inclusion_editor_items': _build_package_inclusion_editor_items(
            [],
        ),
        'option_editor_groups': _build_option_editor_groups(
            {},
            PACKAGE_CUSTOMIZATION_GROUP_SPECS,
        ),
    })


@login_required
def admin_package_edit(request, package_id):
    """Edit a package"""
    access_denied = _require_admin_roles(
        request, PACKAGE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    package = get_object_or_404(
        Package.objects.prefetch_related('thumbnails'), id=package_id)

    if request.method == 'POST':
        try:
            previous_stock = int(package.stock or 0)
            previous_option_images = _collect_option_image_paths(
                package.customization_options,
                PACKAGE_CUSTOMIZATION_GROUP_SPECS,
            )
            previous_inclusion_images = _collect_package_inclusion_image_paths(
                _get_package_inclusion_items(package, for_display=False),
            )
            package_type = request.POST.get('package_type')
            customization_options = _filter_removed_package_cake_decorations(
                _parse_customization_options_payload(
                    request.POST.get('customization_options_payload'),
                    PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                )
            )
            package_inclusion_items = _resolve_package_inclusion_submission(
                request.POST,
                fallback_text=package.features,
            )
            if not package_inclusion_items:
                raise ValueError(
                    'Add at least one package feature or inclusion.')
            if package_type not in PUBLIC_PACKAGE_TYPE_VALUES:
                messages.error(
                    request, 'Selected package type is no longer available.')
                return render(request, 'admin/packages/edit.html', {
                    'package': package,
                    'admin_menu': get_admin_menu(request),
                    'thumbnail_slots': _build_package_thumbnail_slots(package),
                    'package_inclusion_editor_items': _build_package_inclusion_editor_items(
                        package_inclusion_items,
                    ),
                    'option_editor_groups': _build_option_editor_groups(
                        _filter_removed_package_cake_decorations(
                            customization_options,
                        ),
                        PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                    ),
                })

            inclusion_summary = '\n'.join(
                _format_package_inclusion_lines(package_inclusion_items)
            )
            customization_options = {
                **customization_options,
                'included_items': package_inclusion_items,
            }

            package.name = request.POST.get('name')
            package.package_type = package_type
            package.description = request.POST.get('description')
            package.base_price = request.POST.get('base_price')
            package.stock = _parse_stock_quantity(request.POST.get('stock', 0))
            package.status = request.POST.get('status')
            package.features = inclusion_summary
            package.included_items = inclusion_summary
            package.customization_options = customization_options

            uploaded_image = request.FILES.get('image')
            if uploaded_image:
                package.image = uploaded_image

            package_inclusion_items = _apply_package_inclusion_image_uploads(
                package_inclusion_items,
                request.FILES,
                object_id=package.id,
            )
            customization_options = _apply_option_image_uploads(
                customization_options,
                PACKAGE_CUSTOMIZATION_GROUP_SPECS,
                request.FILES,
                product_prefix='package-options',
                object_id=package.id,
            )
            customization_options['included_items'] = package_inclusion_items
            package.customization_options = customization_options

            package.save()
            thumbnail_removals = {
                slot_order
                for slot_order in range(1, MAX_PACKAGE_THUMBNAILS + 1)
                if request.POST.get(f'remove_thumbnail_{slot_order}') == 'on'
            }
            _sync_package_thumbnails(
                package, request.FILES, thumbnail_removals)
            updated_option_images = _collect_option_image_paths(
                customization_options,
                PACKAGE_CUSTOMIZATION_GROUP_SPECS,
            )
            _delete_option_images(
                previous_option_images - updated_option_images,
            )
            updated_inclusion_images = _collect_package_inclusion_image_paths(
                package_inclusion_items,
            )
            _delete_option_images(
                previous_inclusion_images - updated_inclusion_images,
            )
            if previous_stock != package.stock:
                _log_staff_activity(
                    request.user,
                    'package_stock_updated',
                    f'Updated stock for package "{package.name}" ({package.product_code or "Not assigned"}) from {previous_stock} to {package.stock}.',
                    'package',
                    package.id,
                )
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
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error updating package: {str(e)}')

    return render(request, 'admin/packages/edit.html', {
        'package': package,
        'admin_menu': get_admin_menu(request),
        'thumbnail_slots': _build_package_thumbnail_slots(package),
        'package_inclusion_editor_items': _build_package_inclusion_editor_items(
            _get_package_inclusion_items(package, for_display=False),
        ),
        'option_editor_groups': _build_option_editor_groups(
            _filter_removed_package_cake_decorations(
                package.customization_options,
            ),
            PACKAGE_CUSTOMIZATION_GROUP_SPECS,
        ),
    })


@login_required
@require_POST
def admin_package_delete(request, package_id):
    """Archive or restore a package"""
    access_denied = _require_admin_roles(
        request, PACKAGE_PRODUCT_ROLE_VALUES)
    if access_denied:
        return access_denied

    package = get_object_or_404(Package, id=package_id)
    package_name = package.name
    if package.is_archived:
        _restore_model_instance(package, status='active')
        _log_staff_activity(
            request.user,
            'package_restored',
            f'Restored package "{package_name}".',
            'package',
            package_id,
        )
        messages.success(
            request, f'Package "{package_name}" restored successfully!')
    else:
        _archive_model_instance(package, status='inactive')
        _log_staff_activity(
            request.user,
            'package_archived',
            f'Archived package "{package_name}".',
            'package',
            package_id,
        )
        messages.success(
            request, f'Package "{package_name}" archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_packages'))


# ============================================
# ADMIN PACKAGE ORDERS
# ============================================

@login_required
def admin_package_orders(request):
    """List all package orders"""
    access_denied = _require_admin_roles(
        request, PACKAGE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    orders_queryset = _annotate_admin_order_activity(
        PackageOrder.objects.select_related('user', 'package').filter(
            is_archived=is_archived_view,
        ),
        'package_order',
    ).order_by('-last_activity_at', '-created_at')
    if _get_user_role_value(request.user) == 'packager':
        orders_queryset = orders_queryset.filter(order_status__in=[
                                                 'confirmed', 'preparing', 'ready_for_pickup', 'out_for_delivery', 'completed'])
    orders, orders_pagination = _paginate_admin_queryset(
        request, orders_queryset, 'page')
    _decorate_admin_orders_with_actions(orders, request)
    return render(request, 'admin/orders/package_orders.html', {
        'orders': orders,
        'orders_pagination': orders_pagination,
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_view(request, order_id):
    """View package order details"""
    access_denied = _require_admin_roles(
        request, PACKAGE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    order = get_object_or_404(
        PackageOrder.objects.select_related(
            'user', 'package').prefetch_related(_build_admin_order_payment_prefetch(), 'package__thumbnails'),
        id=order_id,
    )
    if not _can_view_order_for_role(request.user, order):
        messages.error(request, 'Permission denied')
        return redirect('admin_package_orders')
    back_url = _get_safe_admin_return_url(request, 'admin_package_orders')
    return render(request, 'admin/orders/package_order_view.html', {
        'order': order,
        'back_url': back_url,
        'back_label': 'Back to Payments' if back_url.startswith(reverse('admin_payments')) else 'Back to Package Orders',
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_package_order_update(request, order_id):
    """Update package order status"""
    access_denied = _require_admin_roles(
        request, PACKAGE_ORDER_ROLE_VALUES)
    if access_denied:
        return access_denied

    if request.method == 'POST':
        order = get_object_or_404(PackageOrder, id=order_id)
        if not _can_view_order_for_role(request.user, order):
            messages.error(request, 'Permission denied')
            return redirect(_get_safe_admin_return_url(request, 'admin_package_orders'))
        previous_status = order.order_status
        new_status = request.POST.get('status')
        allowed_statuses = {value for value,
                            _ in _get_allowed_status_updates(request.user, order)}

        if new_status and new_status != previous_status:
            if new_status not in allowed_statuses:
                messages.error(
                    request, 'You are not allowed to apply that status change.')
                return redirect(_get_safe_admin_return_url(request, 'admin_package_orders'))
            try:
                if new_status == 'completed':
                    _commit_order_stock(order, request.user)
                elif getattr(order, 'stock_deducted', False):
                    _restore_order_stock(order, request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(_get_safe_admin_return_url(request, 'admin_package_orders'))
            order.order_status = new_status
            order.save(update_fields=['order_status', 'updated_at'])
            if new_status == 'cancelled':
                _cancel_outstanding_balance_payments(order)
            _create_order_status_notification(
                order, 'package', previous_status)
            _log_staff_activity(
                request.user,
                'package_order_status_updated',
                f'Updated package order #{order.id} from {previous_status} to {order.order_status}.',
                'package_order',
                order.id,
            )
            messages.success(
                request, f'Package Order #{order.id} status updated to {order.get_order_status_display()}')
    return redirect(_get_safe_admin_return_url(request, 'admin_package_orders'))


@login_required
@require_POST
def admin_package_order_delete(request, order_id):
    """Archive or restore a package order"""
    access_denied = _require_admin_roles(
        request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    order = get_object_or_404(PackageOrder, id=order_id)
    order_id_value = order.id
    if order.is_archived:
        _restore_model_instance(order)
        _log_staff_activity(
            request.user,
            'package_order_restored',
            f'Restored package order #{order_id_value}.',
            'package_order',
            order_id_value,
        )
        messages.success(
            request, f'Package Order #{order_id_value} restored successfully!')
    else:
        _archive_model_instance(order)
        _log_staff_activity(
            request.user,
            'package_order_archived',
            f'Archived package order #{order_id_value}.',
            'package_order',
            order_id_value,
        )
        messages.success(
            request, f'Package Order #{order_id_value} archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_package_orders'))


# ============================================
# ADMIN PAYMENTS
# ============================================

@login_required
def admin_payments(request):
    """List all payments"""
    access_denied = _require_admin_roles(
        request, PAYMENT_REVIEW_ROLE_VALUES)
    if access_denied:
        return access_denied

    # Get all payments
    is_archived_view = _is_archived_admin_view(request)
    payments = Payment.objects.select_related(
        'cake_order',
        'cake_order__user',
        'package_order',
        'package_order__user',
    ).filter(is_archived=is_archived_view).order_by('-created_at')

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
    rejected_payments = payments.filter(
        payment_status__in=['rejected', 'cancelled'])
    pending_payments_page, pending_payments_pagination = _paginate_admin_queryset(
        request, pending_payments, 'review_page')
    balance_payments_page, balance_payments_pagination = _paginate_admin_queryset(
        request, balance_payments, 'balance_page')
    verified_payments_page, verified_payments_pagination = _paginate_admin_queryset(
        request, verified_payments, 'verified_page')
    rejected_payments_page, rejected_payments_pagination = _paginate_admin_queryset(
        request, rejected_payments, 'rejected_page')

    return render(request, 'admin/payments/list.html', {
        'payments': payments,
        'pending_payments': pending_payments,
        'pending_payments_page': pending_payments_page,
        'pending_payments_pagination': pending_payments_pagination,
        'balance_payments': balance_payments,
        'balance_payments_page': balance_payments_page,
        'balance_payments_pagination': balance_payments_pagination,
        'verified_payments': verified_payments,
        'verified_payments_page': verified_payments_page,
        'verified_payments_pagination': verified_payments_pagination,
        'rejected_payments': rejected_payments,
        'rejected_payments_page': rejected_payments_page,
        'rejected_payments_pagination': rejected_payments_pagination,
        'can_export_sales': _is_full_access_user(request.user),
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_payment_verify(request, payment_id):
    """Verify/Approve/Reject a payment"""
    access_denied = _require_admin_roles(
        request, PAYMENT_REVIEW_ROLE_VALUES)
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
            payment.payment_status = 'rejected'
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
            _sync_order_rejection_from_payment(payment, request.user)
            _log_staff_activity(
                request.user,
                'payment_status_updated',
                f'Updated payment #{payment.id} from {previous_status} to {payment.payment_status}.',
                'payment',
                payment.id,
            )

    return redirect(_get_safe_admin_return_url(request, 'admin_payments'))


@login_required
@require_POST
def admin_payment_delete(request, payment_id):
    """Archive or restore a completed payment from the admin panel"""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    payment = get_object_or_404(Payment, id=payment_id)

    if payment.is_archived:
        payment_id_value = payment.id
        _restore_model_instance(payment)
        _log_staff_activity(
            request.user,
            'payment_restored',
            f'Restored payment #{payment_id_value}.',
            'payment',
            payment_id_value,
        )
        messages.success(
            request, f'Payment #{payment_id_value} restored successfully!')
        return redirect(_get_safe_admin_return_url(request, 'admin_payments'))

    if payment.payment_status not in ['paid', 'rejected', 'cancelled']:
        messages.error(
            request, 'Only verified or rejected payments can be archived.')
        return redirect(_get_safe_admin_return_url(request, 'admin_payments'))

    payment_id_value = payment.id
    _archive_model_instance(payment)
    _log_staff_activity(
        request.user,
        'payment_archived',
        f'Archived payment #{payment_id_value}.',
        'payment',
        payment_id_value,
    )
    messages.success(
        request, f'Payment #{payment_id_value} archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_payments'))


@login_required
def admin_testimonials(request):
    """List testimonials for moderation."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    testimonials = Testimonial.objects.select_related(
        'user',
        'cake_order__cake',
        'package_order__package',
        'reviewed_by',
    ).filter(is_archived=is_archived_view).order_by('-created_at')

    pending_testimonials = testimonials.filter(status=Testimonial.STATUS_PENDING)
    reviewed_testimonials = testimonials.exclude(status=Testimonial.STATUS_PENDING)
    approved_testimonials = testimonials.filter(
        status=Testimonial.STATUS_APPROVED)

    pending_testimonials_page, pending_testimonials_pagination = _paginate_admin_queryset(
        request, pending_testimonials, 'pending_page')
    reviewed_testimonials_page, reviewed_testimonials_pagination = _paginate_admin_queryset(
        request, reviewed_testimonials, 'reviewed_page')

    return render(request, 'admin/testimonials/list.html', {
        'pending_testimonials_page': pending_testimonials_page,
        'pending_testimonials_pagination': pending_testimonials_pagination,
        'reviewed_testimonials_page': reviewed_testimonials_page,
        'reviewed_testimonials_pagination': reviewed_testimonials_pagination,
        'approved_testimonial_count': approved_testimonials.count(),
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
@require_POST
def admin_testimonial_update(request, testimonial_id):
    """Approve, reject, or hide a testimonial."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    testimonial = get_object_or_404(Testimonial, id=testimonial_id)
    if testimonial.is_archived:
        messages.error(
            request, 'Restore this testimonial before changing its review status.')
        return redirect(_get_safe_admin_return_url(request, 'admin_testimonials'))

    action = (request.POST.get('action') or '').strip().lower()
    admin_note = (request.POST.get('admin_note') or '').strip()
    status_map = {
        'approve': Testimonial.STATUS_APPROVED,
        'reject': Testimonial.STATUS_REJECTED,
        'hide': Testimonial.STATUS_HIDDEN,
    }
    next_status = status_map.get(action)
    if next_status is None:
        messages.error(request, 'Unknown testimonial action.')
        return redirect(_get_safe_admin_return_url(request, 'admin_testimonials'))

    previous_status = testimonial.status
    testimonial.status = next_status
    testimonial.admin_note = admin_note
    testimonial.reviewed_by = request.user
    testimonial.reviewed_at = timezone.now()
    testimonial.save(update_fields=[
        'status',
        'admin_note',
        'reviewed_by',
        'reviewed_at',
        'updated_at',
    ])

    _log_staff_activity(
        request.user,
        f'testimonial_{next_status}',
        f'Updated testimonial #{testimonial.id} from {previous_status} to {next_status}.',
        'testimonial',
        testimonial.id,
    )
    messages.success(
        request, f'Testimonial #{testimonial.id} marked as {testimonial.get_status_display().lower()}.')
    return redirect(_get_safe_admin_return_url(request, 'admin_testimonials'))


@login_required
@require_POST
def admin_testimonial_delete(request, testimonial_id):
    """Archive or restore a testimonial."""
    access_denied = _require_admin_roles(request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    testimonial = get_object_or_404(Testimonial, id=testimonial_id)

    if testimonial.is_archived:
        _restore_model_instance(testimonial)
        _log_staff_activity(
            request.user,
            'testimonial_restored',
            f'Restored testimonial #{testimonial.id}.',
            'testimonial',
            testimonial.id,
        )
        messages.success(
            request, f'Testimonial #{testimonial.id} restored successfully!')
        return redirect(_get_safe_admin_return_url(request, 'admin_testimonials'))

    _archive_model_instance(testimonial)
    _log_staff_activity(
        request.user,
        'testimonial_archived',
        f'Archived testimonial #{testimonial.id}.',
        'testimonial',
        testimonial.id,
    )
    messages.success(
        request, f'Testimonial #{testimonial.id} archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_testimonials'))


@login_required
def admin_payments_export(request, file_format):
    """Export paid sales records to XLSX or PDF."""
    access_denied = _require_admin_roles(
        request, FULL_ACCESS_ROLE_VALUES)
    if access_denied:
        return access_denied

    sales_payments = Payment.objects.select_related(
        'cake_order',
        'cake_order__user',
        'package_order',
        'package_order__user',
    ).filter(
        payment_status='paid',
        is_archived=False,
    ).order_by('-paid_at', '-created_at')
    sales_rows = _build_sales_export_rows(sales_payments)

    if file_format == 'xlsx':
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError:
            messages.error(
                request, 'XLSX export is not available until openpyxl is installed.')
            return redirect('admin_payments')

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'Sales Report'
        headers = [
            'Payment ID',
            'Order Type',
            'Order ID',
            'Customer',
            'Purpose',
            'Method',
            'GCash Reference Number',
            'Amount',
            'Paid At',
        ]
        worksheet.append(headers)

        for header_cell in worksheet[1]:
            header_cell.font = Font(bold=True)

        for row in sales_rows:
            worksheet.append([
                row['payment_id'],
                row['order_type'],
                row['order_id'],
                row['customer_name'],
                row['payment_purpose'],
                row['payment_method'],
                row['reference_number'],
                float(row['amount']),
                timezone.localtime(row['paid_at']).strftime('%Y-%m-%d %H:%M'),
            ])

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response[
            'Content-Disposition'] = f'attachment; filename="{_build_sales_export_filename("xlsx")}"'
        workbook.save(response)
        _log_staff_activity(
            request.user,
            'sales_report_exported',
            'Exported the paid sales report in XLSX format.',
            'report',
        )
        return response

    if file_format == 'pdf':
        try:
            from reportlab.lib.pagesizes import landscape, letter
            from reportlab.pdfgen import canvas
        except ImportError:
            messages.error(
                request, 'PDF export is not available until reportlab is installed.')
            return redirect('admin_payments')

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
        width, height = landscape(letter)
        y_position = height - 40

        pdf.setFont('Helvetica-Bold', 16)
        pdf.drawString(40, y_position, 'Hanilies Cakeshoppe Sales Report')
        y_position -= 20
        pdf.setFont('Helvetica', 10)
        pdf.drawString(
            40, y_position, f'Generated: {timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")}')
        y_position -= 28

        pdf.setFont('Helvetica-Bold', 9)
        pdf.drawString(40, y_position, 'Payment')
        pdf.drawString(95, y_position, 'Order')
        pdf.drawString(165, y_position, 'Customer')
        pdf.drawString(330, y_position, 'Purpose')
        pdf.drawString(410, y_position, 'Method')
        pdf.drawString(475, y_position, 'Amount')
        pdf.drawString(550, y_position, 'Paid At')
        y_position -= 18
        pdf.setFont('Helvetica', 8)

        for row in sales_rows:
            if y_position <= 40:
                pdf.showPage()
                y_position = height - 40
                pdf.setFont('Helvetica-Bold', 9)
                pdf.drawString(40, y_position, 'Payment')
                pdf.drawString(95, y_position, 'Order')
                pdf.drawString(165, y_position, 'Customer')
                pdf.drawString(330, y_position, 'Purpose')
                pdf.drawString(410, y_position, 'Method')
                pdf.drawString(475, y_position, 'Amount')
                pdf.drawString(550, y_position, 'Paid At')
                y_position -= 18
                pdf.setFont('Helvetica', 8)

            pdf.drawString(40, y_position, f'#{row["payment_id"]}')
            pdf.drawString(
                95, y_position, f'{row["order_type"]} #{row["order_id"]}')
            pdf.drawString(165, y_position, row['customer_name'][:28])
            pdf.drawString(330, y_position, row['payment_purpose'][:14])
            pdf.drawString(410, y_position, row['payment_method'][:10])
            pdf.drawString(475, y_position, f'PHP {row["amount"]}')
            pdf.drawString(550, y_position, timezone.localtime(
                row['paid_at']).strftime('%Y-%m-%d'))
            y_position -= 16

        pdf.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response[
            'Content-Disposition'] = f'attachment; filename="{_build_sales_export_filename("pdf")}"'
        _log_staff_activity(
            request.user,
            'sales_report_exported',
            'Exported the paid sales report in PDF format.',
            'report',
        )
        return response

    messages.error(request, 'Unsupported export format requested.')
    return redirect('admin_payments')


@login_required
def admin_refunds(request):
    """List customer cancellation and refund requests."""
    access_denied = _require_admin_roles(
        request, {'owner', 'admin', 'manager', 'supervisor', 'cashier'})
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
            'hide_demo_panel': True,
    })


@login_required
@require_POST
def admin_refund_update(request, refund_id):
    """Approve, reject, or process a refund request."""
    refund_request = get_object_or_404(RefundRequest, id=refund_id)
    action = request.POST.get('action')

    if action in ['approve', 'reject']:
        access_denied = _require_admin_roles(
            request, {'owner', 'admin', 'manager', 'supervisor'})
    else:
        access_denied = _require_admin_roles(
            request, {'owner', 'admin', 'cashier'})
    if access_denied:
        return access_denied

    order = refund_request.cake_order or refund_request.package_order
    order_type = 'cake' if refund_request.cake_order_id else 'package'

    if action == 'approve':
        if _user_has_any_role(request.user, {'owner', 'admin'}) and request.POST.get('penalty_fee'):
            custom_penalty = _quantize_amount(request.POST.get('penalty_fee'))
            refundable_base = _get_paid_or_pending_gcash_total(order)
            refund_request.penalty_fee = min(refundable_base, custom_penalty)
            refund_request.refundable_amount = _quantize_amount(
                refundable_base - refund_request.penalty_fee)
        refund_request.status = 'approved'
        refund_request.approved_by = request.user
        refund_request.reviewed_at = timezone.now()
        refund_request.internal_note = request.POST.get(
            'internal_note', refund_request.internal_note).strip()
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
        messages.success(
            request, f'Refund request #{refund_request.id} approved successfully.')
    elif action == 'reject':
        refund_request.status = 'rejected'
        refund_request.approved_by = request.user
        refund_request.reviewed_at = timezone.now()
        refund_request.internal_note = request.POST.get(
            'internal_note', refund_request.internal_note).strip()
        refund_request.save()
        _create_refund_status_notification(refund_request)
        _log_staff_activity(
            request.user,
            'refund_rejected',
            f'Rejected refund request #{refund_request.id}.',
            'refund_request',
            refund_request.id,
        )
        messages.success(
            request, f'Refund request #{refund_request.id} rejected successfully.')
    elif action == 'process':
        if refund_request.status not in ['approved', 'processing']:
            messages.error(request, 'Only approved refunds can be processed.')
            return redirect('admin_refunds')

        refund_request.status = 'processed'
        refund_request.processed_by = request.user
        refund_request.processed_at = timezone.now()
        refund_request.refund_reference_number = request.POST.get(
            'refund_reference_number', '').strip()
        refund_request.internal_note = request.POST.get(
            'internal_note', refund_request.internal_note).strip()
        refund_request.save()
        _create_refund_status_notification(refund_request)
        _log_staff_activity(
            request.user,
            'refund_processed',
            f'Processed refund request #{refund_request.id}.',
            'refund_request',
            refund_request.id,
        )
        messages.success(
            request, f'Refund request #{refund_request.id} processed successfully.')

    return redirect('admin_refunds')


@login_required
def admin_activity_logs(request):
    """List recorded audit trail entries"""
    access_denied = _require_admin_roles(request, AUDIT_TRAIL_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    current_tab = request.GET.get('tab', 'records').strip().lower()
    if current_tab not in {'records', 'export'}:
        current_tab = 'records'

    base_queryset = ActivityLog.objects.select_related('actor').filter(
        is_archived=is_archived_view,
    )
    filter_state = _normalize_activity_log_filter_state(
        request,
        export_scope=current_tab == 'export',
    )
    activity_logs_queryset = _filter_activity_logs_queryset(
        base_queryset, filter_state)
    activity_logs_page, activity_logs_pagination = _paginate_admin_queryset(
        request,
        activity_logs_queryset,
        'logs_page',
        per_page=12,
    )

    for activity_log in activity_logs_page.object_list:
        activity_log.display_actor = (
            activity_log.actor.username if activity_log.actor else 'Deleted user'
        )
        activity_log.display_action = _format_activity_label(
            activity_log.action)
        activity_log.display_time = timezone.localtime(
            activity_log.created_at).strftime('%I:%M %p')
        activity_log.display_target = _build_activity_log_target_label(
            activity_log)
        activity_log.display_module = _format_activity_label(
            activity_log.target_type)
        activity_log.display_record_id = (
            f'#{activity_log.target_id}' if activity_log.target_id else '-'
        )
        activity_log.display_created_at = timezone.localtime(
            activity_log.created_at)
        activity_log.exact_timestamp = activity_log.display_created_at.strftime(
            '%Y-%m-%d %H:%M:%S'
        )
        activity_log.action_badge_key = _get_activity_action_key(
            activity_log.action)
        (
            activity_log.role_badge_key,
            activity_log.role_badge_label,
        ) = _get_activity_role_badge(activity_log.actor, activity_log.actor_role)

    action_options = list(
        base_queryset.exclude(action='').order_by(
            'action').values_list('action', flat=True).distinct()
    )
    action_groups = _build_activity_log_action_groups(
        action_options,
        filter_state['action_values'],
    )
    target_type_options = list(
        base_queryset.exclude(target_type='').order_by(
            'target_type').values_list('target_type', flat=True).distinct()
    )
    actor_options = list(
        User.objects.filter(activity_logs__in=base_queryset)
        .order_by('username')
        .distinct()
        .values('id', 'username')
    )

    records_tab_query = _build_activity_log_query(
        request, tab='records', logs_page=None, export_page=None)
    export_tab_query = _build_activity_log_query(
        request, tab='export', logs_page=None, export_page=None)
    reset_query = _build_activity_log_query(
        request,
        q=None,
        action=None,
        target_type=None,
        actor=None,
        record_id=None,
        date_from=None,
        date_to=None,
        logs_page=None,
        export_page=None,
    )
    archive_toggle_query = _build_activity_log_query(
        request,
        archived=None if is_archived_view else '1',
        logs_page=None,
        export_page=None,
    )
    if is_archived_view:
        archive_toggle_query.pop('archived', None)

    export_context_query = _build_activity_log_query(
        request,
        tab='export',
        logs_page=None,
        export_page=None,
    )
    export_preview_page, export_preview_pagination = _paginate_admin_queryset(
        request,
        activity_logs_queryset,
        'export_page',
        per_page=10,
    )
    export_rows = _build_activity_log_export_rows(
        export_preview_page.object_list)

    date_range_label = None
    if filter_state['date_from_value'] and filter_state['date_to_value']:
        date_range_label = (
            f"{filter_state['date_from_value'].strftime('%b %d, %Y')}"
            f" - {filter_state['date_to_value'].strftime('%b %d, %Y')}"
        )

    return render(request, 'admin/activity_logs.html', {
        'activity_logs': activity_logs_page,
        'activity_logs_pagination': activity_logs_pagination,
        'activity_log_summary': _build_activity_log_summary(activity_logs_queryset),
        'action_groups': action_groups,
        'target_type_options': target_type_options,
        'actor_options': actor_options,
        'current_tab': current_tab,
        'current_filters': filter_state,
        'active_filter_chips': _build_activity_log_filter_chips(
            filter_state,
            actor_options,
        ),
        'records_tab_url': _build_path_with_query(request.path, records_tab_query),
        'export_tab_url': _build_path_with_query(request.path, export_tab_query),
        'reset_filters_url': _build_path_with_query(request.path, reset_query),
        'archive_toggle_url': _build_path_with_query(request.path, archive_toggle_query),
        'export_pdf_url': _build_path_with_query(
            reverse('admin_activity_logs_export', args=['pdf']),
            export_context_query,
        ),
        'export_csv_url': _build_path_with_query(
            reverse('admin_activity_logs_export', args=['csv']),
            export_context_query,
        ),
        'export_xlsx_url': _build_path_with_query(
            reverse('admin_activity_logs_export', args=['xlsx']),
            export_context_query,
        ),
        'print_url': _build_path_with_query(
            reverse('admin_activity_logs_print'),
            export_context_query,
        ),
        'export_preview_rows': export_rows,
        'export_preview_page': export_preview_page,
        'export_preview_pagination': export_preview_pagination,
        'export_window_days': AUDIT_EXPORT_MAX_DAYS,
        'date_range_label': date_range_label,
        'current_page_url': request.get_full_path(),
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_activity_logs_export(request, file_format):
    """Export filtered audit trail entries to CSV, XLSX, or PDF."""
    access_denied = _require_admin_roles(request, AUDIT_TRAIL_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    filter_state = _normalize_activity_log_filter_state(
        request, export_scope=True)
    activity_logs_queryset = _filter_activity_logs_queryset(
        ActivityLog.objects.select_related(
            'actor').filter(is_archived=is_archived_view),
        filter_state,
    )
    export_rows = _build_activity_log_export_rows(activity_logs_queryset)
    report_title = 'Hanilies Cakeshoppe Audit Trail Report'
    date_range_label = (
        f"{filter_state['date_from_value'].strftime('%b %d, %Y')}"
        f" - {filter_state['date_to_value'].strftime('%b %d, %Y')}"
    )

    if file_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="{_build_activity_log_export_filename("csv")}"'
        )
        writer = csv.writer(response)
        writer.writerow(['Hanilies Cakeshoppe Audit Trail Report'])
        writer.writerow([f'Date Range: {date_range_label}'])
        writer.writerow([
            'Date',
            'User',
            'Role',
            'Action',
            'Module',
            'Record ID',
            'Target',
            'Description',
        ])
        for row in export_rows:
            writer.writerow([
                row['date_display'],
                row['actor'],
                row['role'],
                row['action'],
                row['module'],
                row['record_id'] or '-',
                row['target'],
                row['description'],
            ])
        _log_staff_activity(
            request.user,
            'audit_trail_exported',
            'Exported the audit trail in CSV format.',
            'report',
        )
        return response

    if file_format == 'xlsx':
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError:
            messages.error(
                request,
                'XLSX export is not available until openpyxl is installed.',
            )
            return redirect(_get_safe_admin_return_url(request, 'admin_activity_logs'))

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'Audit Trail'
        worksheet.append(['Hanilies Cakeshoppe Audit Trail Report'])
        worksheet.append([f'Date Range: {date_range_label}'])
        worksheet.append([
            'Date',
            'User',
            'Role',
            'Action',
            'Target',
            'Description',
        ])

        for header_cell in worksheet[3]:
            header_cell.font = Font(bold=True)

        for row in export_rows:
            worksheet.append([
                row['date_display'],
                row['actor'],
                row['role'],
                row['action'],
                row['target'],
                row['description'],
            ])

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{_build_activity_log_export_filename("xlsx")}"'
        )
        workbook.save(response)
        _log_staff_activity(
            request.user,
            'audit_trail_exported',
            'Exported the audit trail in XLSX format.',
            'report',
        )
        return response

    if file_format == 'pdf':
        try:
            from reportlab.lib.pagesizes import landscape, letter
            from reportlab.pdfgen import canvas
        except ImportError:
            messages.error(
                request,
                'PDF export is not available until reportlab is installed.',
            )
            return redirect(_get_safe_admin_return_url(request, 'admin_activity_logs'))

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
        width, height = landscape(letter)
        y_position = height - 40

        pdf.setFont('Helvetica-Bold', 16)
        pdf.drawString(40, y_position, report_title)
        y_position -= 18
        pdf.setFont('Helvetica', 10)
        pdf.drawString(40, y_position, f'Date Range: {date_range_label}')
        y_position -= 14
        pdf.drawString(
            40,
            y_position,
            f'Generated: {timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")}',
        )
        y_position -= 26

        pdf.setFont('Helvetica-Bold', 9)
        pdf.drawString(40, y_position, 'Date')
        pdf.drawString(120, y_position, 'User')
        pdf.drawString(205, y_position, 'Role')
        pdf.drawString(315, y_position, 'Action')
        pdf.drawString(410, y_position, 'Target')
        pdf.drawString(505, y_position, 'Description')
        y_position -= 18
        pdf.setFont('Helvetica', 8)

        for row in export_rows:
            if y_position <= 40:
                pdf.showPage()
                y_position = height - 40
                pdf.setFont('Helvetica-Bold', 9)
                pdf.drawString(40, y_position, 'Date')
                pdf.drawString(120, y_position, 'User')
                pdf.drawString(205, y_position, 'Role')
                pdf.drawString(315, y_position, 'Action')
                pdf.drawString(410, y_position, 'Target')
                pdf.drawString(505, y_position, 'Description')
                y_position -= 18
                pdf.setFont('Helvetica', 8)

            pdf.drawString(40, y_position, row['date_display'])
            pdf.drawString(120, y_position, row['actor'][:14])
            pdf.drawString(205, y_position, row['role'][:18])
            pdf.drawString(315, y_position, row['action'][:15])
            pdf.drawString(410, y_position, row['target'][:16])
            pdf.drawString(505, y_position, row['description'][:38])
            y_position -= 16

        pdf.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="{_build_activity_log_export_filename("pdf")}"'
        )
        _log_staff_activity(
            request.user,
            'audit_trail_exported',
            'Exported the audit trail in PDF format.',
            'report',
        )
        return response

    messages.error(request, 'Unsupported export format requested.')
    return redirect(_get_safe_admin_return_url(request, 'admin_activity_logs'))


@login_required
def admin_activity_logs_print(request):
    """Render a print-friendly audit trail page limited to a 30-day window."""
    access_denied = _require_admin_roles(request, AUDIT_TRAIL_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    filter_state = _normalize_activity_log_filter_state(
        request, export_scope=True)
    activity_logs_queryset = _filter_activity_logs_queryset(
        ActivityLog.objects.select_related(
            'actor').filter(is_archived=is_archived_view),
        filter_state,
    )
    _log_staff_activity(
        request.user,
        'audit_trail_print_preview',
        'Opened the audit trail print preview.',
        'report',
    )
    return render(request, 'admin/activity_logs_print.html', {
        'activity_logs': _build_activity_log_export_rows(activity_logs_queryset),
        'date_range_label': (
            f"{filter_state['date_from_value'].strftime('%b %d, %Y')}"
            f" - {filter_state['date_to_value'].strftime('%b %d, %Y')}"
        ),
        'export_window_days': AUDIT_EXPORT_MAX_DAYS,
        'generated_at': timezone.localtime(timezone.now()),
        'is_archived_view': is_archived_view,
    })


@login_required
@require_POST
def admin_activity_log_delete(request, log_id):
    """Archive or restore an audit trail entry from the admin panel"""
    access_denied = _require_admin_roles(request, AUDIT_TRAIL_ROLE_VALUES)
    if access_denied:
        return access_denied

    activity_log = get_object_or_404(ActivityLog, id=log_id)
    if activity_log.is_archived:
        _restore_model_instance(activity_log)
        messages.success(request, 'Audit trail entry restored successfully!')
    else:
        _archive_model_instance(activity_log)
        messages.success(request, 'Audit trail entry archived successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_activity_logs'))


# ============================================
# ADMIN USERS (Role Management)
# ============================================

@login_required
def admin_users(request):
    """List all users"""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
    if access_denied:
        return access_denied

    is_archived_view = _is_archived_admin_view(request)
    users = list(User.objects.filter(
        is_active=not is_archived_view).order_by('-date_joined'))
    staff_users = []
    customer_users = []

    for user in users:
        role_value = _get_user_role_value(user)
        user.admin_list_role_value = role_value
        if role_value == 'customer' and not user.is_staff and not user.is_superuser:
            customer_users.append(user)
        else:
            staff_users.append(user)

    return render(request, 'admin/users/list.html', {
        'users': users,
        'staff_users': staff_users,
        'customer_users': customer_users,
        'is_archived_view': is_archived_view,
        'admin_menu': get_admin_menu(request)
    })


@login_required
def admin_user_view(request, user_id):
    """View a customer or staff account profile from the admin panel."""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
    if access_denied:
        return access_denied

    view_user = get_object_or_404(User.objects.select_related('profile'), id=user_id)
    profile = getattr(view_user, 'profile', None)
    role_value = _get_user_role_value(view_user) or 'customer'
    role_display = 'Owner' if role_value == 'owner' else (
        profile.get_role_display() if profile else role_value.replace('_', ' ').title()
    )
    is_customer_account = (
        role_value == 'customer'
        and not view_user.is_staff
        and not view_user.is_superuser
    )

    cake_orders = list(
        CakeOrder.objects.filter(user=view_user)
        .select_related('cake')
        .order_by('-created_at')
    )
    package_orders = list(
        PackageOrder.objects.filter(user=view_user)
        .select_related('package')
        .order_by('-created_at')
    )

    recent_order_history = sorted(
        [
            {
                'type_label': 'Cake Order',
                'order_id': order.id,
                'product_name': order.cake.name if order.cake else 'Custom Cake',
                'product_code': order.cake.product_code if order.cake else '',
                'status_key': order.order_status,
                'status_label': order.get_order_status_display(),
                'total_price': order.total_price or Decimal('0.00'),
                'created_at': order.created_at,
            }
            for order in cake_orders
        ] + [
            {
                'type_label': 'Package Order',
                'order_id': order.id,
                'product_name': order.package.name if order.package else 'Custom Package',
                'product_code': order.package.product_code if order.package else '',
                'status_key': order.order_status,
                'status_label': order.get_order_status_display(),
                'total_price': order.total_price or Decimal('0.00'),
                'created_at': order.created_at,
            }
            for order in package_orders
        ],
        key=lambda item: item['created_at'],
        reverse=True,
    )[:10]

    total_orders = len(cake_orders) + len(package_orders)
    completed_orders = sum(1 for order in cake_orders if order.order_status == 'completed')
    completed_orders += sum(1 for order in package_orders if order.order_status == 'completed')
    cancelled_orders = sum(1 for order in cake_orders if order.order_status == 'cancelled')
    cancelled_orders += sum(1 for order in package_orders if order.order_status == 'cancelled')
    total_spent = Payment.objects.filter(
        Q(cake_order__user=view_user) | Q(package_order__user=view_user),
        payment_status='paid',
        is_archived=False,
    ).aggregate(total=Sum('amount')).get('total') or Decimal('0.00')

    return render(request, 'admin/users/detail.html', {
        'view_user': view_user,
        'profile': profile,
        'role_display': role_display,
        'account_status_label': 'Active' if view_user.is_active else 'Inactive',
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'cancelled_orders': cancelled_orders,
        'total_spent': total_spent,
        'recent_order_history': recent_order_history,
        'is_customer_account': is_customer_account,
        'admin_menu': get_admin_menu(request),
    })


@login_required
@require_POST
def admin_user_password_reset(request, user_id):
    """Send the standard password reset email to a selected account."""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
    if access_denied:
        return access_denied

    reset_user = get_object_or_404(User, id=user_id)
    if not reset_user.email:
        messages.error(request, f'User "{reset_user.username}" does not have an email address on file.')
        return redirect(_get_safe_admin_return_url(request, 'admin_users'))

    if not reset_user.is_active:
        messages.error(request, f'User "{reset_user.username}" is inactive. Activate the account before sending a password reset email.')
        return redirect(_get_safe_admin_return_url(request, 'admin_users'))

    form = HaniliesPasswordResetForm({'email': reset_user.email})
    if not form.is_valid():
        messages.error(request, 'Unable to send a password reset email for this account right now.')
        return redirect(_get_safe_admin_return_url(request, 'admin_users'))

    try:
        form.save(
            request=request,
            use_https=request.is_secure(),
            email_template_name='registration/password_reset_email.txt',
            subject_template_name='registration/password_reset_subject.txt',
        )
    except Exception as exc:
        messages.error(request, f'Unable to send password reset email: {exc}')
        return redirect(_get_safe_admin_return_url(request, 'admin_users'))

    _log_staff_activity(
        request.user,
        'user_password_reset_sent',
        f'Sent a password reset email to user "{reset_user.username}".',
        'user',
        reset_user.id,
    )
    messages.success(request, f'Password reset email sent to "{reset_user.username}".')
    return redirect(_get_safe_admin_return_url(request, 'admin_users'))


@login_required
def admin_user_add(request):
    """Create a customer or staff account from the admin panel."""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
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
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Email already registered.')
        else:
            candidate_user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            password_errors = _get_password_validation_errors(
                password, user=candidate_user)
            if password_errors:
                for password_error in password_errors:
                    messages.error(request, password_error)
                return render(request, 'admin/users/add.html', {
                    'role_choices': ROLE_CHOICES,
                    'admin_menu': get_admin_menu(request),
                        'hide_demo_panel': True,
    })

            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            _assign_user_role(new_user, role_value,
                              phone=phone, address=address)

            _log_staff_activity(
                request.user,
                'user_created',
                f'Created user "{new_user.username}" with role {role_value}.',
                'user',
                new_user.id,
            )

            messages.success(
                request, f'User "{new_user.username}" created successfully!')
            return redirect('admin_users')

    return render(request, 'admin/users/add.html', {
        'role_choices': ROLE_CHOICES,
        'admin_menu': get_admin_menu(request),
            'hide_demo_panel': True,
    })


@login_required
def admin_user_edit(request, user_id):
    """Edit user profile"""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
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
    """Archive or restore a user from the admin panel"""
    access_denied = _require_admin_roles(request, USER_MANAGEMENT_ROLE_VALUES)
    if access_denied:
        return access_denied

    delete_user = get_object_or_404(User, id=user_id)

    if delete_user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect(_get_safe_admin_return_url(request, 'admin_users'))

    username = delete_user.username
    if delete_user.is_active:
        delete_user.is_active = False
        delete_user.save(update_fields=['is_active'])
        _log_staff_activity(
            request.user,
            'user_archived',
            f'Archived user "{username}".',
            'user',
            user_id,
        )
        messages.success(request, f'User "{username}" archived successfully!')
    else:
        delete_user.is_active = True
        delete_user.save(update_fields=['is_active'])
        _log_staff_activity(
            request.user,
            'user_restored',
            f'Restored user "{username}".',
            'user',
            user_id,
        )
        messages.success(request, f'User "{username}" restored successfully!')
    return redirect(_get_safe_admin_return_url(request, 'admin_users'))


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
            address=getattr(
                getattr(edit_user, 'profile', None), 'address', ''),
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













