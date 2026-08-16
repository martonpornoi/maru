"""Close default PUBLIC execution of application integrity functions."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
REVOKE ALL ON FUNCTION public.maru_applications_guard_definition() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_guard_definition_child() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_guard_submission() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_guard_answer() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_guard_review() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_guard_target() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_applications_append_only() FROM PUBLIC;
"""

REVERSE_SQL = r"""
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_definition() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_definition_child() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_submission() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_answer() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_review() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_guard_target() TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.maru_applications_append_only() TO PUBLIC;
"""


class Migration(migrations.Migration):
    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0002_integrity_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
