from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


def _build_generated_product_code(prefix, record_id):
    return f"{prefix}-{record_id:04d}"


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('owner', 'Owner - Full Access'),
        ('admin', 'Admin - All Management'),
        ('manager', 'Manager - Full Management Access'),
        ('supervisor', 'Supervisor - Full Management Access'),
        ('baker', 'Baker - Cake Management'),
        ('packager', 'Packager - Package Management'),
        ('cashier', 'Cashier - Payments and Products'),
        ('customer', 'Customer - Customer Portal'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default='customer')
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
        ('refund_status', 'Refund Status'),
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


class HomeHeroImage(models.Model):
    title = models.CharField(max_length=120)
    image = models.ImageField(upload_to='hero/')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title


class HomeStripImage(models.Model):
    title = models.CharField(max_length=120)
    image = models.ImageField(upload_to='home-strip/')
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title


class AboutPageImage(models.Model):
    SLOT_STORY = 'story'
    SLOT_TEAM_TERESA = 'team_teresa'
    SLOT_TEAM_MARIA = 'team_maria'
    SLOT_TEAM_JOHN = 'team_john'
    SLOT_TEAM_ANNA = 'team_anna'

    SLOT_CHOICES = [
        (SLOT_STORY, 'Our Story Image'),
        (SLOT_TEAM_TERESA, 'Teresa Rabillas Team Image'),
        (SLOT_TEAM_MARIA, 'Maria Santos Team Image'),
        (SLOT_TEAM_JOHN, 'John Reyes Team Image'),
        (SLOT_TEAM_ANNA, 'Anna Lim Team Image'),
    ]

    IMAGE_POSITION_CENTER = 'center center'
    IMAGE_POSITION_TOP = 'center top'
    IMAGE_POSITION_BOTTOM = 'center bottom'
    IMAGE_POSITION_LEFT = 'left center'
    IMAGE_POSITION_RIGHT = 'right center'
    IMAGE_POSITION_TOP_LEFT = 'left top'
    IMAGE_POSITION_TOP_RIGHT = 'right top'
    IMAGE_POSITION_BOTTOM_LEFT = 'left bottom'
    IMAGE_POSITION_BOTTOM_RIGHT = 'right bottom'

    IMAGE_POSITION_CHOICES = [
        (IMAGE_POSITION_CENTER, 'Center'),
        (IMAGE_POSITION_TOP, 'Top'),
        (IMAGE_POSITION_BOTTOM, 'Bottom'),
        (IMAGE_POSITION_LEFT, 'Left'),
        (IMAGE_POSITION_RIGHT, 'Right'),
        (IMAGE_POSITION_TOP_LEFT, 'Top Left'),
        (IMAGE_POSITION_TOP_RIGHT, 'Top Right'),
        (IMAGE_POSITION_BOTTOM_LEFT, 'Bottom Left'),
        (IMAGE_POSITION_BOTTOM_RIGHT, 'Bottom Right'),
    ]

    slot = models.CharField(max_length=40, choices=SLOT_CHOICES, unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    display_position = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to='about/', blank=True, null=True)
    image_position = models.CharField(
        max_length=24,
        choices=IMAGE_POSITION_CHOICES,
        default=IMAGE_POSITION_CENTER,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slot']

    def __str__(self):
        return self.get_slot_display()

class Cake(models.Model):
    CAKE_CATEGORIES = [
        ('birthday', 'Birthday'),
        ('wedding', 'Wedding'),
        ('christening', 'Christening'),
        ('anniversary', 'Anniversary'),
        ('custom', 'Special Occasions'),
    ]

    name = models.CharField(max_length=100)
    product_code = models.CharField(
        max_length=16, unique=True, blank=True, null=True, editable=False)
    category = models.CharField(max_length=20, choices=CAKE_CATEGORIES)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    image = models.ImageField(
        upload_to='cakes/', blank=True, null=True)  # Already there
    customization_options = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.product_code:
            self.product_code = _build_generated_product_code('CK', self.pk)
            super().save(update_fields=['product_code'])

    def image_url(self):
        if self.image:
            return self.image.url
        return '/static/images/bg.png'


class CakeOrder(models.Model):
    PAYMENT_PLANS = [
        ('cod', '50% GCash Deposit + COD Balance'),
        ('gcash', 'Full GCash Payment'),
    ]

    ORDER_STATUS = [
        ('pending', 'Pending Admin Approval'),
        ('payment_retry', 'Awaiting Payment Resubmission'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('out_for_delivery', 'Out for Delivery'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='cake_orders')
    cake = models.ForeignKey(
        Cake, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    quantity = models.IntegerField(default=1)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_plan = models.CharField(
        max_length=20, choices=PAYMENT_PLANS, default='cod')
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    balance_due = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    order_status = models.CharField(
        max_length=20, choices=ORDER_STATUS, default='pending')

    # Cake customization
    theme = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    shape = models.CharField(max_length=50, blank=True, default='Round')
    flavor = models.CharField(max_length=50, blank=True, default='Chocolate')
    frosting = models.TextField(blank=True, default='')
    filling = models.TextField(blank=True)
    color_palette = models.CharField(max_length=100, blank=True)
    message_on_cake = models.CharField(max_length=200, blank=True)
    special_instructions = models.TextField(blank=True)

    # Delivery info
    delivery_date = models.DateTimeField(null=True, blank=True)
    delivery_address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=100, default='')
    contact_phone = models.CharField(max_length=20, default='')
    contact_email = models.EmailField(default='')
    order_number = models.CharField(
        max_length=32, unique=True, null=True, blank=True)

    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
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
        ('adults_party', 'Adult Birthday Party'),
        ('wedding', 'Wedding'),
    ]

    name = models.CharField(max_length=100)
    product_code = models.CharField(
        max_length=16, unique=True, blank=True, null=True, editable=False)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPES)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    features = models.TextField(
        blank=True, help_text="List features, one per line")
    included_items = models.TextField(
        blank=True, help_text="List included items, one per line")
    image = models.ImageField(upload_to='packages/', blank=True, null=True)
    customization_options = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default='active', choices=[
                              ('active', 'Active'), ('inactive', 'Inactive')])
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.product_code:
            self.product_code = _build_generated_product_code('PKG', self.pk)
            super().save(update_fields=['product_code'])

    @property
    def ordered_thumbnails(self):
        prefetched_objects = getattr(self, '_prefetched_objects_cache', {})
        thumbnails = prefetched_objects.get('thumbnails')
        if thumbnails is not None:
            return sorted(thumbnails, key=lambda thumbnail: thumbnail.sort_order)
        return list(self.thumbnails.order_by('sort_order'))

    @property
    def primary_image(self):
        if self.image:
            return self.image

        thumbnails = self.ordered_thumbnails
        if thumbnails:
            return thumbnails[0].image

        return None


class PackageThumbnail(models.Model):
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE, related_name='thumbnails')
    image = models.ImageField(upload_to='packages/thumbnails/')
    sort_order = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'sort_order'],
                name='unique_package_thumbnail_slot',
            ),
        ]

    def __str__(self):
        return f"{self.package.name} thumbnail #{self.sort_order}"


class PackageOrder(models.Model):
    PAYMENT_PLANS = [
        ('cod', '50% GCash Deposit + COD Balance'),
        ('gcash', 'Full GCash Payment'),
    ]

    ORDER_STATUS = [
        ('pending', 'Pending Admin Approval'),
        ('payment_retry', 'Awaiting Payment Resubmission'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('out_for_delivery', 'Out for Delivery'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    EVENT_TYPES = [
        ('christening', 'Christening'),
        ('kids_birthday', "Kid's Birthday"),
        ('adults_party', 'Adult Birthday Party'),
        ('wedding', 'Wedding'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='package_orders')
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_plan = models.CharField(
        max_length=20, choices=PAYMENT_PLANS, default='cod')
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    balance_due = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
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
    cake_frosting = models.TextField(blank=True)
    cake_filling = models.TextField(blank=True)
    cake_message = models.CharField(max_length=200, blank=True)
    design_reference = models.ImageField(
        upload_to='designs/', blank=True, null=True)
    order_number = models.CharField(
        max_length=32, unique=True, null=True, blank=True)

    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
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


class Testimonial(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_HIDDEN = 'hidden'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_HIDDEN, 'Hidden'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='testimonials')
    cake_order = models.ForeignKey(
        CakeOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='testimonials')
    package_order = models.ForeignKey(
        PackageOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='testimonials')
    customer_name = models.CharField(max_length=100)
    rating = models.PositiveSmallIntegerField(default=5)
    message = models.TextField()
    admin_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_testimonials',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(cake_order__isnull=False, package_order__isnull=True)
                    | Q(cake_order__isnull=True, package_order__isnull=False)
                ),
                name='testimonial_requires_exactly_one_order',
            ),
            models.UniqueConstraint(
                fields=['cake_order'],
                condition=Q(cake_order__isnull=False),
                name='unique_testimonial_per_cake_order',
            ),
            models.UniqueConstraint(
                fields=['package_order'],
                condition=Q(package_order__isnull=False),
                name='unique_testimonial_per_package_order',
            ),
        ]

    def __str__(self):
        return f"Testimonial #{self.id} - {self.customer_name}"

    @property
    def order(self):
        return self.cake_order if self.cake_order_id else self.package_order

    @property
    def order_type(self):
        return 'cake' if self.cake_order_id else 'package'

    @property
    def display_name(self):
        parts = [part for part in self.customer_name.split() if part]
        if len(parts) <= 1:
            return self.customer_name
        return f"{parts[0]} {parts[-1][0]}."

    @property
    def display_context(self):
        if self.cake_order_id:
            if self.cake_order and self.cake_order.theme:
                return self.cake_order.theme
            if self.cake_order and self.cake_order.cake:
                return self.cake_order.cake.get_category_display()
            return 'Cake Order'
        if self.package_order and self.package_order.package:
            return self.package_order.package.name
        if self.package_order:
            return self.package_order.get_event_type_display()
        return 'Customer Order'

    @property
    def star_range(self):
        return range(max(1, min(int(self.rating or 0), 5)))


class ContactInquiry(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contact_inquiries',
    )
    name = models.CharField(max_length=120)
    contact_detail = models.CharField(max_length=150)
    message = models.TextField()
    admin_reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replied_contact_inquiries',
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Inquiry #{self.id} - {self.name}"

    @property
    def status_label(self):
        if self.is_archived:
            return 'Archived'
        if self.admin_reply and self.replied_at:
            return 'Replied'
        if self.is_read:
            return 'Read'
        return 'New'

    @property
    def status_key(self):
        return self.status_label.lower()

    @property
    def reply_email(self):
        contact_value = (self.contact_detail or '').strip()
        if not contact_value:
            return ''
        try:
            validate_email(contact_value)
        except ValidationError:
            return ''
        return contact_value

    @property
    def has_email_contact(self):
        return bool(self.reply_email)




class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cod', 'Cash on Delivery'),
        ('gcash', 'GCash'),
        ('bank_transfer', 'Bank Transfer'),
    ]

    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('verifying', 'Under Verification'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_PURPOSES = [
        ('deposit', 'Deposit'),
        ('balance', 'Remaining Balance'),
        ('full', 'Full Payment'),
        ('refund', 'Refund'),
    ]

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_purpose = models.CharField(
        max_length=20, choices=PAYMENT_PURPOSES, default='full')
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='pending')

    cake_order = models.ForeignKey(
        CakeOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='payments')
    package_order = models.ForeignKey(
        PackageOrder, on_delete=models.CASCADE, null=True, blank=True, related_name='payments')

    reference_number = models.CharField(max_length=100, blank=True)
    proof_image = models.ImageField(upload_to='proofs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment #{self.id} - {self.amount}"


class RefundRequest(models.Model):
    REFUND_STATUS = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
    ]

    cake_order = models.OneToOneField(
        CakeOrder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='refund_request',
    )
    package_order = models.OneToOneField(
        PackageOrder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='refund_request',
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_requests',
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='requested_refunds',
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_refunds',
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_refunds',
    )
    reason = models.TextField()
    internal_note = models.TextField(blank=True)
    penalty_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    refundable_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=REFUND_STATUS, default='requested')
    refund_reference_number = models.CharField(max_length=100, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        if self.cake_order_id:
            return f"Refund for Cake Order #{self.cake_order_id}"
        return f"Refund for Package Order #{self.package_order_id}"


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    actor_role = models.CharField(max_length=100, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField()
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor_label = self.actor.username if self.actor else 'Deleted user'
        return f"{self.action} by {actor_label}"



