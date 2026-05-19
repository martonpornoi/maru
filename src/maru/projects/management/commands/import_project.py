from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from maru.project_import import ProjectImportError, load_project_yaml
from maru.projects.importer import ProjectSetupImportError, import_project_setup


class Command(BaseCommand):
    help = "Import or update a maru project setup from YAML."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the project YAML file.")

    def handle(self, *args, **options):
        try:
            config = load_project_yaml(options["path"])
            result = import_project_setup(config)
        except (OSError, ProjectImportError, ProjectSetupImportError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {result.project.slug}: "
                f"{result.accounts} accounts, "
                f"{result.hotels} hotels, "
                f"{result.rooms} rooms, "
                f"{result.room_combinations} room combinations, "
                f"{result.event_groups} event groups, "
                f"{result.subprojects} subprojects, "
                f"{result.form_fields} form fields"
            )
        )
