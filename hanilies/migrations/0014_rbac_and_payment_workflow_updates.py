from django.db import migrations


def forwards(apps, schema_editor):
    CakeOrder = apps.get_model('hanilies', 'CakeOrder')
    PackageOrder = apps.get_model('hanilies', 'PackageOrder')
    Payment = apps.get_model('hanilies', 'Payment')

    CakeOrder.objects.filter(order_status='delivered').update(
        order_status='completed')
    Payment.objects.filter(payment_status='failed').update(
        payment_status='rejected')

    cake_rejected_ids = list(
        Payment.objects.filter(
            cake_order__isnull=False,
            payment_purpose__in=['deposit', 'full'],
            payment_status='rejected',
        ).values_list('cake_order_id', flat=True)
    )
    package_rejected_ids = list(
        Payment.objects.filter(
            package_order__isnull=False,
            payment_purpose__in=['deposit', 'full'],
            payment_status='rejected',
        ).values_list('package_order_id', flat=True)
    )
    CakeOrder.objects.filter(id__in=cake_rejected_ids, order_status='pending').update(
        order_status='payment_retry'
    )
    PackageOrder.objects.filter(id__in=package_rejected_ids, order_status='pending').update(
        order_status='payment_retry'
    )


def backwards(apps, schema_editor):
    CakeOrder = apps.get_model('hanilies', 'CakeOrder')
    PackageOrder = apps.get_model('hanilies', 'PackageOrder')
    Payment = apps.get_model('hanilies', 'Payment')

    CakeOrder.objects.filter(order_status='completed').update(
        order_status='delivered')
    Payment.objects.filter(payment_status='rejected').update(
        payment_status='failed')
    CakeOrder.objects.filter(order_status='payment_retry').update(
        order_status='pending')
    PackageOrder.objects.filter(
        order_status='payment_retry').update(order_status='pending')


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0013_archive_records'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
