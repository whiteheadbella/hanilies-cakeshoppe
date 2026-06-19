from io import BytesIO
from datetime import date, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch
from PIL import Image, ImageDraw
from django.contrib.messages import get_messages
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import (
    CAKE_MAX_BOOKING_MESSAGE,
    INVALID_BOOKING_WINDOW_MESSAGE,
    MINIMUM_BOOKING_MESSAGE,
    PACKAGE_MAX_BOOKING_MESSAGE,
    CakeBookingDateForm,
    PackageBookingDateForm,
    add_calendar_months,
    build_cake_booking_window,
    build_package_booking_window,
)
from .management.commands.demo_bot import Command as DemoBotCommand
from .models import ActivityLog, Cake, CakeCustomization, CakeOrder, Notification, Package, PackageOrder, PackageThumbnail, Payment, RefundRequest, UserProfile
from .payment_qr import build_gcash_checkout_details
from .views import CAKE_DECORATION_OPTIONS, _get_selected_option_labels, _parse_delivery_datetime


TEST_MEDIA_ROOT = tempfile.mkdtemp()


def build_test_image_upload(name='proof.jpg', image_format='JPEG', content_type='image/jpeg', reference_number='HANI-TEST-001', amount='1350.00', include_receipt_text=True):
    image_bytes = BytesIO()
    image = Image.new('RGB', (1200, 700), color='white')
    if include_receipt_text:
        draw = ImageDraw.Draw(image)
        receipt_lines = [
            'GCash',
            f'Reference No: {reference_number}',
            f'Amount: P{amount}',
            'Transaction Successful',
            'Paid to Hanilies Cakeshoppe',
        ]
        y_position = 40
        for line in receipt_lines:
            draw.text((40, y_position), line, fill='black')
            y_position += 28
    image.save(
        image_bytes,
        format=image_format,
    )
    return SimpleUploadedFile(name, image_bytes.getvalue(), content_type=content_type)


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


class BookingDateFormTests(TestCase):
    def test_cake_booking_date_form_rejects_dates_before_minimum_window(self):
        form = CakeBookingDateForm({
            'delivery_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
        })

        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [MINIMUM_BOOKING_MESSAGE])

    def test_cake_booking_date_form_rejects_dates_beyond_30_days(self):
        form = CakeBookingDateForm({
            'delivery_date': (timezone.now().date() + timedelta(days=31)).isoformat(),
        })

        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [CAKE_MAX_BOOKING_MESSAGE])

    def test_package_booking_date_form_rejects_dates_beyond_30_days(self):
        form = PackageBookingDateForm({
            'event_date': (timezone.now().date() + timedelta(days=31)).isoformat(),
        })

        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [
                         PACKAGE_MAX_BOOKING_MESSAGE])

    def test_booking_date_forms_use_window_limits_as_widget_attrs(self):
        cake_form = CakeBookingDateForm()
        package_form = PackageBookingDateForm()
        cake_window = build_cake_booking_window()
        package_window = build_package_booking_window()

        self.assertEqual(
            cake_form.fields['delivery_date'].widget.attrs['min'], cake_window['min'])
        self.assertEqual(
            cake_form.fields['delivery_date'].widget.attrs['max'], cake_window['max'])
        self.assertEqual(
            package_form.fields['event_date'].widget.attrs['min'], package_window['min'])
        self.assertEqual(
            package_form.fields['event_date'].widget.attrs['max'], package_window['max'])

    def test_booking_date_forms_use_generic_invalid_message_for_bad_input(self):
        form = CakeBookingDateForm({'delivery_date': 'not-a-date'})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['delivery_date'], [
                         INVALID_BOOKING_WINDOW_MESSAGE])


class PaymentQrUnitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='qr-tester',
            password='TestPass123!',
            email='qr@example.com',
        )

    def test_build_gcash_checkout_details_returns_png_data_uri(self):
        preview = build_gcash_checkout_details(
            '2450.50', 'Chocolate Dream cake order', reference_seed='qr-tester')

        self.assertEqual(preview['amount_label'], 'P2450.50')
        self.assertTrue(preview['qr_code_data_uri'].startswith(
            'data:image/png;base64,'))
        self.assertRegex(preview['payment_reference'], r'^HANI-[A-F0-9]{10}$')
        self.assertTrue(
            preview['instruction_payload'].startswith('000201010212'))
        self.assertNotIn('\n', preview['instruction_payload'])

    def test_payment_qr_preview_returns_json_for_logged_in_user(self):
        self.client.login(username='qr-tester', password='TestPass123!')

        response = self.client.get(reverse('payment_qr_preview'), {
            'amount': '1500.00',
            'order_label': 'Chocolate Dream cake order',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['amount_label'], 'P1500.00')
        self.assertEqual(payload['merchant_name'], 'Hanilies Cakeshoppe')
        self.assertRegex(payload['payment_reference'], r'^HANI-[A-F0-9]{10}$')
        self.assertTrue(
            payload['instruction_payload'].startswith('000201010212'))
        self.assertNotIn('scan_target_url', payload)
        self.assertTrue(payload['qr_code_data_uri'].startswith(
            'data:image/png;base64,'))

    def test_payment_qr_preview_keeps_reference_stable_for_same_session(self):
        self.client.login(username='qr-tester', password='TestPass123!')

        first_response = self.client.get(reverse('payment_qr_preview'), {
            'amount': '1500.00',
            'order_label': 'Chocolate Dream cake order',
        })
        second_response = self.client.get(reverse('payment_qr_preview'), {
            'amount': '1500.00',
            'order_label': 'Chocolate Dream cake order',
        })

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            first_response.json()['payment_reference'],
            second_response.json()['payment_reference'],
        )

    def test_payment_qr_preview_rejects_non_positive_amount(self):
        self.client.login(username='qr-tester', password='TestPass123!')

        response = self.client.get(reverse('payment_qr_preview'), {
            'amount': '0.00',
        })

        self.assertEqual(response.status_code, 400)


class DemoBotCommandUnitTests(TestCase):
    def test_gcash_cake_scenario_uses_manual_flow_steps(self):
        command = DemoBotCommand()
        command.payment_mode = 'gcash'

        self.assertEqual(
            command._scenario_steps('cake'),
            ['login', 'cakes', 'cake_order', 'cake_tracking'],
        )

    def test_gcash_package_scenario_uses_manual_flow_steps(self):
        command = DemoBotCommand()
        command.payment_mode = 'gcash'

        self.assertEqual(
            command._scenario_steps('package'),
            ['login', 'packages', 'package_order', 'package_tracking'],
        )

    def test_cod_full_scenario_matches_default_script(self):
        command = DemoBotCommand()
        command.payment_mode = 'cod'

        self.assertEqual(
            command._scenario_steps('full'),
            ['home', 'login', 'ai_recommendations', 'cakes', 'cake_order', 'cake_tracking', 'packages',
                'package_order', 'package_tracking', 'profile', 'ai_recommendations', 'order_tracking'],
        )


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
            role='customer',
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

    def _cake_delivery_date(self, days_ahead=3):
        return (timezone.localdate() + timedelta(days=days_ahead)).isoformat()

    def _cake_checkout_reference(self):
        response = self.client.get(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
        })
        self.assertEqual(response.status_code, 200)
        return response.context['checkout_payment_reference']

    def test_cake_customize_post_creates_order_customization_and_payment(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '2',
            'decorations': ['fresh_flowers'],
            'payment_method': 'cod',
            'payment_amount': '1350.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('cake-proof.jpg', reference_number=generated_reference, amount='1350.00'),
            'theme': 'Birthday',
            'size': '8 inches',
            'shape': 'Round',
            'flavor': 'Chocolate',
            'frosting': 'Buttercream',
            'filling': 'Chocolate Ganache',
            'color_palette': 'Pink and Gold',
            'message_on_cake': 'Happy Birthday Ella',
            'special_instructions': 'Add gold accents.',
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'delivery_landmark': 'Near Plaza Burgos',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CakeOrder.objects.count(), 1)
        self.assertEqual(CakeCustomization.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)

        cake_order = CakeOrder.objects.get()
        deposit_payment = Payment.objects.get(payment_purpose='deposit')
        balance_payment = Payment.objects.get(payment_purpose='balance')
        customization = CakeCustomization.objects.get()

        self.assertEqual(cake_order.total_price, Decimal('2700.00'))
        self.assertEqual(cake_order.payment_plan, 'cod')
        self.assertTrue(cake_order.order_number.startswith('CKO-'))
        self.assertEqual(cake_order.deposit_amount, Decimal('1350.00'))
        self.assertEqual(cake_order.balance_due, Decimal('1350.00'))
        self.assertEqual(
            cake_order.delivery_address,
            '123 Rizal Street, Brgy. Poblacion 1, Oroquieta City, Misamis Occidental (Landmark: Near Plaza Burgos)',
        )
        self.assertEqual(
            cake_order.delivery_date.date().isoformat(), self._cake_delivery_date())
        self.assertEqual(customization.additional_decorations, 'Fresh Flowers')
        self.assertEqual(deposit_payment.payment_method, 'gcash')
        self.assertEqual(deposit_payment.payment_status, 'verifying')
        self.assertEqual(deposit_payment.amount, Decimal('1350.00'))
        self.assertEqual(deposit_payment.reference_number, generated_reference)
        self.assertEqual(deposit_payment.cake_order_id, cake_order.id)
        self.assertEqual(balance_payment.payment_method, 'cod')
        self.assertEqual(balance_payment.payment_status, 'pending')
        self.assertEqual(balance_payment.amount, Decimal('1350.00'))
        self.assertEqual(balance_payment.cake_order_id, cake_order.id)

    def test_cake_customize_get_renders_gcash_qr_preview(self):
        response = self.client.get(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'multipart/form-data')
        self.assertContains(response, 'Account Name:')
        self.assertContains(response, 'GCash Number:')
        self.assertContains(response, reverse('payment_qr_preview'))
        self.assertContains(response, '50% GCash Deposit + COD Balance')
        self.assertContains(response, 'Order Number')
        self.assertContains(response, 'Amount Due')
        self.assertContains(response, 'Payment Reference Number')
        self.assertContains(response, 'Review Cake Order')
        self.assertContains(response, 'Confirm Cake Order')

    def test_cake_customize_get_renders_special_occasions_theme_option(self):
        response = self.client.get(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Special Occasions')
        self.assertNotContains(response, 'Graduation')

    def test_cake_customize_rejects_gcash_without_reference_and_proof(self):
        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'gcash',
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(CakeCustomization.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertContains(response, 'value="gcash" checked')
        self.assertContains(response, 'Full GCash Payment')

    def test_cake_customize_rejects_duplicate_reference_number(self):
        generated_reference = self._cake_checkout_reference()
        Payment.objects.create(
            amount=Decimal('100.00'),
            payment_method='gcash',
            payment_purpose='deposit',
            payment_status='verifying',
            reference_number=generated_reference,
        )

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference.lower(),
            'proof_image': build_test_image_upload('duplicate-proof.jpg', reference_number=generated_reference, amount='600.00'),
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Reference number does not match this order.')
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(CakeCustomization.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 1)

    def test_cake_customize_rejects_invalid_payment_proof_image(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': SimpleUploadedFile('not-an-image.jpg', b'not-an-image', content_type='image/jpeg'),
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Only JPG, JPEG, and PNG files are allowed.')
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(CakeCustomization.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cake_customize_rejects_unserviceable_delivery_city(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('service-area-proof.jpg', reference_number=generated_reference, amount='600.00'),
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Cebu City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'We currently deliver only within the listed service areas.')
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cake_customize_rejects_delivery_date_outside_order_period(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('window-proof.jpg', reference_number=generated_reference, amount='600.00'),
            'delivery_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, MINIMUM_BOOKING_MESSAGE)
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cake_customize_rejects_delivery_date_beyond_30_days(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('late-window-proof.jpg', reference_number=generated_reference, amount='600.00'),
            'delivery_date': (timezone.now().date() + timedelta(days=31)).isoformat(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CAKE_MAX_BOOKING_MESSAGE)
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cake_customize_get_uses_30_day_booking_window(self):
        response = self.client.get(reverse('cake_customize'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['cake_order_window']['min'],
            (timezone.now().date() + timedelta(days=3)).isoformat(),
        )
        self.assertEqual(
            response.context['cake_order_window']['max'],
            (timezone.now().date() + timedelta(days=30)).isoformat(),
        )
        self.assertEqual(CakeOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_cake_customize_accepts_simulated_payment_proof_image(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload(
                'random-proof.jpg',
                reference_number=generated_reference,
                amount='600.00',
                include_receipt_text=False,
            ),
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CakeOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)

    def test_cake_customize_allows_manual_review_with_valid_image_proof(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '600.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload(
                'manual-review-proof.jpg',
                reference_number=generated_reference,
                amount='600.00',
                include_receipt_text=False,
            ),
            'delivery_date': self._cake_delivery_date(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
            'contact_name': 'Cake Tester',
            'contact_phone': '09123456789',
            'contact_email': 'cake@example.com',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CakeOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)

    def test_cakes_page_shows_special_occasions_label_for_custom_category(self):
        self.cake.image = 'cakes/catalog-main.jpg'
        self.cake.save(update_fields=['image'])
        special_cake = Cake.objects.create(
            name='Elegant Celebration Cake',
            category='custom',
            description='Made for milestone celebrations.',
            price=Decimal('1850.00'),
            stock=2,
            image='cakes/special-occasion.jpg',
            is_active=True,
        )

        response = self.client.get(reverse('cakes'), {
            'category': 'custom',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, special_cake.name)
        self.assertContains(response, 'Special Occasions')
        self.assertNotContains(response, '>Custom<', html=False)
        self.assertContains(response, 'data-zoom-gallery="cakes-catalog"')


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
            role='customer',
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

    def _package_event_date(self, days_ahead=3):
        return (timezone.localdate() + timedelta(days=days_ahead)).isoformat()

    def _package_checkout_reference(self):
        response = self.client.get(reverse('package_payment'))
        self.assertEqual(response.status_code, 200)
        return response.context['checkout_payment_reference']

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

    def test_package_order_rejects_removed_corporate_event_type(self):
        response = self.client.post(reverse('package_order'), {
            'package_id': str(self.package.id),
            'event_type': 'corporate',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Selected event type is no longer available for package bookings.',
        )
        self.assertNotIn('package_order_draft', self.client.session)

    def test_order_package_route_blocks_corporate_package_ids(self):
        corporate_package = Package.objects.create(
            name='Corporate Launch Bundle',
            package_type='corporate',
            description='Legacy corporate package.',
            base_price=Decimal('9500.00'),
            status='active',
        )

        response = self.client.get(reverse('order_package'), {
            'package_id': str(corporate_package.id),
        })

        self.assertEqual(response.status_code, 404)

    def test_packages_page_excludes_corporate_packages_from_listing(self):
        Package.objects.create(
            name='Corporate Legacy Bundle',
            package_type='corporate',
            description='Should not appear in the public package catalog.',
            base_price=Decimal('8200.00'),
            status='active',
        )

        response = self.client.get(reverse('packages'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Corporate Legacy Bundle')
        self.assertContains(response, self.package.name)

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
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': self._package_event_date(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3650.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('package-proof.jpg', reference_number=generated_reference, amount='3650.00'),
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PackageOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)

        package_order = PackageOrder.objects.get()
        deposit_payment = Payment.objects.get(payment_purpose='deposit')
        balance_payment = Payment.objects.get(payment_purpose='balance')

        self.assertEqual(package_order.total_price, Decimal('7300.00'))
        self.assertEqual(package_order.payment_plan, 'cod')
        self.assertTrue(package_order.order_number.startswith('PKO-'))
        self.assertEqual(package_order.deposit_amount, Decimal('3650.00'))
        self.assertEqual(package_order.balance_due, Decimal('3650.00'))
        self.assertEqual(package_order.selected_addons, 'Chocofudge Brownies')
        self.assertEqual(package_order.cake_message, 'Happy Birthday Mia')
        self.assertEqual(deposit_payment.payment_method, 'gcash')
        self.assertEqual(deposit_payment.payment_status, 'verifying')
        self.assertEqual(deposit_payment.amount, Decimal('3650.00'))
        self.assertEqual(deposit_payment.reference_number, generated_reference)
        self.assertEqual(deposit_payment.package_order_id, package_order.id)
        self.assertEqual(balance_payment.payment_method, 'cod')
        self.assertEqual(balance_payment.payment_status, 'pending')
        self.assertEqual(balance_payment.amount, Decimal('3650.00'))
        self.assertEqual(balance_payment.package_order_id, package_order.id)
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
            'event_date': self._package_event_date(),
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
        self.assertContains(response, 'value="gcash" checked')
        self.assertContains(response, 'Full GCash Payment')

    def test_package_payment_rejects_duplicate_reference_number(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()
        Payment.objects.create(
            amount=Decimal('100.00'),
            payment_method='gcash',
            payment_purpose='deposit',
            payment_status='verifying',
            reference_number=generated_reference,
        )

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': self._package_event_date(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference.lower(),
            'proof_image': build_test_image_upload('duplicate-package-proof.jpg', reference_number=generated_reference, amount='3250.00'),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Reference number does not match this order.')
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertIn('package_order_draft', self.client.session)

    def test_package_payment_rejects_invalid_payment_proof_image(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': self._package_event_date(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference,
            'proof_image': SimpleUploadedFile('not-an-image.jpg', b'not-an-image', content_type='image/jpeg'),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'Only JPG, JPEG, and PNG files are allowed.')
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn('package_order_draft', self.client.session)

    def test_package_payment_rejects_event_date_outside_order_period(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': (timezone.localdate() + timedelta(days=2)).isoformat(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('package-window-proof.jpg', reference_number=generated_reference, amount='3250.00'),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, MINIMUM_BOOKING_MESSAGE)
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn('package_order_draft', self.client.session)

    def test_package_payment_rejects_event_date_beyond_30_days(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': (timezone.now().date() + timedelta(days=31)).isoformat(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('package-max-window-proof.jpg', reference_number=generated_reference, amount='3250.00'),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, PACKAGE_MAX_BOOKING_MESSAGE)
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn('package_order_draft', self.client.session)

    def test_package_payment_get_uses_30_day_booking_window(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()

        response = self.client.get(reverse('package_payment'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['package_order_window']['min'],
            (timezone.now().date() + timedelta(days=3)).isoformat(),
        )
        self.assertEqual(
            response.context['package_order_window']['max'],
            (timezone.now().date() + timedelta(days=30)).isoformat(),
        )
        self.assertEqual(PackageOrder.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertIn('package_order_draft', self.client.session)

    def test_package_payment_accepts_simulated_payment_proof_image(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': self._package_event_date(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload(
                'random-package-proof.jpg',
                reference_number=generated_reference,
                amount='3250.00',
                include_receipt_text=False,
            ),
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PackageOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertNotIn('package_order_draft', self.client.session)

    def test_package_payment_allows_manual_review_with_valid_image_proof(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()
        generated_reference = self._package_checkout_reference()

        response = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': self._package_event_date(),
            'event_time': '14:30',
            'venue': 'Clarin Gymnasium',
            'contact_name': 'Package Tester',
            'contact_phone': '09999999999',
            'contact_email': 'package@example.com',
            'payment_method': 'cod',
            'payment_amount': '3250.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload(
                'manual-review-package-proof.jpg',
                reference_number=generated_reference,
                amount='3250.00',
                include_receipt_text=False,
            ),
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PackageOrder.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertNotIn('package_order_draft', self.client.session)

    def test_package_payment_get_renders_gcash_qr_preview(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
            'cake_custom_total': '0.00',
        }
        session.save()

        response = self.client.get(reverse('package_payment'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'multipart/form-data')
        self.assertContains(response, 'Account Name:')
        self.assertContains(response, 'GCash Number:')
        self.assertContains(response, reverse('payment_qr_preview'))
        self.assertContains(response, '50% GCash Deposit + COD Balance')
        self.assertContains(response, 'Order Number')
        self.assertContains(response, 'Amount Due')
        self.assertContains(response, 'Payment Reference Number')
        self.assertContains(response, 'Review Package Order')
        self.assertContains(response, 'Confirm Package Order')

    def test_package_cake_customize_get_renders_special_occasions_theme_option(self):
        session = self.client.session
        session['package_order_draft'] = {
            'package_id': str(self.package.id),
            'event_type': 'kids_birthday',
            'selected_addon_labels': [],
            'base_total': '6500.00',
        }
        session.save()

        response = self.client.get(reverse('package_cake_customize'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Special Occasions')
        self.assertNotContains(response, 'Graduation')


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
            role='customer',
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

    def _cake_checkout_reference(self):
        response = self.client.get(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
        })
        self.assertEqual(response.status_code, 200)
        return response.context['checkout_payment_reference']

    def _package_checkout_reference(self):
        response = self.client.get(reverse('package_payment'))
        self.assertEqual(response.status_code, 200)
        return response.context['checkout_payment_reference']

    def test_cake_order_redirects_to_tracking_with_created_order(self):
        generated_reference = self._cake_checkout_reference()

        response = self.client.post(reverse('cake_customize'), {
            'cake_id': str(self.cake.id),
            'quantity': '1',
            'payment_method': 'cod',
            'payment_amount': '490.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('tracking-cake.jpg', reference_number=generated_reference, amount='490.00'),
            'theme': 'Birthday',
            'size': '6 inches',
            'shape': 'Round',
            'flavor': 'Mocha',
            'frosting': 'Buttercream',
            'delivery_date': (timezone.now().date() + timedelta(days=7)).isoformat(),
            'delivery_street_address': '123 Rizal Street',
            'delivery_barangay': 'Poblacion 1',
            'delivery_city': 'Oroquieta City',
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
        self.assertEqual(
            len(tracking_response.context['selected_payments']), 2)
        self.assertContains(tracking_response, 'Submit Cancellation Request')
        self.assertContains(
            tracking_response,
            reverse('request_order_cancellation',
                    args=['cake', created_order.id]),
        )

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

        generated_reference = self._package_checkout_reference()

        final_step = self.client.post(reverse('package_payment'), {
            'event_type': 'kids_birthday',
            'event_date': (timezone.now().date() + timedelta(days=14)).isoformat(),
            'event_time': '15:00',
            'venue': 'Oroquieta Gym',
            'contact_name': 'Integration User',
            'contact_phone': '09170000000',
            'contact_email': 'integration@example.com',
            'payment_method': 'cod',
            'payment_amount': '4225.00',
            'reference_number': generated_reference,
            'proof_image': build_test_image_upload('tracking-package.jpg', reference_number=generated_reference, amount='4225.00'),
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
        self.assertEqual(
            len(tracking_response.context['selected_payments']), 2)
        self.assertNotIn('package_order_draft', self.client.session)

    def test_profile_shows_recent_orders_after_customer_login(self):
        cake_order = CakeOrder.objects.create(
            user=self.user,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('980.00'),
            payment_plan='cod',
            deposit_amount=Decimal('490.00'),
            balance_due=Decimal('490.00'),
            order_status='confirmed',
            contact_name='Integration User',
            contact_phone='09170000000',
            contact_email='integration@example.com',
        )
        package_order = PackageOrder.objects.create(
            user=self.user,
            package=self.package,
            total_price=Decimal('7000.00'),
            payment_plan='gcash',
            deposit_amount=Decimal('7000.00'),
            balance_due=Decimal('0.00'),
            order_status='pending',
            event_type='kids_birthday',
            event_date=date(2026, 8, 10),
            venue='Oroquieta Gym',
            contact_name='Integration User',
            contact_phone='09170000000',
            contact_email='integration@example.com',
        )

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['order_count'], 2)
        self.assertContains(response, 'Recent Orders')
        self.assertContains(
            response,
            f'{reverse("order_tracking")}?type=cake&id={cake_order.id}',
        )
        self.assertContains(
            response,
            f'{reverse("order_tracking")}?type=package&id={package_order.id}',
        )
        self.assertContains(response, self.cake.name)
        self.assertContains(response, self.package.name)

    def test_order_tracking_keeps_customer_archived_orders_visible(self):
        archived_order = CakeOrder.objects.create(
            user=self.user,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('980.00'),
            payment_plan='cod',
            deposit_amount=Decimal('490.00'),
            balance_due=Decimal('490.00'),
            order_status='confirmed',
            contact_name='Integration User',
            contact_phone='09170000000',
            contact_email='integration@example.com',
            is_archived=True,
        )

        response = self.client.get(
            f'{reverse("order_tracking")}?type=cake&id={archived_order.id}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['selected_order'].id, archived_order.id)
        self.assertContains(response, f'Cake Order #{archived_order.id}')
        self.assertContains(response, 'Archived Record')


class SecurityValidationTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username='viewer-user',
            password='TestPass123!',
            email='viewer@example.com',
        )
        UserProfile.objects.create(user=self.viewer, role='customer')

        self.admin_user = User.objects.create_user(
            username='admin-user',
            password='TestPass123!',
            email='admin@example.com',
        )
        UserProfile.objects.create(user=self.admin_user, role='admin')
        self.manager_user = User.objects.create_user(
            username='manager-user',
            password='TestPass123!',
            email='manager@example.com',
        )
        UserProfile.objects.create(user=self.manager_user, role='manager')
        self.cashier_user = User.objects.create_user(
            username='cashier-user',
            password='TestPass123!',
            email='cashier@example.com',
        )
        UserProfile.objects.create(user=self.cashier_user, role='cashier')
        self.supervisor_user = User.objects.create_user(
            username='supervisor-user',
            password='TestPass123!',
            email='supervisor@example.com',
        )
        UserProfile.objects.create(
            user=self.supervisor_user, role='supervisor')
        self.cake = Cake.objects.create(
            name='Admin Test Cake',
            category='birthday',
            description='Cake used for admin order tests.',
            price=Decimal('999.00'),
            stock=4,
            is_active=True,
        )
        self.package = Package.objects.create(
            name='Admin Test Package',
            package_type='christening',
            description='Package used for admin order tests.',
            base_price=Decimal('5000.00'),
            status='active',
        )

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

    def test_admin_dashboard_includes_total_sales_for_paid_payments_today(self):
        Payment.objects.create(
            amount=Decimal('1250.00'),
            payment_method='gcash',
            payment_status='paid',
            paid_at=timezone.now(),
        )
        Payment.objects.create(
            amount=Decimal('700.00'),
            payment_method='cod',
            payment_status='paid',
            paid_at=timezone.now() - timedelta(days=1),
        )
        Payment.objects.create(
            amount=Decimal('300.00'),
            payment_method='gcash',
            payment_status='pending',
            paid_at=timezone.now(),
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['total_sales_today'], Decimal('1250.00'))
        self.assertContains(response, "Today's Sales")
        self.assertContains(response, 'P1250.00')

    def test_admin_dashboard_includes_weekly_and_monthly_sales_totals(self):
        now = timezone.now()
        Payment.objects.create(
            amount=Decimal('900.00'),
            payment_method='gcash',
            payment_status='paid',
            paid_at=now,
        )
        Payment.objects.create(
            amount=Decimal('400.00'),
            payment_method='cod',
            payment_status='paid',
            paid_at=now - timedelta(days=2),
        )
        Payment.objects.create(
            amount=Decimal('600.00'),
            payment_method='gcash',
            payment_status='paid',
            paid_at=now - timedelta(days=10),
        )
        Payment.objects.create(
            amount=Decimal('2000.00'),
            payment_method='gcash',
            payment_status='paid',
            paid_at=now - timedelta(days=40),
        )
        Payment.objects.create(
            amount=Decimal('500.00'),
            payment_method='gcash',
            payment_status='pending',
            paid_at=now,
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['total_sales_week'], Decimal('1300.00'))
        self.assertEqual(
            response.context['total_sales_month'], Decimal('1900.00'))
        self.assertContains(response, "This Week's Sales")
        self.assertContains(response, "This Month's Sales")
        self.assertContains(response, 'P1300.00')
        self.assertContains(response, 'P1900.00')

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
        self.assertGreaterEqual(users_response.context['users'].count(), 4)
        self.assertContains(users_response, reverse('admin_user_add'))

    def test_admin_can_create_staff_user_from_admin_panel(self):
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(reverse('admin_user_add'), {
            'username': 'new-supervisor',
            'email': 'new-supervisor@example.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
            'first_name': 'New',
            'last_name': 'Supervisor',
            'phone': '09179990000',
            'address': 'Oroquieta City',
            'role': 'supervisor',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('admin_users'))
        created_user = User.objects.get(username='new-supervisor')
        self.assertEqual(created_user.profile.role, 'supervisor')
        self.assertTrue(created_user.is_staff)

    def test_manager_can_access_admin_users(self):
        self.client.login(username='manager-user', password='TestPass123!')

        response = self.client.get(reverse('admin_users'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Users')

    def test_cashier_can_access_admin_payments_and_refunds(self):
        self.client.login(username='cashier-user', password='TestPass123!')

        payments_response = self.client.get(reverse('admin_payments'))
        refunds_response = self.client.get(reverse('admin_refunds'))

        self.assertEqual(payments_response.status_code, 200)
        self.assertEqual(refunds_response.status_code, 200)

    def test_manager_can_access_admin_payments(self):
        self.client.login(username='manager-user', password='TestPass123!')

        response = self.client.get(reverse('admin_payments'))

        self.assertEqual(response.status_code, 200)

    def test_supervisor_has_full_access_to_operations_and_user_management(self):
        self.client.login(username='supervisor-user', password='TestPass123!')

        cake_orders_response = self.client.get(reverse('admin_cake_orders'))
        package_orders_response = self.client.get(
            reverse('admin_package_orders'))
        payments_response = self.client.get(reverse('admin_payments'))
        refunds_response = self.client.get(reverse('admin_refunds'))
        users_response = self.client.get(reverse('admin_users'))

        self.assertEqual(cake_orders_response.status_code, 200)
        self.assertEqual(package_orders_response.status_code, 200)
        self.assertEqual(payments_response.status_code, 200)
        self.assertEqual(refunds_response.status_code, 200)
        self.assertEqual(users_response.status_code, 200)

    def test_admin_can_access_activity_logs_page(self):
        ActivityLog.objects.create(
            actor=self.admin_user,
            actor_role='Admin - All Management',
            action='test_action',
            target_type='payment',
            target_id=1,
            description='Created for access test.',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_activity_logs'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Audit Trail')
        self.assertContains(response, 'Created for access test.')

    def test_admin_activity_logs_page_renders_delete_action(self):
        log = ActivityLog.objects.create(
            actor=self.admin_user,
            actor_role='Admin - All Management',
            action='test_action',
            target_type='payment',
            target_id=1,
            description='Created for delete action test.',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_activity_logs'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Archive')
        self.assertContains(
            response,
            reverse('admin_activity_log_delete', args=[log.id]),
        )

    def test_admin_can_delete_activity_log_via_post_route(self):
        log = ActivityLog.objects.create(
            actor=self.admin_user,
            actor_role='Admin - All Management',
            action='test_action',
            target_type='payment',
            target_id=1,
            description='Created for delete route test.',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_activity_log_delete', args=[log.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_activity_logs'))
        log.refresh_from_db()
        self.assertTrue(log.is_archived)
        self.assertIsNotNone(log.archived_at)
        self.assertNotContains(self.client.get(
            reverse('admin_activity_logs')), log.description)
        self.assertContains(self.client.get(
            f"{reverse('admin_activity_logs')}?archived=1"), log.description)

    def test_admin_dashboard_shows_recent_audit_trail_entries(self):
        for index in range(6):
            ActivityLog.objects.create(
                actor=self.admin_user,
                actor_role='Admin - All Management',
                action=f'action_{index}',
                target_type='payment',
                target_id=index + 1,
                description=f'Audit entry {index}',
            )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent Audit Trail')
        self.assertContains(response, 'Audit entry 5')
        self.assertContains(response, 'Audit entry 1')
        self.assertNotContains(response, 'Audit entry 0')
        self.assertEqual(len(response.context['recent_activity_logs']), 5)

    def test_admin_can_delete_user_via_post_route(self):
        delete_user = User.objects.create_user(
            username='delete-me',
            password='TestPass123!',
            email='delete-me@example.com',
        )
        UserProfile.objects.create(user=delete_user, role='customer')
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_user_delete', args=[delete_user.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('admin_users'))
        delete_user.refresh_from_db()
        self.assertFalse(delete_user.is_active)
        active_response = self.client.get(reverse('admin_users'))
        archived_response = self.client.get(
            f"{reverse('admin_users')}?archived=1")
        self.assertNotIn(delete_user, list(active_response.context['users']))
        self.assertIn(delete_user, list(archived_response.context['users']))

    def test_admin_users_page_renders_delete_action_for_other_users(self):
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_users'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Archive')
        self.assertContains(response, reverse(
            'admin_user_delete', args=[self.viewer.id]))

    def test_admin_payments_includes_verifying_gcash_in_review_list(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='0917234567',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_payments'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(payment, response.context['pending_payments'])
        self.assertContains(response, 'Payments For Review')
        self.assertContains(response, 'Under Verification')

    def test_admin_payment_verify_creates_activity_log(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='0917234567',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'approve',
        })

        self.assertEqual(response.status_code, 302)
        log = ActivityLog.objects.get(
            action='payment_status_updated', target_id=payment.id)
        self.assertEqual(log.actor, self.admin_user)
        self.assertIn('Updated payment', log.description)

    def test_admin_payments_page_renders_preview_customer_order_actions(self):
        cake_order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        package_order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('4200.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=cake_order,
            reference_number='CAKE-REF-001',
        )
        Payment.objects.create(
            amount=Decimal('4200.00'),
            payment_method='gcash',
            payment_status='pending',
            package_order=package_order,
            reference_number='PACKAGE-REF-001',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_payments'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview Customer Order', count=2)
        self.assertContains(response, reverse(
            'admin_cake_order_view', args=[cake_order.id]))
        self.assertContains(response, reverse(
            'admin_package_order_view', args=[package_order.id]))

    def test_admin_payments_review_pagination_uses_query_routes(self):
        for index in range(11):
            order = CakeOrder.objects.create(
                user=self.viewer,
                cake=self.cake,
                quantity=1,
                total_price=Decimal('999.00'),
                contact_name='Viewer User',
                contact_phone='09123456789',
                contact_email='viewer@example.com',
            )
            Payment.objects.create(
                amount=Decimal('999.00'),
                payment_method='gcash',
                payment_purpose='full',
                payment_status='verifying',
                cake_order=order,
                reference_number=f'PAGINATED-{index:03d}',
            )
        self.client.login(username='admin-user', password='TestPass123!')

        first_response = self.client.get(reverse('admin_payments'))
        second_response = self.client.get(
            f'{reverse("admin_payments")}?review_page=2')

        self.assertEqual(first_response.status_code, 200)
        self.assertContains(first_response, 'Showing 1-10 of 11')
        self.assertContains(first_response, '?review_page=2')
        self.assertNotContains(first_response, 'PAGINATED-000')

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, 'Showing 11-11 of 11')
        self.assertContains(second_response, 'PAGINATED-000')
        self.assertContains(second_response, reverse('admin_payments'))

    def test_admin_payment_verify_preserves_review_page_query(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='PRESERVE-001',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            f'{reverse("admin_payment_verify", args=[payment.id])}?review_page=2',
            {'action': 'approve'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'],
            f'{reverse("admin_payments")}?review_page=2',
        )

    def test_cashier_can_open_order_preview_from_payment_review(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            payment_plan='gcash',
            deposit_amount=Decimal('0.00'),
            balance_due=Decimal('0.00'),
            theme='Birthday',
            size='8 inches',
            flavor='Chocolate',
            frosting='Buttercream',
            message_on_cake='Happy Birthday',
            special_instructions='Use gold accents.',
            delivery_address='Oroquieta City',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_purpose='full',
            payment_status='verifying',
            cake_order=order,
            reference_number='CAKE-REF-002',
        )
        self.client.login(username='cashier-user', password='TestPass123!')

        response = self.client.get(
            reverse('admin_cake_order_view', args=[order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer Order Preview')
        self.assertContains(response, 'Happy Birthday')

    def test_supervisor_can_verify_payment_from_review_queue(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='SUP-VERIFY-001',
        )
        self.client.login(username='supervisor-user', password='TestPass123!')

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'approve',
        })

        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'paid')

    def test_cashier_can_verify_payment_from_review_queue(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('999.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='CASHIER-VERIFY-001',
        )
        self.client.login(username='cashier-user', password='TestPass123!')

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'approve',
        })

        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'paid')

    def test_admin_can_delete_verified_payment_via_post_route(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1500.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('1500.00'),
            payment_method='gcash',
            payment_status='paid',
            cake_order=order,
            reference_number='PAID-001',
            paid_at=timezone.now(),
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_payment_delete', args=[payment.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_payments'))
        payment.refresh_from_db()
        self.assertTrue(payment.is_archived)
        active_response = self.client.get(reverse('admin_payments'))
        archived_response = self.client.get(
            f"{reverse('admin_payments')}?archived=1")
        self.assertNotIn(payment, list(active_response.context['payments']))
        self.assertIn(payment, list(archived_response.context['payments']))

    def test_admin_can_delete_rejected_payment_via_post_route(self):
        order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('4200.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('4200.00'),
            payment_method='cod',
            payment_status='rejected',
            package_order=order,
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_payment_delete', args=[payment.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_payments'))
        payment.refresh_from_db()
        self.assertTrue(payment.is_archived)
        active_response = self.client.get(reverse('admin_payments'))
        archived_response = self.client.get(
            f"{reverse('admin_payments')}?archived=1")
        self.assertNotIn(payment, list(active_response.context['payments']))
        self.assertIn(payment, list(archived_response.context['payments']))

    def test_admin_payments_page_renders_delete_actions_for_completed_payments(self):
        cake_order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1800.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        package_order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('5200.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        verified_payment = Payment.objects.create(
            amount=Decimal('1800.00'),
            payment_method='gcash',
            payment_status='paid',
            cake_order=cake_order,
            reference_number='PAID-002',
            paid_at=timezone.now(),
        )
        rejected_payment = Payment.objects.create(
            amount=Decimal('5200.00'),
            payment_method='cod',
            payment_status='rejected',
            package_order=package_order,
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_payments'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse(
            'admin_payment_delete', args=[verified_payment.id]))
        self.assertContains(response, reverse(
            'admin_payment_delete', args=[rejected_payment.id]))
        self.assertContains(response, 'Archive')

    def test_admin_can_export_sales_report_as_xlsx(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1350.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        Payment.objects.create(
            amount=Decimal('1350.00'),
            payment_method='gcash',
            payment_status='paid',
            cake_order=order,
            payment_purpose='full',
            reference_number='SALES-XLSX-001',
            paid_at=timezone.now(),
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(
            reverse('admin_payments_export', args=['xlsx']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('hanilies-sales-report-',
                      response['Content-Disposition'])

    def test_admin_can_export_sales_report_as_pdf(self):
        order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('4800.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        Payment.objects.create(
            amount=Decimal('4800.00'),
            payment_method='gcash',
            payment_status='paid',
            package_order=order,
            payment_purpose='full',
            reference_number='SALES-PDF-001',
            paid_at=timezone.now(),
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(
            reverse('admin_payments_export', args=['pdf']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('hanilies-sales-report-',
                      response['Content-Disposition'])

    def test_customer_can_request_cancellation_and_staff_can_process_refund(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            payment_plan='cod',
            deposit_amount=Decimal('600.00'),
            balance_due=Decimal('600.00'),
            order_status='confirmed',
            delivery_date=timezone.now() + timedelta(days=5),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        Payment.objects.create(
            amount=Decimal('600.00'),
            payment_method='gcash',
            payment_purpose='deposit',
            payment_status='paid',
            cake_order=order,
            reference_number='DEP-PAID-001',
            paid_at=timezone.now(),
        )
        balance_payment = Payment.objects.create(
            amount=Decimal('600.00'),
            payment_method='cod',
            payment_purpose='balance',
            payment_status='pending',
            cake_order=order,
        )

        self.client.login(username='viewer-user', password='TestPass123!')
        response = self.client.post(
            reverse('request_order_cancellation', args=['cake', order.id]),
            {'reason': 'Family event was cancelled.'},
        )

        self.assertEqual(response.status_code, 302)
        refund_request = RefundRequest.objects.get(cake_order=order)
        self.assertEqual(refund_request.status, 'requested')
        self.assertEqual(refund_request.refundable_amount, Decimal('600.00'))

        tracking_response = self.client.get(
            f'{reverse("order_tracking")}?type=cake&id={order.id}')
        self.assertEqual(tracking_response.status_code, 200)
        self.assertContains(tracking_response, 'View Cancellation Details')
        self.assertContains(
            tracking_response, 'id="open-cancellation-details-button"', html=False)
        self.assertContains(tracking_response,
                            'id="cancellation-request-card"', html=False)
        self.assertContains(tracking_response, 'd-none', html=False)

        self.client.login(username='admin-user', password='TestPass123!')
        approve_response = self.client.post(
            reverse('admin_refund_update', args=[refund_request.id]),
            {'action': 'approve', 'internal_note': 'Approved for refund.'},
        )

        self.assertEqual(approve_response.status_code, 302)
        refund_request.refresh_from_db()
        order.refresh_from_db()
        balance_payment.refresh_from_db()
        self.assertEqual(refund_request.status, 'approved')
        self.assertEqual(order.order_status, 'cancelled')
        self.assertEqual(balance_payment.payment_status, 'cancelled')

        self.client.login(username='cashier-user', password='TestPass123!')
        process_response = self.client.post(
            reverse('admin_refund_update', args=[refund_request.id]),
            {'action': 'process', 'refund_reference_number': 'REFUND-001'},
        )

        self.assertEqual(process_response.status_code, 302)
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, 'processed')
        self.assertEqual(refund_request.refund_reference_number, 'REFUND-001')

    def test_admin_can_delete_cake_order_via_post_route(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_cake_order_delete', args=[order.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_cake_orders'))
        order.refresh_from_db()
        self.assertTrue(order.is_archived)
        active_response = self.client.get(reverse('admin_cake_orders'))
        archived_response = self.client.get(
            f"{reverse('admin_cake_orders')}?archived=1")
        self.assertNotIn(order, list(active_response.context['orders']))
        self.assertIn(order, list(archived_response.context['orders']))

    def test_admin_cake_orders_page_renders_delete_action_option(self):
        CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            order_status='confirmed',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_cake_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Archive Order')
        self.assertContains(response, 'Ready for Pickup')

    def test_admin_cake_orders_page_renders_preview_summary_action(self):
        order = CakeOrder.objects.create(
            user=self.viewer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('999.00'),
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_cake_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview Summary')
        self.assertContains(response, reverse(
            'admin_cake_order_view', args=[order.id]))

    def test_admin_can_delete_package_order_via_post_route(self):
        order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('5000.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.post(
            reverse('admin_package_order_delete', args=[order.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse(
            'admin_package_orders'))
        order.refresh_from_db()
        self.assertTrue(order.is_archived)
        active_response = self.client.get(reverse('admin_package_orders'))
        archived_response = self.client.get(
            f"{reverse('admin_package_orders')}?archived=1")
        self.assertNotIn(order, list(active_response.context['orders']))
        self.assertIn(order, list(archived_response.context['orders']))

    def test_admin_package_orders_page_renders_delete_action_option(self):
        PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('5000.00'),
            order_status='confirmed',
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_package_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Archive Order')
        self.assertContains(response, 'Out for Delivery')

    def test_admin_package_orders_page_renders_preview_summary_action(self):
        order = PackageOrder.objects.create(
            user=self.viewer,
            package=self.package,
            total_price=Decimal('5000.00'),
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Viewer User',
            contact_phone='09123456789',
            contact_email='viewer@example.com',
        )
        self.client.login(username='admin-user', password='TestPass123!')

        response = self.client.get(reverse('admin_package_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview Summary')
        self.assertContains(response, reverse(
            'admin_package_order_view', args=[order.id]))


class OrderStatusNotificationTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='notified-user',
            password='TestPass123!',
            email='customer@example.com',
            first_name='Notified',
            last_name='User',
        )
        UserProfile.objects.create(user=self.customer, role='customer')

        self.admin_user = User.objects.create_user(
            username='status-admin',
            password='TestPass123!',
            email='status-admin@example.com',
        )
        UserProfile.objects.create(user=self.admin_user, role='admin')

        self.cake = Cake.objects.create(
            name='Status Cake',
            category='birthday',
            description='Cake for notification tests.',
            price=Decimal('1200.00'),
            stock=3,
            is_active=True,
        )
        self.package = Package.objects.create(
            name='Status Package',
            package_type='christening',
            description='Package for notification tests.',
            base_price=Decimal('6500.00'),
            status='active',
        )

        self.client.login(username='status-admin', password='TestPass123!')

    def test_admin_cake_order_update_creates_customer_notification_for_key_status(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='confirmed',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_cake_order_update', args=[order.id]), {
            'status': 'preparing',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'preparing')
        notification = Notification.objects.get(cake_order=order)
        self.assertEqual(notification.user, self.customer)
        self.assertEqual(notification.notification_type, 'order_status')
        self.assertIn('Current status: Preparing.', notification.message)

    def test_admin_cake_order_update_accepts_ready_for_pickup_status(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='preparing',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_cake_order_update', args=[order.id]), {
            'status': 'ready_for_pickup',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'ready_for_pickup')
        notification = Notification.objects.get(cake_order=order)
        self.assertIn('Current status: Ready for Pickup.',
                      notification.message)

    def test_admin_cake_order_update_sends_customer_email(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='confirmed',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_cake_order_update', args=[order.id]), {
            'status': 'ready_for_pickup',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Cake Order #1 updated')
        self.assertIn('Current status: Ready for Pickup.', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['customer@example.com'])

    def test_admin_package_order_update_creates_customer_notification_for_key_status(self):
        order = PackageOrder.objects.create(
            user=self.customer,
            package=self.package,
            total_price=Decimal('6500.00'),
            order_status='confirmed',
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_package_order_update', args=[order.id]), {
            'status': 'preparing',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'preparing')
        self.assertTrue(Notification.objects.filter(
            package_order=order).exists())

    def test_admin_package_order_update_accepts_out_for_delivery_status(self):
        order = PackageOrder.objects.create(
            user=self.customer,
            package=self.package,
            total_price=Decimal('6500.00'),
            order_status='ready_for_pickup',
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_package_order_update', args=[order.id]), {
            'status': 'out_for_delivery',
        })

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'out_for_delivery')
        notification = Notification.objects.get(package_order=order)
        self.assertIn('Current status: Out for Delivery.',
                      notification.message)

    def test_no_notification_is_created_when_status_does_not_change(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='pending',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )

        response = self.client.post(reverse('admin_cake_order_update', args=[order.id]), {
            'status': 'pending',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Notification.objects.filter(
            cake_order=order).exists())

    def test_payment_approval_creates_customer_notification(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='confirmed',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('1200.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='REF-001',
        )

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'approve',
        })

        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'paid')
        notification = Notification.objects.get(payment=payment)
        self.assertEqual(notification.notification_type, 'payment_status')
        self.assertIn('payment status is now Paid', notification.message)

    def test_payment_approval_sends_customer_email(self):
        order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('1200.00'),
            order_status='confirmed',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('1200.00'),
            payment_method='gcash',
            payment_status='verifying',
            cake_order=order,
            reference_number='REF-003',
        )

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'approve',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject,
                         f'Payment #{payment.id} updated')
        self.assertIn('payment status is now Paid', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['customer@example.com'])

    def test_payment_rejection_creates_customer_notification(self):
        order = PackageOrder.objects.create(
            user=self.customer,
            package=self.package,
            total_price=Decimal('6500.00'),
            order_status='confirmed',
            event_type='christening',
            event_date=date(2026, 6, 1),
            event_time=time(10, 30),
            venue='Oroquieta City Hall',
            contact_name='Notified User',
            contact_phone='09170000000',
            contact_email='customer@example.com',
        )
        payment = Payment.objects.create(
            amount=Decimal('6500.00'),
            payment_method='gcash',
            payment_status='verifying',
            package_order=order,
            reference_number='REF-002',
        )

        response = self.client.post(reverse('admin_payment_verify', args=[payment.id]), {
            'action': 'reject',
        })

        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.payment_status, 'rejected')
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'payment_retry')
        notification = Notification.objects.get(payment=payment)
        self.assertEqual(notification.notification_type, 'payment_status')
        self.assertIn('payment status is now Rejected', notification.message)


class InAppNotificationViewTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='profile-user',
            password='TestPass123!',
            email='profile-user@example.com',
            first_name='Profile',
            last_name='User',
        )
        UserProfile.objects.create(user=self.customer, role='customer')
        self.cake = Cake.objects.create(
            name='Tracked Cake',
            category='birthday',
            description='Cake for tracking tests.',
            price=Decimal('900.00'),
            stock=2,
            is_active=True,
        )
        self.cake_order = CakeOrder.objects.create(
            user=self.customer,
            cake=self.cake,
            quantity=1,
            total_price=Decimal('900.00'),
            order_status='confirmed',
            contact_name='Profile User',
            contact_phone='09170000000',
            contact_email='profile-user@example.com',
        )
        self.notification = Notification.objects.create(
            user=self.customer,
            notification_type='order_status',
            title='Cake Order #1 updated',
            message='Your cake order has been confirmed.',
            status_value='confirmed',
            cake_order=self.cake_order,
            is_read=False,
        )
        self.client.login(username='profile-user', password='TestPass123!')

    def test_profile_page_lists_recent_notifications(self):
        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Notifications')
        self.assertContains(
            response, f'{reverse("profile")}?section=notifications')

    def test_profile_notifications_section_renders_on_right_panel_route(self):
        response = self.client.get(
            f'{reverse("profile")}?section=notifications')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['active_profile_section'], 'notifications')
        self.assertContains(response, self.notification.title)
        self.assertNotContains(response, 'Edit Profile Information')

    def test_profile_post_saves_structured_delivery_address(self):
        response = self.client.post(reverse('profile'), {
            'first_name': 'Profile',
            'last_name': 'User',
            'email': 'profile-user@example.com',
            'phone': '09170000000',
            'address_line_1': '45 Bonifacio Street',
            'address_barangay': 'Poblacion 2',
            'address_city': 'Oroquieta City',
            'address_landmark': 'Near the cathedral',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'],
            f'{reverse("profile")}?section=profile&tab=personal',
        )
        self.customer.profile.refresh_from_db()
        self.assertEqual(
            self.customer.profile.address,
            '45 Bonifacio Street, Brgy. Poblacion 2, Oroquieta City, Misamis Occidental (Landmark: Near the cathedral)',
        )

    def test_update_preferences_redirects_back_to_preferences_tab(self):
        response = self.client.post(reverse('update_preferences'), {
            'account_notifications': 'on',
            'promo_emails': 'on',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'],
            f'{reverse("profile")}?section=profile&tab=preferences',
        )

    def test_order_tracking_marks_selected_order_notifications_read(self):
        response = self.client.get(
            f'{reverse("order_tracking")}?type=cake&id={self.cake_order.id}')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.notification.message)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AdminPackageImageUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='package-admin',
            password='TestPass123!',
            email='package-admin@example.com',
        )
        UserProfile.objects.create(user=self.admin_user, role='admin')
        self.client.login(username='package-admin', password='TestPass123!')

    def test_admin_package_add_saves_uploaded_image(self):
        uploaded_image = SimpleUploadedFile(
            'package.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )
        thumbnail_one = SimpleUploadedFile(
            'thumb1.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )
        thumbnail_two = SimpleUploadedFile(
            'thumb2.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )

        response = self.client.post(reverse('admin_package_add'), {
            'name': 'Image Package',
            'package_type': 'christening',
            'description': 'Package with uploaded image.',
            'base_price': '4500.00',
            'status': 'active',
            'features': 'Backdrop\nCupcakes',
            'image': uploaded_image,
            'thumbnail_1': thumbnail_one,
            'thumbnail_2': thumbnail_two,
        })

        self.assertEqual(response.status_code, 302)
        package = Package.objects.get(name='Image Package')
        self.assertTrue(bool(package.image))
        self.assertIn('packages/', package.image.name)
        self.assertEqual(package.thumbnails.count(), 2)
        self.assertEqual(
            list(package.thumbnails.order_by(
                'sort_order').values_list('sort_order', flat=True)),
            [1, 2],
        )

    def test_admin_package_edit_replaces_image_when_new_file_uploaded(self):
        original_image = SimpleUploadedFile(
            'original.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )
        package = Package.objects.create(
            name='Editable Package',
            package_type='christening',
            description='Package before edit.',
            base_price=Decimal('5500.00'),
            status='active',
            features='Stage lights',
            image=original_image,
        )
        original_thumbnail = PackageThumbnail.objects.create(
            package=package,
            sort_order=1,
            image=SimpleUploadedFile(
                'original-thumb.jpg',
                (
                    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                    b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                    b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                    b'\x00\x3b'
                ),
                content_type='image/gif',
            ),
        )
        original_name = package.image.name
        original_thumbnail_name = original_thumbnail.image.name

        replacement_image = SimpleUploadedFile(
            'replacement.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )
        replacement_thumbnail = SimpleUploadedFile(
            'replacement-thumb.jpg',
            (
                b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                b'\x00\x3b'
            ),
            content_type='image/gif',
        )

        response = self.client.post(reverse('admin_package_edit', args=[package.id]), {
            'name': 'Editable Package',
            'package_type': 'christening',
            'description': 'Package after edit.',
            'base_price': '5500.00',
            'status': 'active',
            'features': 'Stage lights\nBalloons',
            'image': replacement_image,
            'thumbnail_1': replacement_thumbnail,
        })

        self.assertEqual(response.status_code, 302)
        package.refresh_from_db()
        self.assertTrue(bool(package.image))
        self.assertNotEqual(package.image.name, original_name)
        updated_thumbnail = package.thumbnails.get(sort_order=1)
        self.assertNotEqual(updated_thumbnail.image.name,
                            original_thumbnail_name)

    def test_admin_package_edit_can_remove_thumbnail_slot(self):
        package = Package.objects.create(
            name='Package With Thumbnail',
            package_type='christening',
            description='Package before thumbnail removal.',
            base_price=Decimal('5500.00'),
            status='active',
            features='Stage lights',
        )
        PackageThumbnail.objects.create(
            package=package,
            sort_order=1,
            image=SimpleUploadedFile(
                'remove-thumb.jpg',
                (
                    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                    b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                    b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                    b'\x00\x3b'
                ),
                content_type='image/gif',
            ),
        )

        response = self.client.post(reverse('admin_package_edit', args=[package.id]), {
            'name': 'Package With Thumbnail',
            'package_type': 'christening',
            'description': 'Package after thumbnail removal.',
            'base_price': '5500.00',
            'status': 'active',
            'features': 'Stage lights',
            'remove_thumbnail_1': 'on',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(package.thumbnails.exists())


class PackageThumbnailCatalogTests(TestCase):
    def test_packages_page_renders_zoom_gallery_data_for_package(self):
        package = Package.objects.create(
            name='Gallery Package',
            package_type='christening',
            description='Package with thumbnail gallery.',
            base_price=Decimal('5500.00'),
            status='active',
            features='Backdrop',
            image=SimpleUploadedFile(
                'main.jpg',
                (
                    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                    b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                    b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                    b'\x00\x3b'
                ),
                content_type='image/gif',
            ),
        )
        for slot_order in range(1, 5):
            PackageThumbnail.objects.create(
                package=package,
                sort_order=slot_order,
                image=SimpleUploadedFile(
                    f'thumb-{slot_order}.jpg',
                    (
                        b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
                        b'\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00'
                        b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01'
                        b'\x00\x3b'
                    ),
                    content_type='image/gif',
                ),
            )

        response = self.client.get(reverse('packages'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-zoom-images=')
        self.assertNotContains(response, 'data-thumbnail-src=')
        self.assertContains(response, '5 images available in zoom')
        self.assertContains(response, package.image.url)
        for thumbnail in package.thumbnails.order_by('sort_order'):
            self.assertContains(response, thumbnail.image.url)


class HomeRecommendationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='recommend-user',
            password='TestPass123!',
            first_name='Recommend',
            last_name='User',
            email='recommend@example.com',
        )
        UserProfile.objects.create(user=self.user, role='customer')

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
        self.assertContains(
            response, 'data-zoom-gallery="home-recommended-cakes"')
        self.assertContains(
            response, 'data-zoom-gallery="home-recommended-packages"')


class AuthenticationFlowTests(TestCase):
    def _build_user_with_role(self, role, index=1):
        user = User.objects.create_user(
            username=f'{role}-user-{index}',
            email=f'{role}-{index}@example.com',
            password='TestPass123!',
            first_name=role.title(),
            last_name='Reset',
        )
        UserProfile.objects.create(user=user, role=role)
        if role != 'customer':
            user.is_staff = True
            user.save(update_fields=['is_staff'])
        return user

    def _extract_reset_path(self, body):
        for line in body.splitlines():
            candidate = line.strip()
            if candidate.startswith('http://testserver'):
                return urlsplit(candidate).path
        self.fail('Password reset email did not include a reset link.')

    def test_public_register_creates_customer_profile(self):
        response = self.client.post(reverse('register'), {
            'username': 'registered-customer',
            'email': 'registered@example.com',
            'password': 'TestPass123!',
            'confirm_password': 'TestPass123!',
            'firstname': 'Registered',
            'lastname': 'Customer',
            'phone': '09171234567',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('profile'))
        registered_user = User.objects.get(username='registered-customer')
        self.assertEqual(registered_user.profile.role, 'customer')
        self.assertFalse(registered_user.is_staff)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject,
                         'Welcome to Hanilies Cakeshoppe')
        self.assertEqual(mail.outbox[0].to, ['registered@example.com'])
        self.assertIn('http://testserver' +
                      reverse('login'), mail.outbox[0].body)
        self.assertIn('http://testserver' +
                      reverse('profile'), mail.outbox[0].body)
        self.assertIn('http://testserver' +
                      reverse('contact'), mail.outbox[0].body)

    def test_authenticated_customer_is_redirected_away_from_login_page(self):
        user = User.objects.create_user(
            username='existing-customer',
            email='existing@example.com',
            password='TestPass123!',
        )
        UserProfile.objects.create(user=user, role='customer')
        self.client.login(username='existing-customer',
                          password='TestPass123!')

        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], reverse('profile'))

    def test_authenticated_staff_is_redirected_away_from_login_page(self):
        user = User.objects.create_user(
            username='existing-admin',
            email='admin@example.com',
            password='TestPass123!',
        )
        UserProfile.objects.create(user=user, role='admin')
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        self.client.login(username='existing-admin', password='TestPass123!')

        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'], reverse('admin_dashboard'))

    def test_login_page_shows_forgot_password_link(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('password_reset'))
        self.assertContains(response, 'Forgot Password?')

    def test_password_reset_request_supports_all_roles(self):
        roles = [role for role, _ in UserProfile.ROLE_CHOICES]

        for index, role in enumerate(roles, start=1):
            user = self._build_user_with_role(role, index=index)

            response = self.client.post(
                reverse('password_reset'),
                {'email': user.email},
                follow=True,
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                'Password reset instructions have been sent if the email is registered.',
            )

        self.assertEqual(len(mail.outbox), len(roles))
        self.assertEqual(
            ActivityLog.objects.filter(
                action='Password reset requested').count(),
            len(roles),
        )

    def test_password_reset_request_uses_generic_message_for_unknown_email(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': 'missing@example.com'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Password reset instructions have been sent if the email is registered.',
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            ActivityLog.objects.filter(
                action='Password reset requested').exists()
        )

    def test_password_reset_confirm_updates_password_and_logs_completion(self):
        user = self._build_user_with_role('customer')
        request_response = self.client.post(
            reverse('password_reset'),
            {'email': user.email},
            follow=True,
        )

        self.assertContains(
            request_response,
            'Password reset instructions have been sent if the email is registered.',
        )
        self.assertEqual(len(mail.outbox), 1)

        reset_path = self._extract_reset_path(mail.outbox[0].body)
        confirm_response = self.client.get(reset_path, follow=True)

        self.assertEqual(confirm_response.status_code, 200)
        self.assertContains(confirm_response, 'Set a New Password')

        completion_response = self.client.post(
            confirm_response.request['PATH_INFO'],
            {
                'new_password1': 'NewSecurePass456!',
                'new_password2': 'NewSecurePass456!',
            },
            follow=True,
        )

        self.assertEqual(completion_response.status_code, 200)
        self.assertEqual(
            completion_response.request['PATH_INFO'],
            reverse('login'),
        )
        self.assertContains(
            completion_response,
            'Password successfully reset. You may now log in.',
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password('NewSecurePass456!'))
        self.assertEqual(
            ActivityLog.objects.filter(
                action='Password reset completed', actor=user).count(),
            1,
        )

    def test_password_reset_confirm_enforces_password_validation(self):
        user = self._build_user_with_role('manager')
        self.client.post(reverse('password_reset'), {
                         'email': user.email}, follow=True)
        reset_path = self._extract_reset_path(mail.outbox[0].body)
        confirm_response = self.client.get(reset_path, follow=True)

        response = self.client.post(
            confirm_response.request['PATH_INFO'],
            {
                'new_password1': 'password123',
                'new_password2': 'password123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This password is too common.')

        user.refresh_from_db()
        self.assertTrue(user.check_password('TestPass123!'))
        self.assertFalse(
            ActivityLog.objects.filter(
                action='Password reset completed', actor=user).exists()
        )


@override_settings(DEBUG=False, DEMO_BOT_REMOTE_ENABLED=True)
class RemoteBrowserDemoBotTests(TestCase):
    def test_remote_demo_bot_prefers_latest_image_backed_showcase_catalog(self):
        Cake.objects.create(
            name='Older Demo Cake',
            category='birthday',
            description='Older cake for ordering.',
            price=Decimal('750.00'),
            stock=2,
            image='cakes/older-demo.jpg',
            is_active=True,
        )
        showcase_cake = Cake.objects.create(
            name='Showcase Special Occasion Cake',
            category='custom',
            description='Newest special-occasion cake with image.',
            price=Decimal('1450.00'),
            stock=3,
            image='cakes/showcase-demo.jpg',
            is_active=True,
        )
        Package.objects.create(
            name='Older Demo Package',
            package_type='christening',
            description='Older package for ordering.',
            base_price=Decimal('6500.00'),
            image='packages/older-demo.jpg',
            status='active',
        )
        showcase_package = Package.objects.create(
            name='Showcase Wedding Package',
            package_type='wedding',
            description='Newest package with main image and thumbnails.',
            base_price=Decimal('15000.00'),
            image='packages/showcase-demo.jpg',
            status='active',
        )
        PackageThumbnail.objects.create(
            package=showcase_package,
            image='packages/thumbnails/showcase-1.jpg',
            sort_order=1,
        )

        response = self.client.post(
            reverse('start_demo_bot'),
            data=json.dumps({'scenario': 'full', 'payment_mode': 'cod'}),
            content_type='application/json',
            REMOTE_ADDR='198.51.100.20',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()['browser_demo']
        self.assertEqual(
            payload['step_urls']['cakes'],
            f"{reverse('cakes')}?category=custom",
        )
        self.assertEqual(
            payload['step_urls']['cake_order'],
            f"{reverse('cake_customize')}?cake_id={showcase_cake.id}",
        )
        self.assertEqual(
            payload['step_urls']['packages'],
            f"{reverse('packages')}?type={showcase_package.package_type}",
        )
        self.assertEqual(
            payload['step_urls']['package_order'],
            f"{reverse('order_package')}?package_id={showcase_package.id}",
        )

    def test_remote_demo_bot_start_prepares_browser_walkthrough(self):
        response = self.client.post(
            reverse('start_demo_bot'),
            data=json.dumps({'scenario': 'full', 'payment_mode': 'cod'}),
            content_type='application/json',
            REMOTE_ADDR='198.51.100.20',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['mode'], 'browser')
        self.assertEqual(payload['browser_demo']
                         ['credentials']['username'], 'paneldemo')
        self.assertIn('launch_url', payload['browser_demo'])
        self.assertIn('cake_tracking', payload['browser_demo']['step_urls'])

        demo_user = User.objects.get(username='paneldemo')
        self.assertTrue(demo_user.cake_orders.exists())
        self.assertTrue(demo_user.package_orders.exists())
        demo_cake_order = demo_user.cake_orders.order_by('-id').first()
        self.assertEqual(
            payload['browser_demo']['step_urls']['order_tracking'],
            f"{reverse('order_tracking')}?type=cake&id={demo_cake_order.id}",
        )

    def test_remote_demo_bot_start_keeps_manual_gcash_flow_without_payment_demo_steps(self):
        response = self.client.post(
            reverse('start_demo_bot'),
            data=json.dumps({'scenario': 'full', 'payment_mode': 'gcash'}),
            content_type='application/json',
            REMOTE_ADDR='198.51.100.20',
        )

        self.assertEqual(response.status_code, 200)
        browser_demo = response.json()['browser_demo']
        self.assertNotIn('cake_payment_demo', browser_demo['script_steps'])
        self.assertNotIn('package_payment_demo', browser_demo['script_steps'])
        self.assertNotIn('cake_payment_demo', browser_demo['step_urls'])
        self.assertNotIn('package_payment_demo', browser_demo['step_urls'])

    def test_remote_demo_bot_status_and_stop_work_for_browser_mode(self):
        self.client.post(
            reverse('start_demo_bot'),
            data=json.dumps({'scenario': 'login', 'payment_mode': 'gcash'}),
            content_type='application/json',
            REMOTE_ADDR='198.51.100.20',
        )

        status_response = self.client.get(
            reverse('demo_bot_status'),
            REMOTE_ADDR='198.51.100.20',
        )
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()
        self.assertTrue(status_payload['running'])
        self.assertEqual(status_payload['active_demo']['mode'], 'browser')

        stop_response = self.client.post(
            reverse('stop_demo_bot'),
            REMOTE_ADDR='198.51.100.20',
        )
        self.assertEqual(stop_response.status_code, 200)

        final_status = self.client.get(
            reverse('demo_bot_status'),
            REMOTE_ADDR='198.51.100.20',
        )
        self.assertEqual(final_status.status_code, 200)
        self.assertFalse(final_status.json()['running'])


class MediaSyncCommandTests(TestCase):
    def test_sync_repo_media_copies_repo_media_into_media_root(self):
        source_base_dir = Path(tempfile.mkdtemp())
        destination_media_root = Path(tempfile.mkdtemp())

        self.addCleanup(shutil.rmtree, source_base_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, destination_media_root,
                        ignore_errors=True)

        source_file = source_base_dir / 'media' / 'cakes' / 'deploy-sample.txt'
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text('repo media content', encoding='utf-8')

        with override_settings(BASE_DIR=source_base_dir, MEDIA_ROOT=destination_media_root):
            call_command('sync_repo_media')

        synced_file = destination_media_root / 'cakes' / 'deploy-sample.txt'
        self.assertTrue(synced_file.exists())
        self.assertEqual(synced_file.read_text(
            encoding='utf-8'), 'repo media content')


class MediaServingTests(TestCase):
    def test_media_file_is_served_from_media_url(self):
        media_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)

        media_file = media_root / 'packages' / 'visible.txt'
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_text('package image placeholder', encoding='utf-8')

        with override_settings(MEDIA_ROOT=media_root):
            response = self.client.get('/media/packages/visible.txt')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content),
            b'package image placeholder',
        )


class CatalogSeedFixtureTests(TestCase):
    def test_catalog_seed_fixture_loads_into_empty_database(self):
        Cake.objects.all().delete()
        Package.objects.all().delete()

        call_command('loaddata', 'catalog_seed', verbosity=0)

        self.assertEqual(Cake.objects.count(), 25)
        self.assertEqual(Package.objects.count(), 12)
        self.assertTrue(Cake.objects.filter(
            name='Chocolate Fudge Cake').exists())
        self.assertTrue(Cake.objects.filter(
            name="Valentine's Day Cake", category='custom').exists())
        self.assertTrue(Cake.objects.filter(
            name='New Year Cake', category='custom').exists())
        self.assertTrue(Package.objects.filter(
            name='Wedding Package A').exists())

    def test_catalog_seed_fixture_can_be_loaded_again_without_duplicate_rows(self):
        call_command('loaddata', 'catalog_seed', verbosity=0)
        call_command('loaddata', 'catalog_seed', verbosity=0)

        self.assertEqual(Cake.objects.count(), 25)
        self.assertEqual(Package.objects.count(), 12)

    def test_special_occasions_route_lists_seeded_custom_cakes(self):
        call_command('loaddata', 'catalog_seed', verbosity=0)

        response = self.client.get(reverse('cakes'), {'category': 'custom'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cakes'].count(), 9)
        self.assertContains(response, 'Graduation Cake')
        self.assertContains(response, 'Debut Cake')
        self.assertContains(response, 'Gender Reveal Cake')
        self.assertContains(response, 'Christmas Cake')
        self.assertContains(response, 'New Year Cake')
        seeded_cake = Cake.objects.get(name="Valentine's Day Cake")
        self.assertContains(
            response,
            f"{reverse('cake_customize')}?cake_id={seeded_cake.id}",
        )
