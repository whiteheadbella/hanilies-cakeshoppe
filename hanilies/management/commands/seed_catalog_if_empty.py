from django.core.management import BaseCommand, call_command
from django.db.models import Q

from hanilies.models import Cake, Package, _build_generated_product_code


class Command(BaseCommand):
    help = "Load the catalog seed fixture only when the catalog is empty."

    def handle(self, *args, **options):
        if Cake.objects.exists() or Package.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Catalog seed skipped because cake/package data already exists."
            ))
            return

        call_command('loaddata', 'catalog_seed',
                     verbosity=options.get('verbosity', 1))

        updated_cakes = 0
        for cake_id in Cake.objects.filter(
            Q(product_code__isnull=True) | Q(product_code='')
        ).values_list('id', flat=True):
            Cake.objects.filter(pk=cake_id).update(
                product_code=_build_generated_product_code('CK', cake_id)
            )
            updated_cakes += 1

        updated_packages = 0
        for package_id in Package.objects.filter(
            Q(product_code__isnull=True) | Q(product_code='')
        ).values_list('id', flat=True):
            Package.objects.filter(pk=package_id).update(
                product_code=_build_generated_product_code('PKG', package_id)
            )
            updated_packages += 1

        self.stdout.write(self.style.SUCCESS(
            f"Catalog seed loaded. Assigned product codes to {updated_cakes} cakes and {updated_packages} packages."
        ))
