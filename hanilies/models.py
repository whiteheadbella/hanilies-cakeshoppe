from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner - Full Access'),
        ('admin', 'Admin - All Management'),
        ('manager', 'Manager - Orders & Customers'),
        ('baker', 'Baker - Cake Management'),
        ('packager', 'Packager - Package Management'),
        ('cashier', 'Cashier - Payments Only'),
        ('viewer', 'Viewer - Read Only'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default='viewer')
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('order_status', 'Order Status'),
        ('payment_status', 'Payment Status'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(
        max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=150)
    message = models.TextField()
    status_value = models.CharField(max_length=30, blank=True)
    cake_order = models.ForeignKey(
        'CakeOrder', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    package_order = models.ForeignKey(
        'PackageOrder', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    payment = models.ForeignKey(
        'Payment', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification #{self.id} - {self.title}"


class Cake(models.Model):
    CAKE_CATEGORIES = [
        ('birthday', 'Birthday'),
        ('wedding', 'Wedding'),
        ('christening', 'Christening'),
        ('anniversary', 'Anniversary'),
        ('custom', 'Custom'),
    ]

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CAKE_CATEGORIES)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    image = models.ImageField(
        upload_to='cakes/', blank=True, null=True)  # Already there
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def image_url(self):
        if self.image:
            return self.image.url
        return '/static/images/bg.png'


class CakeOrder(models.Model):
    ORDER_STATUS = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='cake_orders')
    cake = models.ForeignKey(
        Cake, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    quantity = models.IntegerField(default=1)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    order_status = models.CharField(
        max_length=20, choices=ORDER_STATUS, default='pending')

    # Cake customization
    theme = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    shape = models.CharField(max_length=50, blank=True, default='Round')
    flavor = models.CharField(max_length=50, blank=True, default='Chocolate')
    frosting = models.CharField(
        max_length=50, blank=True, default='Buttercream')
    filling = models.CharField(max_length=50, blank=True)
    color_palette = models.CharField(max_length=100, blank=True)
    message_on_cake = models.CharField(max_length=200, blank=True)
    special_instructions = models.TextField(blank=True)

    # Delivery info
    delivery_date = models.DateTimeField(null=True, blank=True)
    delivery_address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=100, default='')
    contact_phone = models.CharField(max_length=20, default='')
    contact_email = models.EmailField(default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} - {self.user.username}"

    @property
    def email(self):
        return self.contact_email

    @email.setter
    def email(self, value):
        self.contact_email = value

    @property
    def status(self):
        return self.order_status

    @status.setter
    def status(self, value):
        self.order_status = value


class CakeCustomization(models.Model):
    cake_order = models.OneToOneField(
        CakeOrder, on_delete=models.CASCADE, related_name='customization')
    message_on_cake = models.CharField(max_length=200, blank=True)
    color_palette = models.CharField(max_length=100, blank=True)
    design_reference = models.ImageField(
        upload_to='designs/', blank=True, null=True)
    additional_decorations = models.TextField(blank=True)

    def __str__(self):
        return f"Customization for Order #{self.cake_order.id}"


class Package(models.Model):
    PACKAGE_TYPES = [
        ('christening', 'Christening'),
        ('kids_birthday', "Kid's Birthday"),
        ('adults_party', "Adult's Party"),
        ('wedding', 'Wedding'),
        ('corporate', 'Corporate'),
    ]

    name = models.CharField(max_length=100)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPES)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    features = models.TextField(
        blank=True, help_text="List features, one per line")
    included_items = models.TextField(
        blank=True, help_text="List included items, one per line")
    image = models.ImageField(upload_to='packages/', blank=True, null=True)
    status = models.CharField(max_length=20, default='active', choices=[
                              ('active', 'Active'), ('inactive', 'Inactive')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class PackageOrder(models.Model):
    ORDER_STATUS = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    EVENT_TYPES = [
        ('christening', 'Christening'),
        ('kids_birthday', "Kid's Birthday"),
        ('adults_party', "Adult's Party"),
        ('wedding', 'Wedding'),
        ('corporate', 'Corporate'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='package_orders')
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    order_status = models.CharField(
        max_length=20, choices=ORDER_STATUS, default='pending')

    # Event details
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    event_date = models.DateField()
    event_time = models.TimeField(null=True, blank=True)
    venue = models.TextField()

    # Contact info
    contact_name = models.CharField(max_length=100)
    contact_phone = models.CharField(max_length=20)
    contact_email = models.EmailField()

    # Package customizations
    selected_addons = models.TextField(blank=True)
    cake_flavor = models.CharField(max_length=50, blank=True)
    cake_frosting = models.CharField(max_length=50, blank=True)
    cake_filling = models.CharField(max_length=50, blank=True)
    cake_message = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Package Order #{self.id} - {self.user.username}"

    @property
    def email(self):
        return self.contact_email

    @email.setter
    def email(self, value):
        self.contact_email = value

    @property
    def status(self):
        return self.order_status

    @status.setter
    def status(self, value):
        self.order_status = value


class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cod', 'Cash on Delivery'),
        ('gcash', 'GCash'),
        ('bank_transfer', 'Bank Transfer'),
    ]

    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('verifying', 'Verifying'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='pending')

    cake_order = models.ForeignKey(
        CakeOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='payments')
    package_order = models.ForeignKey(
        PackageOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='payments')

    reference_number = models.CharField(max_length=100, blank=True)
    proof_image = models.ImageField(upload_to='proofs/', blank=True, null=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment #{self.id} - {self.amount}"


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    actor_role = models.CharField(max_length=100, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor_label = self.actor.username if self.actor else 'Deleted user'
        return f"{self.action} by {actor_label}"
