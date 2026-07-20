"""Small, independently testable modules for the New Demo Bot."""

PACE_OPTIONS = [
    {'id': 'superfast', 'label': 'Super Fast', 'delay_ms': 450},
    {'id': 'fast', 'label': 'Fast', 'delay_ms': 900},
    {'id': 'normal', 'label': 'Normal', 'delay_ms': 1500},
    {'id': 'slow', 'label': 'Slow', 'delay_ms': 2400},
]

DEMO_SESSION_ACTIONS = {
    'start_admin': 'start_admin',
    'logout': 'logout',
}

DEMO_MODULES = [
    {
        'id': 'customer',
        'title': 'Customer Flow',
        'audience': 'Customer',
        'access': 'public',
        'icon': 'user',
        'description': 'Presents the customer ordering journey from registration through order confirmation.',
        'steps': [
            {
                'id': 'intro',
                'route': 'home',
                'selector': '.navbar-brand, main',
                'title': 'Introduction',
                'message': 'Opens the homepage and shows the guided welcome message.',
            },
            {
                'id': 'customer_registration',
                'route': 'register',
                'selector': 'form, main',
                'title': 'Customer Registration',
                'message': 'Completes the live customer registration form with sample data.',
            },
            {
                'id': 'customer_login',
                'route': 'login',
                'selector': 'form, main',
                'title': 'Customer Login',
                'message': 'Logs in with the newly registered demo customer account.',
            },
            {
                'id': 'homepage_walkthrough',
                'route': 'home',
                'selector': '.content-wrapper, main',
                'title': 'Homepage Walkthrough',
                'message': 'Highlights navigation, featured content, and key customer sections.',
            },
            {
                'id': 'cake_ordering',
                'route': 'cakes',
                'selector': '.content-wrapper, main',
                'title': 'Cake Ordering',
                'message': 'Browses cakes, displays a showcase item, and opens the cake order flow.',
            },
            {
                'id': 'customize_cake',
                'route': 'cake_customize',
                'selector': 'form, main, .content-wrapper',
                'title': 'Customize Your Cake',
                'message': 'Fills the cake customization, delivery, and first order payment flow.',
            },
            {
                'id': 'package_ordering',
                'route': 'packages',
                'selector': '.content-wrapper, main',
                'title': 'Package Ordering',
                'message': 'Browses packages, displays details, and opens the package order flow.',
            },
            {
                'id': 'customize_package_cake',
                'route': 'order_package',
                'selector': 'form, main, .content-wrapper',
                'title': 'Package Selection',
                'message': 'Selects the package inclusions and add-ons, then continues to package cake customization.',
            },
            {
                'id': 'package_cake_design',
                'route': 'package_cake_customize',
                'selector': 'form, main, .content-wrapper',
                'title': 'Customize Your Package Cake',
                'message': 'Configures the bundled cake details, then continues to the final package payment page.',
            },
            {
                'id': 'simulated_payment',
                'route': 'package_payment',
                'selector': 'form, main, .content-wrapper',
                'title': 'Package Payment and Review',
                'message': 'Completes the event details, payment proof, and booking confirmation for the package order.',
            },
            {
                'id': 'customer_order_confirmation',
                'route': 'order_tracking',
                'selector': '.content-wrapper, main',
                'title': 'Customer Order Confirmation',
                'message': 'Opens My Orders and the live tracking details for the submitted demo orders.',
            },
        ],
    },
    {
        'id': 'admin',
        'title': 'Admin Flow',
        'audience': 'Admin',
        'access': 'public',
        'icon': 'gauge-high',
        'description': 'Presents the administrator workflow from dashboard review through audit trail using the isolated demo admin session.',
        'steps': [
            {
                'id': 'administrator_login',
                'route': 'login',
                'selector': 'form, main',
                'title': 'Administrator Login',
                'message': 'Logs out the customer and signs in with the demo administrator account.',
            },
            {
                'id': 'administrator_dashboard',
                'route': 'admin_dashboard',
                'selector': '.content-area, main',
                'title': 'Administrator Dashboard',
                'message': 'Highlights dashboard statistics and recent operational activity.',
            },
            {
                'id': 'cake_order_management',
                'route': 'admin_cake_orders',
                'selector': '.module-card, .content-area',
                'title': 'Cake Order Management',
                'message': 'Reviews the demo cake order, opens the summary, and updates the status.',
            },
            {
                'id': 'package_order_management',
                'route': 'admin_package_orders',
                'selector': '.module-card, .content-area',
                'title': 'Package Order Management',
                'message': 'Reviews the package booking and updates the package order status.',
            },
            {
                'id': 'payment_verification',
                'route': 'admin_payments',
                'selector': '.module-card, .content-area',
                'title': 'Payment Verification',
                'message': 'Opens the payment proof, reviews the reference, and approves the payment.',
            },
            {
                'id': 'cake_management',
                'route': 'admin_cakes',
                'selector': '.module-card, .content-area',
                'title': 'Cake Management',
                'message': 'Demonstrates add, edit, and archive actions for cake products.',
            },
            {
                'id': 'cake_product_edit',
                'route': 'admin_cakes',
                'edit_route': 'admin_cake_edit',
                'selector': 'form, .module-card, .content-area',
                'title': 'Edit Cake Product',
                'message': 'Opens the existing cake product /edit page and highlights editable product details.',
            },
            {
                'id': 'package_management',
                'route': 'admin_packages',
                'selector': '.module-card, .content-area',
                'title': 'Package Management',
                'message': 'Demonstrates add, edit, and archive actions for package products.',
            },
            {
                'id': 'package_product_edit',
                'route': 'admin_packages',
                'edit_route': 'admin_package_edit',
                'selector': 'form, .module-card, .content-area',
                'title': 'Edit Package Product',
                'message': 'Opens the existing package product /edit page and highlights editable package details.',
            },
            {
                'id': 'user_management',
                'route': 'admin_users',
                'selector': '.module-card, .content-area',
                'title': 'User Management',
                'message': 'Demonstrates add, edit, role assignment, and archive actions for a demo user.',
            },
            {
                'id': 'user_edit',
                'route': 'admin_users',
                'edit_route': 'admin_user_edit',
                'selector': 'form, .module-card, .content-area',
                'title': 'Edit User Account',
                'message': 'Opens the existing user /edit page and highlights editable account details.',
            },
            {
                'id': 'audit_trail',
                'route': 'admin_activity_logs',
                'selector': '.module-card, .content-area',
                'title': 'Audit Trail',
                'message': 'Shows filtered activity logs and the export tools.',
            },
            {
                'id': 'logout',
                'route': 'home',
                'selector': 'body',
                'title': 'Logout',
                'message': 'Logs out the administrator and displays the demo completion message.',
            },
        ],
    },
]


def get_demo_module(module_id):
    """Return one independent demo module by id."""
    return next((module for module in DEMO_MODULES if module['id'] == module_id), None)


def get_demo_steps(module_id):
    """Return a copy of one module's steps so callers cannot mutate globals."""
    module = get_demo_module(module_id)
    if module is None:
        return []
    return [dict(step) for step in module['steps']]


def get_full_demo_steps():
    """Combine already-defined independent modules into one full walkthrough."""
    steps = []
    for module in DEMO_MODULES:
        steps.extend(get_demo_steps(module['id']))
    return steps


def validate_demo_modules():
    """Check module and step integrity for tests and future changes."""
    module_ids = [module['id'] for module in DEMO_MODULES]
    if len(module_ids) != len(set(module_ids)):
        return False

    step_ids = []
    for module in DEMO_MODULES:
        if not module.get('steps'):
            return False
        for step in module['steps']:
            required = {'id', 'route', 'selector', 'title', 'message'}
            if not required.issubset(step):
                return False
            step_ids.append(step['id'])
    return len(step_ids) == len(set(step_ids))


def _get_user_role(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    if getattr(user, 'is_superuser', False):
        return 'owner'
    profile = getattr(user, 'profile', None)
    return getattr(profile, 'role', None)


def _user_can_run_access(user, access):
    if access == 'public':
        return True
    if not getattr(user, 'is_authenticated', False):
        return False
    if access == 'authenticated':
        return True
    if access == 'admin':
        return bool(getattr(user, 'is_superuser', False) or _get_user_role(user) in {'owner', 'admin', 'manager', 'supervisor'})
    return False


def _access_reason(user, access):
    if _user_can_run_access(user, access):
        return ''
    if access == 'authenticated':
        return 'Sign in required'
    if access == 'admin':
        return 'Admin access required'
    return 'Unavailable'


def build_demo_bot_payload(resolve_url, user=None, step_url_overrides=None):
    """Build the browser payload while keeping route resolution outside the catalog."""
    step_url_overrides = step_url_overrides or {}
    modules = []
    for module in DEMO_MODULES:
        access = module.get('access', 'public')
        module_payload = {key: value for key,
                          value in module.items() if key != 'steps'}
        module_payload['available'] = _user_can_run_access(user, access)
        module_payload['disabled_reason'] = _access_reason(user, access)
        module_payload['steps'] = []
        for index, step in enumerate(module['steps'], start=1):
            step_payload = dict(step)
            route_name = step['route']
            if step['id'] == 'customer_login' and getattr(user, 'is_authenticated', False):
                route_name = 'profile'
                if step['id'] == 'customer_login':
                    step_payload['title'] = 'Login'
                    step_payload['message'] = 'Login'
            if step['id'] == 'administrator_login' and _user_can_run_access(user, 'admin'):
                route_name = 'admin_dashboard'
                step_payload['title'] = 'Administrator Session Ready'
                step_payload['message'] = 'The current admin session is ready, so the demo opens the dashboard directly.'
            step_payload['url'] = step_url_overrides.get(
                step['id']) or resolve_url(route_name)
            step_payload['module_id'] = module['id']
            step_payload['module_title'] = module['title']
            step_payload['access'] = access
            step_payload['order'] = index
            module_payload['steps'].append(step_payload)
        modules.append(module_payload)

    full_steps = []
    for module in modules:
        full_steps.extend([dict(step) for step in module['steps']])

    full_available = all(module['available'] for module in modules)
    return {
        'name': 'New Demo Bot',
        'version': '3.3',
        'modules': modules,
        'full_demo': {
            'id': 'full',
            'title': 'Full Demo Flow',
            'description': 'Runs the customer flow followed by the admin flow.',
            'available': full_available,
            'disabled_reason': '' if full_available else 'Full demo requires admin access. Sign in with an admin account first.',
            'steps': full_steps,
        },
        'pace_options': PACE_OPTIONS,
        'default_pace': 'normal',
        'session_endpoints': {
            'manage_session': resolve_url('new_demo_bot_session'),
            'actions': DEMO_SESSION_ACTIONS,
        },
        'session': {
            'is_authenticated': bool(getattr(user, 'is_authenticated', False)),
            'is_admin': _user_can_run_access(user, 'admin'),
            'role': _get_user_role(user),
        },
    }
