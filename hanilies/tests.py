from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Cake, CakeOrder, Package, PackageOrder, UserProfile


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
