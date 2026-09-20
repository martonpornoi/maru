"""Real restricted-runtime restored-release reads, denial, withdrawal and replay."""

import json
import sys
from dataclasses import replace
from uuid import uuid4

from tests.rehearsals.programme_change_scenario import (
    change_from_document,
    change_sources,
)
from tests.rehearsals.programme_release_preparation import _manifest, _require
from tests.rehearsals.programme_restore_authority import (
    verify_restored_authority_revocation,
)
from tests.rehearsals.programme_runtime_environment import (
    require_programme_runtime_environment,
)


def verify_restored_release(document):
    require_programme_runtime_environment()
    _require(set(document) == {"sources", "change"}, "restore_input_invalid")
    setup, proposal, _, _, planning, _, staffing, release = change_sources(
        document["sources"]
    )
    change_from_document(
        document["change"], setup=setup, staffing=staffing, release=release
    )
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        _require_native_readiness,
        build_candidate_application,
    )

    build_candidate_application()
    from maru.programme.models import ProgrammeItem  # noqa: PLC0415
    from maru.programme.public_copy_commands import (  # noqa: PLC0415
        withdraw_programme_public_rendition,
    )
    from maru.scheduling.authorization import (  # noqa: PLC0415
        SchedulingAuthorizationDeniedError,
    )
    from maru.scheduling.models import (  # noqa: PLC0415
        SchedulingReleaseArtifact,
        SchedulingReleaseDependencyChange,
    )

    before = _manifest(setup, planning.planner)
    _require(
        before.state == "available"
        and before.pointer_version == 4
        and len(before.selections) == 3
        and before.is_active,
        "restore_current_release_missing",
    )
    try:
        _manifest(setup, proposal.lead)
    except SchedulingAuthorizationDeniedError:
        pass
    else:
        raise RuntimeError("restore_unauthorized_private_release_read")
    artifact = SchedulingReleaseArtifact.objects.get(release_id=before.release_id)
    original = bytes(artifact.payload)
    selection = before.selections[0]
    item = ProgrammeItem.objects.get(
        public_renditions__id=selection.public_rendition_id,
        organization_id=setup.organization_id,
        edition_id=setup.edition_id,
    )
    arguments = {
        "actor_id": planning.planner.authenticate().id,
        "organization_id": setup.organization_id,
        "edition_id": setup.edition_id,
        "item_id": item.id,
        "rendition_id": selection.public_rendition_id,
        "expected_version": item.aggregate_version,
        "reason": "Synthetic logical-recovery disclosure withdrawal.",
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "programme_rehearsal",
    }
    result = withdraw_programme_public_rendition(**arguments)
    _require(
        withdraw_programme_public_rendition(**arguments)
        == replace(result, replayed=True),
        "restore_withdrawal_retry_changed",
    )
    after = _manifest(setup, planning.planner)
    _require(
        after.state == "invalidated"
        and not after.selections
        and after.is_active
        and after.pointer_version == before.pointer_version
        and after.release_id == before.release_id,
        "restore_disclosure_not_invalidated",
    )
    _require(
        SchedulingReleaseDependencyChange.objects.filter(
            dependency__kind="programme_public_copy",
            dependency__source_id=selection.public_rendition_id,
        ).count()
        == 1,
        "restore_journal_missing",
    )
    _require(
        bytes(SchedulingReleaseArtifact.objects.get(id=artifact.id).payload)
        == original,
        "restore_original_artifact_changed",
    )
    verify_restored_authority_revocation(setup, planning)
    _require_native_readiness(require_programme_runtime_environment())


def _main():
    try:
        raw = sys.stdin.buffer.read(131_073)
        _require(len(raw) <= 131_072, "restore_input_too_large")
        verify_restored_release(json.loads(raw))
    except Exception:  # noqa: BLE001 - private child never prints data or credentials.
        return 2
    sys.stdout.write("programme-logical-restore-verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
