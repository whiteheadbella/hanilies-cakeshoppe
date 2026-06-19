from django.db import migrations, models


def forwards(apps, schema_editor):
    CakeOrder = apps.get_model('hanilies', 'CakeOrder')
    PackageOrder = apps.get_model('hanilies', 'PackageOrder')

    for order in CakeOrder.objects.filter(order_number__isnull=True).order_by('id'):
        order.order_number = f'CKO-{order.id:06d}'
        order.save(update_fields=['order_number'])

    for order in PackageOrder.objects.filter(order_number__isnull=True).order_by('id'):
        order.order_number = f'PKO-{order.id:06d}'
        order.save(update_fields=['order_number'])


def backwards(apps, schema_editor):
    CakeOrder = apps.get_model('hanilies', 'CakeOrder')
    PackageOrder = apps.get_model('hanilies', 'PackageOrder')
    CakeOrder.objects.update(order_number=None)
    PackageOrder.objects.update(order_number=None)


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0014_rbac_and_payment_workflow_updates'),
    ]

    operations = [
        migrations.AddField(
            model_name='cakeorder',
            name='order_number',
            field=models.CharField(
                blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='packageorder',
            name='order_number',
            field=models.CharField(
                blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.RunPython(forwards, backwards),
    ]
