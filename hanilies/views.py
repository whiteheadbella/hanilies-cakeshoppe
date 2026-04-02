from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q
from django.utils import timezone
from .models import UserProfile, Cake, CakeOrder, Package, PackageOrder, Payment


# ============================================
# MAIN SITE PAGES
# ============================================

def home(request):
    """Home page"""
    return render(request, 'hanilies/home.html')


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
        
        messages.success(request, 'Thank you for your message! We will get back to you soon.')
        return redirect('contact')
    
    return render(request, 'hanilies/contact.html')


def cakes(request):
    """Cakes listing page"""
    cake_list = Cake.objects.filter(is_active=True)
    return render(request, 'hanilies/cakes.html', {'cakes': cake_list})


def packages(request):
    """Packages listing page"""
    package_list = Package.objects.filter(status='active')
    return render(request, 'hanilies/packages.html', {'packages': package_list})


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
        messages.success(request, 'Registration successful! Welcome to Hanilies Cakeshoppe!')
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
            user.profile.address = request.POST.get('address', user.profile.address)
            user.profile.save()
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')
    
    return render(request, 'hanilies/profile.html')


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
    return render(request, 'hanilies/order_tracking.html')


@login_required
def cake_customize(request):
    """Customize a cake"""
    return render(request, 'hanilies/cake_customize.html')


@login_required
def package_order(request):
    """Order a package"""
    return render(request, 'hanilies/package_order.html')


@login_required
def package_cake_customize(request):
    """Customize cake for a package"""
    return render(request, 'hanilies/package_cake_customize.html')


@login_required
def package_payment(request):
    """Process package payment"""
    return render(request, 'hanilies/package_payment.html')


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
        {'name': 'Package Orders', 'url': 'admin_package_orders', 'icon': 'calendar-check'},
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
        messages.error(request, 'You do not have permission to access the admin panel.')
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
            messages.success(request, f'Cake "{cake.name}" added successfully!')
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
            messages.success(request, f'Cake "{cake.name}" updated successfully!')
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
        messages.success(request, f'Order #{order.id} status updated to {order.get_order_status_display()}')
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
            messages.success(request, f'Package "{package.name}" added successfully!')
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
            package.features = request.POST.get('features', '')  # Update features
            package.save()
            messages.success(request, f'Package "{package.name}" updated successfully!')
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
    messages.success(request, f'Package "{package_name}" deleted successfully!')
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
        messages.success(request, f'Package Order #{order.id} status updated to {order.get_order_status_display()}')
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
            messages.success(request, f'Payment #{payment.id} has been approved!')
        elif action == 'reject':
            payment.payment_status = 'failed'
            messages.warning(request, f'Payment #{payment.id} has been rejected.')
        else:
            payment.payment_status = 'verifying'
            messages.info(request, f'Payment #{payment.id} is under verification.')
        
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
        
        messages.success(request, f'User "{edit_user.username}" updated successfully!')
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
        
        messages.success(request, f'User "{edit_user.username}" role updated to {new_role}')
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