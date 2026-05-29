import base64
from decimal import Decimal, InvalidOperation
from io import BytesIO

import qrcode
from django.conf import settings


def get_gcash_profile():
    return {
        'account_name': getattr(
            settings,
            'HANILIES_GCASH_ACCOUNT_NAME',
            'Hanilies Cakeshoppe',
        ),
        'account_number': getattr(
            settings,
            'HANILIES_GCASH_ACCOUNT_NUMBER',
            '09171234567',
        ),
        'payment_note': getattr(
            settings,
            'HANILIES_GCASH_PAYMENT_NOTE',
            'Scan this QR to copy the payment instructions on another device, or open GCash and send payment manually using the account below.',
        ),
    }


def _normalize_amount(amount):
    try:
        return Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')


def build_gcash_instruction_payload(amount, order_label):
    normalized_amount = _normalize_amount(amount)
    profile = get_gcash_profile()
    cleaned_label = (order_label or 'Order payment').strip() or 'Order payment'

    lines = [
        'Hanilies Cakeshoppe GCash Payment',
        f"Account Name: {profile['account_name']}",
        f"GCash Number: {profile['account_number']}",
        f'Amount: PHP {normalized_amount:.2f}',
        f'Payment For: {cleaned_label}',
        'After sending payment, upload the GCash reference number and proof of payment in checkout.',
    ]
    return '\n'.join(lines)


def generate_qr_code_data_uri(payload):
    qr_code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr_code.add_data(payload)
    qr_code.make(fit=True)

    image = qr_code.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def build_gcash_checkout_details(amount, order_label):
    normalized_amount = _normalize_amount(amount)
    profile = get_gcash_profile()
    payload = build_gcash_instruction_payload(normalized_amount, order_label)

    return {
        **profile,
        'amount': f'{normalized_amount:.2f}',
        'amount_label': f'P{normalized_amount:.2f}',
        'order_label': (order_label or 'Order payment').strip() or 'Order payment',
        'instruction_payload': payload,
        'qr_code_data_uri': generate_qr_code_data_uri(payload),
    }
