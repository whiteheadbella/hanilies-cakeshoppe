from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(choices=[
                 ('order_status', 'Order Status'), ('payment_status', 'Payment Status')], max_length=20)),
                ('title', models.CharField(max_length=150)),
                ('message', models.TextField()),
                ('status_value', models.CharField(blank=True, max_length=30)),
                ('is_read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cake_order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                 related_name='notifications', to='hanilies.cakeorder')),
                ('package_order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                 related_name='notifications', to='hanilies.packageorder')),
                ('payment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                 related_name='notifications', to='hanilies.payment')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                 related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
