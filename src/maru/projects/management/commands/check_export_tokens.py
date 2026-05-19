from __future__ import annotations

from django.core.management.base import BaseCommand

from maru.projects.models import ExportAccessLog, ExportToken


class Command(BaseCommand):
    help = "Report export token health without printing raw token values."

    def add_arguments(self, parser):
        parser.add_argument(
            "--project",
            help="Limit output to one project slug.",
        )

    def handle(self, *args, **options):
        tokens = ExportToken.objects.select_related("project").order_by(
            "project__slug",
            "export_type",
            "name",
        )
        if options["project"]:
            tokens = tokens.filter(project__slug=options["project"])

        if not tokens.exists():
            self.stdout.write("No export tokens found.")
            return

        for token in tokens:
            logs = ExportAccessLog.objects.filter(export_token=token)
            last_success = logs.filter(success=True).order_by("-created_at").first()
            failed_count = logs.filter(success=False).count()
            status = "active" if token.active else "inactive"
            success_text = (
                last_success.created_at.isoformat(timespec="seconds")
                if last_success
                else "never"
            )
            self.stdout.write(
                " | ".join(
                    [
                        f"project={token.project.slug}",
                        f"name={token.name}",
                        f"type={token.export_type}",
                        f"status={status}",
                        f"last_success={success_text}",
                        f"failed_requests={failed_count}",
                    ]
                )
            )
