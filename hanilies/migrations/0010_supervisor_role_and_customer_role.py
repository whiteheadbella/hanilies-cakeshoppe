from django.db import migrations, models


def migrate_viewer_to_customer(apps, schema_editor):
    UserProfile = apps.get_model('hanilies', 'UserProfile')
    UserProfile.objects.filter(role='viewer').update(role='customer')


def migrate_customer_to_viewer(apps, schema_editor):
    UserProfile = apps.get_model('hanilies', 'UserProfile')
    UserProfile.objects.filter(role='customer').update(role='viewer')


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0009_cakeorder_balance_due_cakeorder_deposit_amount_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_viewer_to_customer, migrate_customer_to_viewer),
        migrations.AlterField(
            model_name='userprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('owner', 'Owner - Full Access'),
                    ('admin', 'Admin - All Management'),
                    ('manager', 'Manager - Orders & Customers'),
                    ('supervisor', 'Supervisor - Operations Oversight'),
                    ('baker', 'Baker - Cake Management'),
                    ('packager', 'Packager - Package Management'),
                    ('cashier', 'Cashier - Payments Only'),
                    ('customer', 'Customer - Customer Portal'),
                ],
                default='customer',
                max_length=20,
            ),
        ),
    ]