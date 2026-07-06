from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from .models import UserProfile, Cake, CakeOrder, CakeCustomization, Package, PackageOrder, Payment

# ========================
# PERMISSION HELPER
# ========================


def user_has_permission(user, model_name, action='view'):
    """Check if user has permission for a model"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not hasattr(user, 'profile'):
        return False

    role = user.profile.role

    permissions = {
        'owner': ['*'],
        'admin': ['*'],
        'manager': ['CakeOrder', 'PackageOrder'],
        'supervisor': ['Cake', 'CakeOrder', 'CakeCustomization', 'Package', 'PackageOrder'],
        'baker': ['Cake', 'CakeOrder', 'CakeCustomization'],
        'packager': ['Package', 'PackageOrder'],
        'cashier': ['Payment'],
        'customer': [],
    }

    allowed = permissions.get(role, [])
    return '*' in allowed or model_name in allowed


# ========================
# CUSTOM ADMIN SITE
# ========================

class HaniliesAdminSite(admin.AdminSite):
    site_header = "Hanilies Cakeshoppe Admin"
    site_title = "Hanilies Admin"
    index_title = "Dashboard"

    # Use custom templates
    index_template = 'admin/dashboard.html'
    app_index_template = 'admin/app_index.html'

    def get_app_list(self, request):
        app_list = super().get_app_list(request)

        if request.user.is_superuser:
            return app_list

        if not hasattr(request.user, 'profile'):
            return []

        role = request.user.profile.role

        allowed_models = {
            'owner': ['Cake', 'CakeOrder', 'CakeCustomization', 'Package', 'PackageOrder', 'Payment', 'User', 'UserProfile'],
            'admin': ['Cake', 'CakeOrder', 'CakeCustomization', 'Package', 'PackageOrder', 'Payment', 'User', 'UserProfile'],
            'manager': ['CakeOrder', 'PackageOrder'],
            'supervisor': ['Cake', 'CakeOrder', 'CakeCustomization', 'Package', 'PackageOrder'],
            'baker': ['Cake', 'CakeOrder', 'CakeCustomization'],
            'packager': ['Package', 'PackageOrder'],
            'cashier': ['Payment'],
            'customer': [],
        }

        allowed = allowed_models.get(role, [])

        filtered_app_list = []
        for app in app_list:
            filtered_models = []
            for model in app.get('models', []):
                if model['object_name'] in allowed or role in ['owner', 'admin']:
                    filtered_models.append(model)
            if filtered_models:
                app['models'] = filtered_models
                filtered_app_list.append(app)

        return filtered_app_list


admin_site = HaniliesAdminSite(name='hanilies_admin')


# ========================
# USER PROFILE INLINE
# ========================

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'


class CustomUserAdmin(UserAdmin):
    inlines = [UserProfileInline]
    list_display = ('username', 'email', 'first_name',
                    'last_name', 'is_staff', 'get_role')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'profile__role')

    def get_role(self, obj):
        if hasattr(obj, 'profile'):
            role_colors = {
                'owner': '#fbbf24',
                'admin': '#f97316',
                'manager': '#3b82f6',
                'supervisor': '#14b8a6',
                'baker': '#ec489a',
                'packager': '#8b5cf6',
                'cashier': '#10b981',
                'customer': '#6b7280',
            }
            color = role_colors.get(obj.profile.role, '#6b7280')
            return format_html('<span style="background: {}; color: white; padding: 4px 12px; border-radius: 20px;">{}</span>',
                               color, obj.profile.get_role_display())
        return '-'
    get_role.short_description = 'Role'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'profile') and request.user.profile.role in ['owner', 'admin']:
            return qs
        return qs.filter(id=request.user.id)


admin_site.register(User, CustomUserAdmin)


# ========================
# MODEL ADMINS
# ========================

class BaseRoleAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return user_has_permission(request.user, self.model.__name__, 'view')

    def has_add_permission(self, request):
        return user_has_permission(request.user, self.model.__name__, 'add')

    def has_change_permission(self, request, obj=None):
        return user_has_permission(request.user, self.model.__name__, 'change')

    def has_delete_permission(self, request, obj=None):
        return user_has_permission(request.user, self.model.__name__, 'delete')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'profile') and request.user.profile.role in ['owner', 'admin']:
            return qs
        if hasattr(qs.model, 'user'):
            return qs.filter(user=request.user)
        return qs


@admin.register(Cake, site=admin_site)
class CakeAdmin(BaseRoleAdmin):
    list_display = ('product_code', 'name', 'category',
                    'price', 'stock', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('product_code', 'name', 'description')
    list_editable = ('price', 'stock', 'is_active')
    readonly_fields = ('product_code',)


@admin.register(CakeOrder, site=admin_site)
class CakeOrderAdmin(BaseRoleAdmin):
    list_display = ('id', 'user', 'cake', 'quantity',
                    'total_price', 'order_status', 'created_at')
    list_filter = ('order_status', 'created_at')
    search_fields = ('user__username', 'cake__name')
    raw_id_fields = ('user', 'cake')


@admin.register(CakeCustomization, site=admin_site)
class CakeCustomizationAdmin(BaseRoleAdmin):
    list_display = ('id', 'cake_order', 'message_on_cake')
    search_fields = ('cake_order__user__username',)


@admin.register(Package, site=admin_site)
class PackageAdmin(BaseRoleAdmin):
    list_display = ('product_code', 'name', 'package_type',
                    'base_price', 'status', 'created_at')
    list_filter = ('package_type', 'status')
    search_fields = ('product_code', 'name', 'description')
    readonly_fields = ('product_code',)


@admin.register(PackageOrder, site=admin_site)
class PackageOrderAdmin(BaseRoleAdmin):
    list_display = ('id', 'user', 'package', 'event_type',
                    'event_date', 'total_price', 'order_status', 'created_at')
    list_filter = ('order_status', 'event_type', 'event_date')
    search_fields = ('user__username', 'contact_name', 'venue')
    raw_id_fields = ('user', 'package')


@admin.register(Payment, site=admin_site)
class PaymentAdmin(BaseRoleAdmin):
    list_display = ('id', 'amount', 'payment_method',
                    'payment_status', 'created_at')
    list_filter = ('payment_method', 'payment_status')
    search_fields = ('reference_number',)
