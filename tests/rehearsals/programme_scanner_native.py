"""Host-only real daemon preparation proof; not collected or run while deferred."""

import hashlib
import time
from uuid import uuid4

import pytest
from django.test import override_settings

from maru.applications.programme_file_preparation import prepare_programme_pdf
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)
from tests.rehearsals.programme_scanner import isolated_programme_scanner

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


def test_native_real_scanner_prepares_exact_synthetic_bytes_and_cleans_owned_resources(
    monkeypatch,
):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "600")
    # The public preparer promises envelope + real scan, not full PDF validity.
    data = b"%PDF-1.7\nSynthetic scanner acceptance only.\n%%EOF\n"
    with isolated_programme_scanner(deadline=time.monotonic() + 600.0) as scanner:
        with override_settings(
            MARU_PROGRAMME_FILE_SCANNER="clamav",
            MARU_PROGRAMME_FILE_SCANNER_HOST="127.0.0.1",
            MARU_PROGRAMME_FILE_SCANNER_PORT=scanner.port,
            MARU_PROGRAMME_FILE_SCANNER_TIMEOUT_SECONDS=5.0,
        ):
            prepared = prepare_programme_pdf(data=data)
        assert prepared.data == data
        assert prepared.sha256 == hashlib.sha256(data).hexdigest()
        assert prepared.scanner_code == "clamav-instream@1"
        assert scanner.engine_version == "1.5.4"
        assert scanner.signature_version > 0
    # Context exit verifies exact container/network removal; no cleanup-by-name
    # of unrelated resources and no durable host file/signature volume existed.
