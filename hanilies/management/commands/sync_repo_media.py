from pathlib import Path
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Copy committed media files from the repository into MEDIA_ROOT."

    def handle(self, *args, **options):
        source_root = Path(settings.BASE_DIR) / 'media'
        destination_root = Path(settings.MEDIA_ROOT)

        if not source_root.exists():
            self.stdout.write(self.style.WARNING(
                f"Source media directory does not exist: {source_root}"
            ))
            return

        if source_root.resolve() == destination_root.resolve():
            self.stdout.write("Repository media and MEDIA_ROOT are the same path; nothing to sync.")
            return

        copied_count = 0
        for source_path in source_root.rglob('*'):
            if not source_path.is_file():
                continue

            relative_path = source_path.relative_to(source_root)
            destination_path = destination_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)

            if destination_path.exists():
                source_stat = source_path.stat()
                destination_stat = destination_path.stat()
                if (
                    source_stat.st_size == destination_stat.st_size
                    and int(source_stat.st_mtime) <= int(destination_stat.st_mtime)
                ):
                    continue

            shutil.copy2(source_path, destination_path)
            copied_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Synced {copied_count} media file(s) into {destination_root}"
        ))