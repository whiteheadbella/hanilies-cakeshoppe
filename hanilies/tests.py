from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Cake, CakeCustomization, CakeOrder, Package, PackageOrder, Payment, UserProfile
from .views import CAKE_DECORATION_OPTIONS, _get_selected_option_labels, _parse_delivery_datetime


class ViewHelperUnitTests(TestCase):
    def test_parse_delivery_datetime_returns_aware_morning_timestamp(self):
        delivery_datetime = _parse_delivery_datetime('2026-06-15')

        self.assertIsNotNone(delivery_datetime)
        self.assertTrue(timezone.is_aware(delivery_datetime))
        self.assertEqual(delivery_datetime.date().isoformat(), '2026-06-15')
        self.assertEqual(
            (delivery_datetime.hour, delivery_datetime.minute), (10, 0))

    def test_parse_delivery_datetime_returns_none_for_invalid_date(self):
        self.assertIsNone(_parse_delivery_datetime('not-a-date'))

    def test_selected_option_labels_ignores_unknown_keys(self):
        labels, total = _get_selected_option_labels(
            ['fresh_flowers', 'invalid-option', 'sprinkles'],
            CAKE_DECORATION_OPTIONS,
        )

        self.assertEqual(labels, ['Fresh Flowers', 'Edible Sprinkles'])
        self.assertEqual(total, Decimal('400.00'))


class CakeModelUnitTests(TestCase):
    def test_image_url_uses_static_fallback_when_no_upload_exists(self):
        cake = Cake.objects.create(
            name='Fallback Cake',
            category='birthday',
            description='No uploaded image.',
            price=Decimal('850.00'),
            stock=3,
            is_active=True,
        )

        self.assertEqual(cake.image_url(), '/static/images/bg.png')


class CakeOrderViewUnitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='cake-tester',
            password='TestPass123!',
            email='cake@example.com',
            first_name='Cake',
            last_name='Tester',
        )
        UserProfile.objects.create(
            user=self.user,
            role='viewer',
            phone='09123456789',
            address='Oroquieta City',
        )
        self.cake = Cake.objects.create(
            name='Chocolate Dream',
            category='birthday',
            description='Rich chocolate celebration cake.',
            price=Decimal('1200.00'),
            stock=5,
            is_active=True,
        )
        self.client.login(username='cake-tester', password='TestPass123!')

    def test_cake_customize_post_creates_order_customization_and_payment(self):
        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '2',
            'decorations': ['fresh_flowers'],
            'payment_method': 'cod',
            'theme': 'Birthday',
            'size': '8 inches',
            'shape': 'Round',
            'flavor': 'Chocolate',
            'frosting': 'Buttercream',
            'filling': 'Chocolate Ganache',
            'color_palette': 'Pink and Gold',
            'message_on_cake': 'Happy Birthday Ella',
            'special_instructions': 'Add gold accents.',
            'delivery_date': '2026-06-20',
            'delivery_address': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CakeOrder.objects.count(), 1)
        self.assertEqual(CakeCustomization.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

        cake_order = CakeOrder.objects.get()
        payment = Payment.objects.get()
        customization = CakeCustomization.objects.get()

        self.assertEqual(cake_order.total_price, Decimal('2700.00'))
        self.assertEqual(
            cake_order.delivery_date.date().isoformat(), '2026-06-20')
        self.assertEqual(customization.additional_decorations, 'Fresh Flowers')
        self.assertEqual(payment.payment_method, 'cod')
        self.assertEqual(payment.payment_status, 'pending')
        self.assertEqual(payment.amount, Decimal('2700.00'))
        self.assertEqual(payment.cake_order_id, cake_order.id)

    def test_cake_customize_rejects_gcash_without_reference_and_proof(self):
        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'gcash',
            'delivery_date': '2026-06-20',
            'delivery_address': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(CakeCustomization.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)


class PackageFlowUnitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='package-tester',
            password='TestPass123!',
            email='package@example.com',
            first_name='Package',
            last_name='Tester',
        )
        UserProfile.objects.create(
            user=self.user,
            role='viewer',
            phone='09999999999',
            address='Clarin, Misamis Occidental',
        )
        self.package = Package.objects.create(
            name='Birthday Blast',
            package_type='kids_birthday',
            description='Party package with themed cake and balloons.',
            base_price=Decimal('6500.00'),
            status='active',
        )
        self.client.login(username='package-tester', password='TestPass123!')

    def test_package_order_post_stores_selected_addons_in_session_draft(self):
        response = self.client.post(reverse('package_order'), {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addons': ['brownies', 'cookies'],
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse(
            'package_cake_customize'))

        draft = self.client.session['package_order_draft']
        self.assertEqual(draft['package_id'], str(self.package.id))
        self.assertEqual(draft['selected_addon_labels'], [
                         'Chocofudge Brownies', 'Chocochip Cookies'])
        self.assertEqual(draft['addons_total'], '550.00')
        self.assertEqual(draft['base_total'], '7050.00')

    def test_order_package_route_alias_uses_same_package_flow(self):
        response = self.client.post(reverse('order_package'), {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addons': ['brownies'],
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse(
            'package_cake_customize'))

        draft = self.client.session['package_order_draft']
        self.assertEqual(draft['package_id'], str(self.package.id))
        self.assertEqual(draft['selected_addon_labels'],
                         ['Chocofudge Brownies'])

    def test_package_payment_post_creates_order_and_clears_session_draft(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': ['Chocofudge Brownies'],
            'base_total': '6800.00',
            'cake_flavor': 'Vanilla',
            'cake_frosting': 'Buttercream',
            'cake_filling': 'Strawberry Jam',
            'cake_message': 'Happy Birthday Mia',
            'cake_custom_total': '500.00',
        }
        session.save()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': '2026-07-01',
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PackageOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)

        package_order = PackageOrder.objects.get()
        payment = Payment.objects.get()

        self.assertEqual(package_order.total_price, Decimal('7300.00'))
        self.assertEqual(package_order.selected_addons, 'Chocofudge Brownies')
        self.assertEqual(package_order.cake_message, 'Happy Birthday Mia')
        self.assertEqual(payment.payment_method, 'cod')
        self.assertEqual(payment.payment_status, 'pending')
        self.assertEqual(payment.amount, Decimal('7300.00'))
        self.assertEqual(payment.package_order_id, package_order.id)
        self.assertNotIn('package_order_draft', self.client.session)

    def test_package_payment_rejects_gcash_without_required_fields(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': '2026-07-01',
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'gcash',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn('package_order_draft', self.client.session)


class OrderingIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='integration-user',
            password='TestPass123!',
            email='integration@example.com',
            first_name='Integration',
            last_name='User',
        )
        UserProfile.objects.create(
            user=self.user,
            role='viewer',
            phone='09170000000',
            address='Oroquieta City',
        )
        self.cake = Cake.objects.create(
            name='Mocha Celebration',
            category='birthday',
            description='Mocha cake for celebrations.',
            price=Decimal('980.00'),
            stock=8,
            is_active=True,
        )
        self.package = Package.objects.create(
            name='Celebration Package',
            package_type='kids_birthday',
            description='Package with cake and add-ons.',
            base_price=Decimal('7000.00'),
            status='active',
        )
        self.client.login(username='integration-user', password='TestPass123!')

    def test_cake_order_redirects_to_tracking_with_created_order(self):
        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'theme': 'Birthday',
            'size': '6 inches',
            'shape': 'Round',
            'flavor': 'Mocha',
            'frosting': 'Buttercream',
            'delivery_date': '2026-08-02',
            'delivery_address': 'Oroquieta City',
            'contact_name': 'Integration User',
            'contact_phone': '09170000000',
            'contact_email': 'integration@example.com',
        })

        self.assertEqual(response.status_code, 302)
        created_order = CakeOrder.objects.get(user=self.user)
        self.assertEqual(
            response.headers['Location'],
            f"{reverse('order_tracking')}?type=cake&id={created_order.id}",
        )

        tracking_response = self.client.get(response.headers['Location'])

        self.assertEqual(tracking_response.status_code, 200)
        self.assertEqual(
            tracking_response.context['selected_order_type'], 'cake')
        self.assertEqual(
            tracking_response.context['selected_order'].id, created_order.id)
        self.assertEqual(
            tracking_response.context['selected_payment'].cake_order_id, created_order.id)

    def test_package_booking_flow_redirects_to_tracking_with_created_order(self):
        first_step = self.client.post(reverse('package_order'), {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addons': ['brownies', 'cupcakes'],
        })

        self.assertEqual(first_step.status_code, 302)
        self.assertEqual(first_step.headers['Location'], reverse(
            'package_cake_customize'))

        second_step = self.client.post(reverse('package_cake_customize'), {
            'cake_size': 'upgrade_10',
            'cake_decorations': ['fresh_flowers'],
            'theme': 'Galaxy',
            'flavor': 'Chocolate',
            'frosting': 'Buttercream',
            'filling': 'Chocolate Ganache',
            'shape': 'Round',
            'message_on_cake': 'Happy Birthday Nico',
            'color_palette': 'Blue and Silver',
            'cake_instructions': 'Use star accents.',
        })

        self.assertEqual(second_step.status_code, 302)
        self.assertEqual(
            second_step.headers['Location'], reverse('package_payment'))

        final_step = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': '2026-08-10',
            'event_time': '15:00',
            'venue': 'Oroquieta Gym',
            'contact_name': 'Integration User',
            'contact_phone': '09170000000',
            'contact_email': 'integration@example.com',
            'payment_method': 'cod',
        })

        self.assertEqual(final_step.status_code, 302)
        created_order = PackageOrder.objects.get(user=self.user)
        self.assertEqual(
            final_step.headers['Location'],
            f"{reverse('order_tracking')}?type=package&id={created_order.id}",
        )
        self.assertEqual(created_order.total_price, Decimal('8450.00'))
        self.assertEqual(created_order.selected_addons,
                         'Chocofudge Brownies\nThemed Cupcakes')
        self.assertEqual(created_order.cake_message, 'Happy Birthday Nico')

        tracking_response = self.client.get(final_step.headers['Location'])

        self.assertEqual(tracking_response.status_code, 200)
        self.assertEqual(
            tracking_response.context['selected_order_type'], 'package')
        self.assertEqual(
            tracking_response.context['selected_order'].id, created_order.id)
        self.assertEqual(
            tracking_response.context['selected_payment'].package_order_id,
            created_order.id,
        )
        self.assertNotIn('package_order_draft', self.client.session)


class SecurityValidationTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username='viewer-user',
            password='TestPass123!',
            email='viewer@example.com',
        )
        UserProfile.objects.create(user=self.viewer, role='viewer')

        self.admin_user = User.objects.create_user(
            username='admin-user',
            password='TestPass123!',
            email='admin@example.com',
        )
        UserProfile.objects.create(user=self.admin_user, role='admin')

    def test_guest_is_redirected_to_login_for_protected_tracking_route(self):
        response = self.client.get(reverse('order_tracking'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.headers['Location'])

    def test_viewer_is_redirected_home_from_admin_dashboard(self):
        self.client.login(username='viewer-user', password='TestPass123!')

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('home'))

    def test_admin_role_can_access_admin_dashboard(self):
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['role'], 'admin')

    def test_viewer_is_redirected_from_admin_payments(self):
        self.client.login(username='viewer-user', password='TestPass123!')

        response = self.client.get(reverse('admin_payments'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_dashboard'))

    def test_admin_can_access_admin_users_and_payments(self):
        Payment.objects.create(
            amount=Decimal('500.00'),
            payment_method='cod',
            payment_status='pending',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        payments_response = self.client.get(reverse('admin_payments'))
        users_response = self.client.get(reverse('admin_users'))

        self.assertEqual(payments_response.status_code, 200)
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(payments_response.context['payments'].count(), 1)
        self.assertGreaterEqual(users_response.context['users'].count(), 2)


class HomeRecommendationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='recommend-user',
            password='TestPass123!',
            first_name='Recommend',
            last_name='User',
            email='recommend@example.com',
        )
        UserProfile.objects.create(user=self.user, role='viewer')

        self.birthday_cake = Cake.objects.create(
            name='Birthday Chocolate Cake',
            category='birthday',
            description='Chocolate birthday cake for parties.',
            price=Decimal('950.00'),
            stock=5,
            is_active=True,
        )
        self.wedding_cake = Cake.objects.create(
            name='Elegant Wedding Cake',
            category='wedding',
            description='Tiered wedding cake with floral styling.',
            price=Decimal('4200.00'),
            stock=2,
            is_active=True,
        )

        self.christening_package = Package.objects.create(
            name='Christening Package A',
            package_type='christening',
            description='Christening setup with cake and balloons.',
            base_price=Decimal('7000.00'),
            status='active',
        )
        self.kids_package = Package.objects.create(
            name='Kids Birthday Package',
            package_type='kids_birthday',
            description='Birthday package with themed treats.',
            base_price=Decimal('6500.00'),
            status='active',
        )

        CakeOrder.objects.create(
            user=self.user,
            cake=self.birthday_cake,
            quantity=1,
            total_price=Decimal('950.00'),
            theme='Birthday',
            flavor='Chocolate',
            frosting='Buttercream',
            delivery_address='Oroquieta City',
            contact_name='Recommend User',
            contact_phone='09123456789',
            contact_email='recommend@example.com',
        )
        PackageOrder.objects.create(
            user=self.user,
            package=self.christening_package,
            total_price=Decimal('7000.00'),
            event_type='christening',
            event_date=date(2026, 5, 30),
            event_time=time(13, 0),
            venue='Oroquieta City',
            contact_name='Recommend User',
            contact_phone='09123456789',
            contact_email='recommend@example.com',
            cake_flavor='Chocolate',
            cake_frosting='Buttercream',
        )

    def test_homepage_personalizes_recommendations_for_signed_in_user(self):
        self.client.login(username='recommend-user', password='TestPass123!')

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['recommendation_headline'], 'Recommended For Your Next Celebration')
        self.assertEqual(
            response.context['recommended_cakes'][0]['id'], self.birthday_cake.id)
        self.assertEqual(
            response.context['recommended_packages'][0]['id'], self.christening_package.id)

    def test_homepage_falls_back_to_best_sellers_for_guest_users(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['recommendation_headline'], 'Best-Selling Picks')
        self.assertGreaterEqual(len(response.context['recommended_cakes']), 1)
        self.assertGreaterEqual(
            len(response.context['recommended_packages']), 1)
