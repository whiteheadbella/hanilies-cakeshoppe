from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0016_alter_cakeorder_order_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cake',
            name='customization_options',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='package',
            name='customization_options',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
