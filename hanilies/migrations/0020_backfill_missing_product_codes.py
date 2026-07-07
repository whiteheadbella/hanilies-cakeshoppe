from django.db import migrations
from django.db.models import Q


def backfill_missing_product_codes(apps, schema_editor):
    Cake = apps.get_model('hanilies', 'Cake')
    Package = apps.get_model('hanilies', 'Package')

    for cake_id in Cake.objects.filter(
        Q(product_code__isnull=True) | Q(product_code='')
    ).values_list('id', flat=True):
        Cake.objects.filter(pk=cake_id).update(
            product_code=f'CK-{cake_id:04d}')

    for package_id in Package.objects.filter(
        Q(product_code__isnull=True) | Q(product_code='')
    ).values_list('id', flat=True):
        Package.objects.filter(pk=package_id).update(
            product_code=f'PKG-{package_id:04d}')


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0019_cake_and_package_product_codes'),
    ]

    operations = [
        migrations.RunPython(backfill_missing_product_codes,
                             migrations.RunPython.noop),
    ]
