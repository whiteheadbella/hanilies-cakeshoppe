from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0020_backfill_missing_product_codes'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomeHeroImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True,
                 primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('image', models.ImageField(upload_to='hero/')),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['display_order', 'id'],
            },
        ),
    ]
