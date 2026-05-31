from .models import Cake, CakeOrder, Package, PackageOrder, Payment
from django.contrib.auth.models import User

def user_role_context(request):
    """Add user role to all templates"""
    if request.user.is_authenticated:
        role = getattr(request.user, 'profile', None)
        return {
            'user_role': role.role if role else 'customer',
            'user_role_display': role.get_role_display() if role else 'Customer - Customer Portal',
        }
    return {}

def admin_dashboard_stats(request):
    """Add stats for admin dashboard"""
    if request.user.is_authenticated and request.user.is_staff:
        try:
            return {
                'cake_count': Cake.objects.filter(is_active=True).count(),
                'cake_orders': CakeOrder.objects.count(),
                'packages': Package.objects.filter(status='active').count(),
                'package_orders': PackageOrder.objects.count(),
                'pending_payments': Payment.objects.filter(payment_status='pending').count(),
                'total_users': User.objects.filter(is_active=True).count(),
            }
        except:
            pass
    return {}