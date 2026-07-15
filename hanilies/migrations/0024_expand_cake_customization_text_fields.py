from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hanilies', '0023_alter_package_package_type_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cakeorder',
            name='filling',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='cakeorder',
            name='frosting',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='packageorder',
            name='cake_filling',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='packageorder',
            name='cake_frosting',
            field=models.TextField(blank=True),
        ),
    ]
