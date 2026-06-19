import base64
import hashlib
import re
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
            'Scan this QR inside GCash so the payment amount and Hanilies reference are filled in automatically.',
        ),
    }


def _normalize_amount(amount):
    try:
        return Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')


def _clean_numeric(value):
    return ''.join(character for character in str(value or '') if character.isdigit())


def _sanitize_emv_text(value, fallback, max_length):
    normalized = re.sub(r'[^A-Z0-9 .,&/\-]', '',
                        str(value or '').upper()).strip()
    if not normalized:
        normalized = fallback
    return normalized[:max_length]


def _format_tlv(tag, value):
    normalized_value = str(value)
    return f'{tag}{len(normalized_value):02d}{normalized_value}'


def _build_crc16(payload):
    crc_value = 0xFFFF
    for byte in payload.encode('ascii'):
        crc_value ^= byte << 8
        for _ in range(8):
            if crc_value & 0x8000:
                crc_value = ((crc_value << 1) ^ 0x1021) & 0xFFFF
            else:
                crc_value = (crc_value << 1) & 0xFFFF
    return f'{crc_value:04X}'


def build_gcash_payment_reference(amount, order_label, reference_seed=''):
    normalized_amount = _normalize_amount(amount)
    cleaned_label = (order_label or 'Order payment').strip() or 'Order payment'
    raw_seed = '|'.join([
        str(reference_seed or 'public-preview'),
        cleaned_label.lower(),
        f'{normalized_amount:.2f}',
    ])
    digest = hashlib.sha1(raw_seed.encode('utf-8')).hexdigest().upper()
    return f'HANI-{digest[:10]}'


def build_gcash_instruction_payload(amount, order_label, reference_seed='', payment_reference=''):
    normalized_amount = _normalize_amount(amount)
    profile = get_gcash_profile()
    cleaned_label = (order_label or 'Order payment').strip() or 'Order payment'
    payment_reference = str(payment_reference or '').strip().upper() or build_gcash_payment_reference(
        normalized_amount,
        cleaned_label,
        reference_seed,
    )

    merchant_name = _sanitize_emv_text(
        profile['account_name'],
        'HANILIES CAKESHOPPE',
        25,
    )
    merchant_city = _sanitize_emv_text(
        getattr(settings, 'HANILIES_GCASH_MERCHANT_CITY', 'TAYTAY'),
        'TAYTAY',
        15,
    )
    merchant_category_code = _clean_numeric(
        getattr(settings, 'HANILIES_GCASH_MERCHANT_CATEGORY_CODE', '5462'),
    ) or '5462'
    qr_gui = str(getattr(settings, 'HANILIES_GCASH_QR_GUI',
                 'ph.ppmi.qrph')).strip() or 'ph.ppmi.qrph'
    account_number = _clean_numeric(profile['account_number'])
    purpose_label = _sanitize_emv_text(cleaned_label, 'ORDER PAYMENT', 25)

    merchant_account_information = ''.join([
        _format_tlv('00', qr_gui),
        _format_tlv('01', account_number),
    ])
    additional_data = ''.join([
        _format_tlv('01', payment_reference),
        _format_tlv('05', payment_reference),
        _format_tlv('08', purpose_label),
    ])
    payload_without_crc = ''.join([
        _format_tlv('00', '01'),
        _format_tlv('01', '12'),
        _format_tlv('26', merchant_account_information),
        _format_tlv('52', merchant_category_code[:4].zfill(4)),
        _format_tlv('53', '608'),
        _format_tlv('54', f'{normalized_amount:.2f}'),
        _format_tlv('58', 'PH'),
        _format_tlv('59', merchant_name),
        _format_tlv('60', merchant_city),
        _format_tlv('62', additional_data),
        '6304',
    ])
    return f'{payload_without_crc}{_build_crc16(payload_without_crc)}'


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


def build_gcash_checkout_details(amount, order_label, reference_seed='', payment_reference=''):
    normalized_amount = _normalize_amount(amount)
    profile = get_gcash_profile()
    payment_reference = str(payment_reference or '').strip().upper() or build_gcash_payment_reference(
        normalized_amount,
        order_label,
        reference_seed,
    )
    payload = build_gcash_instruction_payload(
        normalized_amount,
        order_label,
        reference_seed,
        payment_reference=payment_reference,
    )

    return {
        **profile,
        'amount': f'{normalized_amount:.2f}',
        'amount_label': f'P{normalized_amount:.2f}',
        'order_label': (order_label or 'Order payment').strip() or 'Order payment',
        'payment_reference': payment_reference,
        'instruction_payload': payload,
        'qr_code_data_uri': generate_qr_code_data_uri(payload),
    }
