from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.identity.models import Account
from maru.registration import configuration_lifecycle as lifecycle
from maru.registration.models import (
    ConfigurationStatus,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationProvenanceStatus,
    RegistrationSetupCommandReceipt,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupDependencyError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
)
from maru.registration.template_lifecycle import RegistrationTemplateStateConflictError

ORG = UUID(int=1)
SERIES = UUID(int=2)
EDITION = UUID(int=3)
CONFIGURATION = UUID(int=4)
ACTOR = UUID(int=5)


class _Query:
    def __init__(
        self,
        *,
        result: object = None,
        rows: tuple[object, ...] = (),
        exists: bool | None = None,
    ) -> None:
        self.result = result
        self.rows = rows
        self.exists_result = bool(result) if exists is None else exists

    def select_for_update(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def select_related(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def filter(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def exclude(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def values_list(self, *_args: object, **_kwargs: object) -> _Query:
        return self

    def distinct(self) -> _Query:
        return self

    def first(self) -> object:
        return self.result

    def exists(self) -> bool:
        return self.exists_result

    def __getitem__(self, item: int | slice) -> object:
        return self.rows[item]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rows)


def _scope(
    *,
    origin: str = RegistrationSetupOrigin.BLANK,
    status: str = ConfigurationStatus.DRAFT,
) -> SimpleNamespace:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    configuration = SimpleNamespace(
        id=CONFIGURATION,
        origin=origin,
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
        status=status,
        version=1,
        last_changed_in_setup_version=2,
        review_required=False,
        review_note="Reviewed configuration.",
        activated_at=now,
        source_template_id=None,
        source_edition_id=None,
        source_configuration_id=None,
        source_version=None,
        source_content_digest="",
        source_imported_at=None,
        source_imported_by_id=None,
        created_in_setup_version=1,
        content_digest="a" * 64,
    )
    return SimpleNamespace(
        organization=SimpleNamespace(id=ORG, lifecycle="active"),
        series=SimpleNamespace(id=SERIES),
        edition=SimpleNamespace(
            id=EDITION,
            name="Maru 2026",
            lifecycle="preparing",
            currency_codes=("EUR",),
        ),
        actor=SimpleNamespace(id=ACTOR),
        control=SimpleNamespace(
            id=UUID(int=6),
            origin=origin,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            aggregate_version=3,
        ),
        configuration=configuration,
        sections=(),
        questions=(),
        products=(),
        minor_policy=None,
        active_capacity_codes=frozenset(),
        decision=SimpleNamespace(reason_code="allowed", obligations=frozenset()),
        evaluated_at=now,
    )


def _field_code(error: ValidationError) -> str | None:
    if hasattr(error, "error_dict"):
        return next(iter(error.error_dict.values()))[0].code
    return error.error_list[0].code


@pytest.mark.parametrize(
    ("function", "value", "kwargs", "code"),
    [
        (
            lifecycle._strict_uuid,
            "not-a-uuid",
            {"field": "configuration_id"},
            "registration_setup_uuid_invalid",
        ),
        (
            lifecycle._expected_version,
            True,
            {},
            "registration_setup_expected_version_invalid",
        ),
        (
            lifecycle._expected_version,
            0,
            {},
            "registration_setup_expected_version_invalid",
        ),
        (
            lifecycle._source_channel,
            "Invalid Channel",
            {},
            "registration_setup_source_channel_invalid",
        ),
        (
            lifecycle._content_digest,
            "A" * 64,
            {},
            "registration_setup_content_digest_invalid",
        ),
        (
            lifecycle._confirmation,
            "edition\u0000",
            {},
            "registration_setup_edition_confirmation_invalid",
        ),
    ],
)
def test_lifecycle_scalar_inputs_reject_ambiguous_or_noncanonical_values(
    function: Any,
    value: object,
    kwargs: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        function(value, **kwargs)
    assert _field_code(raised.value) == code


@pytest.mark.parametrize(
    ("value", "required", "maximum", "code"),
    [
        (7, False, 20, "registration_setup_text_invalid"),
        ("   ", True, 20, "registration_setup_text_required"),
        ("line\u0000", False, 20, "registration_setup_text_invalid"),
        ("x" * 21, False, 20, "registration_setup_text_too_long"),
    ],
)
def test_lifecycle_text_normalization_rejects_hidden_and_unbounded_content(
    value: object,
    required: bool,
    maximum: int,
    code: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        lifecycle._normalized_text(
            value,
            field="reason",
            maximum=maximum,
            required=required,
        )
    assert _field_code(raised.value) == code


def test_lifecycle_text_normalization_is_unicode_stable_and_space_bounded() -> None:
    assert (
        lifecycle._normalized_text(
            "  Review   the cafe\u0301 setup  ",
            field="reason",
            maximum=80,
            required=True,
        )
        == "Review the caf\u00e9 setup"
    )


def test_bounded_query_rejects_one_row_beyond_the_declared_limit() -> None:
    assert lifecycle._bounded(_Query(rows=(1, 2)), limit=2) == (1, 2)
    with pytest.raises(RegistrationSetupLimitExceededError):
        lifecycle._bounded(_Query(rows=(1, 2, 3)), limit=2)


def test_authorization_rejects_unpersisted_actor_and_unresolved_exact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        lifecycle._authorize_scope(
            actor=Account(id=None),
            organization_id=ORG,
            series_id=SERIES,
            edition_id=EDITION,
        )

    actor = Account(id=ACTOR)
    monkeypatch.setattr(
        lifecycle.EventEdition.objects,
        "filter",
        lambda **_kwargs: _Query(exists=True),
    )
    monkeypatch.setattr(lifecycle, "resolve_edition_target", lambda **_kwargs: None)
    with pytest.raises(RegistrationSetupAuthorizationDeniedError):
        lifecycle._authorize_scope(
            actor=actor,
            organization_id=ORG,
            series_id=SERIES,
            edition_id=EDITION,
        )


def _install_lock_queries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing: str | None,
    orphan_question: bool = False,
    capacity_overflow: bool = False,
) -> None:
    organization = None if missing == "organization" else SimpleNamespace(id=ORG)
    series = None if missing == "series" else SimpleNamespace(id=SERIES)
    edition = None if missing == "edition" else SimpleNamespace(id=EDITION)
    control = None if missing == "control" else SimpleNamespace(id=UUID(int=10))
    actor = None if missing == "actor" else SimpleNamespace(id=ACTOR, pk=ACTOR)
    configuration = (
        None if missing == "configuration" else SimpleNamespace(id=CONFIGURATION)
    )
    managers = (
        (lifecycle.Organization.objects, _Query(result=organization)),
        (lifecycle.ConventionSeries.objects, _Query(result=series)),
        (lifecycle.EventEdition.objects, _Query(result=edition)),
        (lifecycle.RegistrationSetupControl.objects, _Query(result=control)),
        (lifecycle.Account.objects, _Query(result=actor)),
        (
            lifecycle.RegistrationConfiguration.objects,
            _Query(result=configuration),
        ),
        (lifecycle.RegistrationSection.objects, _Query(rows=())),
        (
            lifecycle.RegistrationQuestion.objects,
            _Query(
                rows=(
                    SimpleNamespace(
                        section_id=UUID(int=99),
                        section=None,
                    ),
                )
                if orphan_question
                else ()
            ),
        ),
        (lifecycle.AdmissionProduct.objects, _Query(rows=())),
        (lifecycle.MinorRegistrationPolicy.objects, _Query(result=None)),
    )
    for manager, query in managers:
        monkeypatch.setattr(
            manager,
            "select_for_update",
            lambda query=query: query,
        )
    capacity_rows: tuple[object, ...] = (
        tuple(f"capacity-{index}" for index in range(lifecycle.MAX_CAPACITY_CODES + 1))
        if capacity_overflow
        else ()
    )
    monkeypatch.setattr(
        lifecycle.ParticipationCapacity.objects,
        "filter",
        lambda **_kwargs: _Query(rows=capacity_rows),
    )
    monkeypatch.setattr(
        lifecycle,
        "_authorize_scope",
        lambda **_kwargs: SimpleNamespace(
            allowed=True,
            reason_code="allowed",
            obligations=frozenset(),
        ),
    )


@pytest.mark.parametrize(
    ("missing", "error"),
    [
        ("organization", RegistrationSetupAuthorizationDeniedError),
        ("series", RegistrationSetupAuthorizationDeniedError),
        ("edition", RegistrationSetupAuthorizationDeniedError),
        ("control", RegistrationSetupStateConflictError),
        ("actor", RegistrationSetupAuthorizationDeniedError),
        ("configuration", RegistrationSetupStateConflictError),
    ],
)
def test_locked_scope_fails_closed_at_every_exact_ownership_boundary(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    error: type[Exception],
) -> None:
    _install_lock_queries(monkeypatch, missing=missing)
    with pytest.raises(error):
        lifecycle._lock_scope(
            actor=Account(id=ACTOR),
            organization_id=ORG,
            series_id=SERIES,
            edition_id=EDITION,
            configuration_id=CONFIGURATION,
        )


def test_locked_scope_rejects_orphan_question_and_capacity_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_lock_queries(monkeypatch, missing=None, orphan_question=True)
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._lock_scope(
            actor=Account(id=ACTOR),
            organization_id=ORG,
            series_id=SERIES,
            edition_id=EDITION,
            configuration_id=CONFIGURATION,
        )

    _install_lock_queries(monkeypatch, missing=None, capacity_overflow=True)
    with pytest.raises(RegistrationSetupLimitExceededError):
        lifecycle._lock_scope(
            actor=Account(id=ACTOR),
            organization_id=ORG,
            series_id=SERIES,
            edition_id=EDITION,
            configuration_id=CONFIGURATION,
        )


def test_original_source_binding_requires_creation_receipt_target_and_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(origin=RegistrationSetupOrigin.PRIOR_EDITION)
    configuration = scope.configuration
    configuration.created_in_setup_version = None
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_original_source_binding(
            configuration=configuration,
            control=scope.control,
            organization=scope.organization,
            edition=scope.edition,
        )

    configuration.created_in_setup_version = 1
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "filter",
        lambda **_kwargs: _Query(result=None),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_original_source_binding(
            configuration=configuration,
            control=scope.control,
            organization=scope.organization,
            edition=scope.edition,
        )

    receipt = SimpleNamespace(
        actor_id=UUID(int=90),
        targets=_Query(rows=()),
    )
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "filter",
        lambda **_kwargs: _Query(result=receipt),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_original_source_binding(
            configuration=configuration,
            control=scope.control,
            organization=scope.organization,
            edition=scope.edition,
        )

    target = SimpleNamespace(
        target_schema_version=configuration.version,
        content_digest="source-binding",
    )
    receipt.targets = _Query(rows=(target,))
    monkeypatch.setattr(
        lifecycle,
        "configuration_source_binding_digest",
        lambda _configuration: "source-binding",
    )
    configuration.source_imported_by_id = UUID(int=91)
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_original_source_binding(
            configuration=configuration,
            control=scope.control,
            organization=scope.organization,
            edition=scope.edition,
        )


def test_original_source_binding_maps_invalid_start_graph_to_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(origin=RegistrationSetupOrigin.PRIOR_EDITION)
    configuration = scope.configuration
    configuration.created_in_setup_version = 1
    configuration.source_imported_by_id = ACTOR
    target = SimpleNamespace(
        target_schema_version=configuration.version,
        content_digest="source-binding",
    )
    receipt = SimpleNamespace(
        actor_id=ACTOR,
        targets=_Query(rows=(target,)),
    )
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "filter",
        lambda **_kwargs: _Query(result=receipt),
    )
    monkeypatch.setattr(
        lifecycle,
        "configuration_source_binding_digest",
        lambda _configuration: "source-binding",
    )
    monkeypatch.setattr(
        lifecycle,
        "_require_setup_start_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(RegistrationSetupStateConflictError()),
    )

    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_original_source_binding(
            configuration=configuration,
            control=scope.control,
            organization=scope.organization,
            edition=scope.edition,
        )


def _nonblank_source(scope: SimpleNamespace, origin: str) -> None:
    configuration = scope.configuration
    configuration.origin = origin
    scope.control.origin = origin
    configuration.source_version = 1
    configuration.source_content_digest = "f" * 64
    configuration.source_imported_at = scope.evaluated_at
    configuration.source_imported_by_id = ACTOR


@pytest.mark.parametrize(
    "mutate",
    [
        lambda scope: setattr(
            scope.control,
            "provenance_status",
            RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        ),
        lambda scope: setattr(scope.configuration, "source_version", 1),
        lambda scope: _nonblank_source(
            scope,
            RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        ),
        lambda scope: (
            _nonblank_source(scope, RegistrationSetupOrigin.PUBLISHED_TEMPLATE),
            setattr(scope.configuration, "source_edition_id", EDITION),
        ),
        lambda scope: _nonblank_source(
            scope,
            RegistrationSetupOrigin.PLATFORM_STARTER,
        ),
        lambda scope: _nonblank_source(
            scope,
            RegistrationSetupOrigin.PRIOR_EDITION,
        ),
    ],
)
def test_exact_source_digest_rejects_incomplete_or_ambiguous_provenance(
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
) -> None:
    scope = _scope()
    monkeypatch.setattr(
        lifecycle,
        "_require_original_source_binding",
        lambda **_kwargs: None,
    )
    mutate(scope)
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)


def test_template_source_digest_rejects_missing_stale_and_unproven_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(origin=RegistrationSetupOrigin.PUBLISHED_TEMPLATE)
    _nonblank_source(scope, RegistrationSetupOrigin.PUBLISHED_TEMPLATE)
    scope.configuration.source_template_id = UUID(int=20)
    monkeypatch.setattr(
        lifecycle,
        "_require_original_source_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle.RegistrationTemplate.objects,
        "filter",
        lambda **_kwargs: _Query(result=None),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    template = SimpleNamespace(
        provenance_status=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
        created_in_catalog_version=1,
        last_changed_in_catalog_version=1,
        version=1,
        content_digest="f" * 64,
    )
    monkeypatch.setattr(
        lifecycle.RegistrationTemplate.objects,
        "filter",
        lambda **_kwargs: _Query(result=template),
    )
    monkeypatch.setattr(lifecycle, "_template_source_digest", lambda _value: "f" * 64)
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    template.provenance_status = RegistrationProvenanceStatus.COMPLETE
    monkeypatch.setattr(
        lifecycle,
        "require_published_template_evidence",
        lambda _value: (_ for _ in ()).throw(RegistrationTemplateStateConflictError()),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)


def test_copied_source_digest_rejects_missing_wrong_edition_and_stale_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(origin=RegistrationSetupOrigin.PRIOR_EDITION)
    _nonblank_source(scope, RegistrationSetupOrigin.PRIOR_EDITION)
    scope.configuration.source_configuration_id = UUID(int=30)
    scope.configuration.source_edition_id = UUID(int=31)
    monkeypatch.setattr(
        lifecycle,
        "_require_original_source_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        lifecycle.RegistrationConfiguration.objects,
        "select_related",
        lambda *_args: _Query(result=None),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    source = SimpleNamespace(
        id=UUID(int=30),
        edition_id=EDITION,
        edition=SimpleNamespace(id=EDITION, series=scope.series),
        origin=RegistrationSetupOrigin.BLANK,
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
        created_in_setup_version=1,
        last_changed_in_setup_version=2,
        version=1,
        content_digest="f" * 64,
    )
    monkeypatch.setattr(
        lifecycle.RegistrationConfiguration.objects,
        "select_related",
        lambda *_args: _Query(result=source),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    source.edition_id = UUID(int=31)
    source.edition = SimpleNamespace(id=UUID(int=31), series=scope.series)
    monkeypatch.setattr(
        lifecycle.RegistrationSetupControl.objects,
        "filter",
        lambda **_kwargs: _Query(result=None),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    source_control = SimpleNamespace(id=UUID(int=32))
    monkeypatch.setattr(
        lifecycle.RegistrationSetupControl.objects,
        "filter",
        lambda **_kwargs: _Query(result=source_control),
    )
    monkeypatch.setattr(
        lifecycle,
        "_configuration_source_digest",
        lambda _value: "e" * 64,
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)


def test_nonblank_and_successor_sources_require_complete_exact_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(origin=RegistrationSetupOrigin.PUBLISHED_TEMPLATE)
    scope.configuration.source_version = 1
    monkeypatch.setattr(
        lifecycle,
        "_require_original_source_binding",
        lambda **_kwargs: None,
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(scope)

    successor = _scope(origin=RegistrationSetupOrigin.SUCCESSOR)
    _nonblank_source(successor, RegistrationSetupOrigin.SUCCESSOR)
    successor.configuration.source_configuration_id = UUID(int=40)
    successor.configuration.source_edition_id = UUID(int=41)
    source = SimpleNamespace(
        edition_id=UUID(int=41),
        edition=SimpleNamespace(id=UUID(int=41)),
    )
    monkeypatch.setattr(
        lifecycle.RegistrationConfiguration.objects,
        "select_related",
        lambda *_args: _Query(result=source),
    )
    with pytest.raises(RegistrationSetupDependencyError):
        lifecycle._require_exact_source_digest(successor)


def test_validation_helpers_preserve_codes_and_fail_closed_on_missing_policy_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert lifecycle._validation_codes(
        ValidationError("Invalid", code="specific_code")
    ) == ("specific_code",)
    model = SimpleNamespace(
        full_clean=lambda: (_ for _ in ()).throw(
            ValidationError("Invalid", code="model_invalid")
        )
    )
    issues = lifecycle._model_issues(
        model,
        target_kind="configuration",
        target_key="configuration",
    )
    assert issues == [
        lifecycle.RegistrationConfigurationIssue(
            "model_invalid",
            "configuration",
            "configuration",
        )
    ]

    monkeypatch.setattr(lifecycle, "minor_policy_payload", lambda _policy: None)
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._minor_policy_target_digest(SimpleNamespace())


def test_minor_policy_evidence_requires_receipt_action_and_exact_target_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    policy = SimpleNamespace(
        id=UUID(int=50),
        configuration_id=CONFIGURATION,
        reviewed_by_id=ACTOR,
        reviewed_at=scope.evaluated_at,
        last_changed_in_setup_version=1,
        created_in_setup_version=1,
        enabled=True,
        minor_age_threshold=18,
        guardian_notice_version="guardian-v1",
        jurisdiction_code="HU",
        review_reference="LEGAL-1",
    )
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "select_for_update",
        lambda: _Query(result=None),
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._require_minor_policy_review_evidence(scope=scope, policy=policy)

    receipt = SimpleNamespace(
        action=RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED,
        actor_id=UUID(int=51),
        request_digest="a" * 64,
        resulting_version=1,
        reason="Review policy.",
        targets=_Query(rows=()),
    )
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "select_for_update",
        lambda: _Query(result=receipt),
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._require_minor_policy_review_evidence(scope=scope, policy=policy)

    receipt.actor_id = ACTOR
    receipt.request_digest = lifecycle._minor_policy_request_digest(
        scope=scope,
        receipt=receipt,
        policy=policy,
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._require_minor_policy_review_evidence(scope=scope, policy=policy)


def test_minor_policy_request_digest_rejects_unrelated_receipt_action() -> None:
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._minor_policy_request_digest(
            scope=_scope(),
            receipt=SimpleNamespace(action="unrelated"),
            policy=SimpleNamespace(),
        )


def test_configuration_issues_report_multiple_operator_actionable_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    scope = _scope()
    scope.configuration.opens_at = now.replace(tzinfo=None)
    scope.configuration.closes_at = (now + timedelta(days=20)).replace(tzinfo=None)
    scope.configuration.currency = "USD"
    scope.configuration.waitlist_enabled = False
    scope.configuration.automatic_waitlist_promotion = True
    scope.configuration.default_payment_window_minutes = 0
    scope.configuration.minimum_age = 10
    scope.configuration.capacity = 10
    source = SimpleNamespace(
        key="staff_gate",
        position=1,
        help_text="",
        condition_question_key="",
        visibility=QuestionVisibility.REGISTRATION_STAFF,
        field_type=QuestionFieldType.SINGLE_CHOICE,
        options=["yes", "no"],
    )
    dependent = SimpleNamespace(
        key="attendee_detail",
        position=2,
        help_text="x" * (lifecycle.MAX_QUESTION_HELP_LENGTH + 1),
        condition_question_key="staff_gate",
        condition_value="unavailable",
        visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
    )
    missing_source = SimpleNamespace(
        key="orphan",
        position=3,
        help_text="",
        condition_question_key="missing",
        condition_value="true",
        visibility=QuestionVisibility.ATTENDEE_AND_STAFF,
    )
    scope.questions = (source, dependent, missing_source)
    monkeypatch.setattr(lifecycle, "_model_issues", lambda *_args, **_kwargs: [])

    codes = {issue.code for issue in lifecycle._configuration_issues(scope)}

    assert {
        "registration_setup_period_timezone_invalid",
        "registration_setup_currency_invalid",
        "registration_setup_waitlist_invalid",
        "registration_setup_payment_window_invalid",
        "registration_question_help_too_long",
        "registration_condition_visibility_incompatible",
        "registration_condition_value_incompatible",
        "registration_condition_source_not_prior",
        "registration_products_required",
        "minor_policy_required",
    } <= codes
    assert now.tzinfo is UTC


def test_configuration_issues_bound_product_period_and_capacity_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    scope = _scope()
    scope.configuration.opens_at = now
    scope.configuration.closes_at = now + timedelta(days=10)
    scope.configuration.currency = "EUR"
    scope.configuration.waitlist_enabled = True
    scope.configuration.automatic_waitlist_promotion = True
    scope.configuration.default_payment_window_minutes = 60
    scope.configuration.minimum_age = 18
    scope.configuration.capacity = 100
    product = SimpleNamespace(
        code="late",
        description="",
        sales_open_at=now,
        sales_close_at=now + timedelta(days=11),
        capacity=10,
        waitlist_enabled=True,
        payment_window_minutes=60,
        required_capacity_codes=[],
    )
    scope.products = (product,)
    monkeypatch.setattr(lifecycle, "_model_issues", lambda *_args, **_kwargs: [])

    assert "product_sales_after_registration" in {
        issue.code for issue in lifecycle._configuration_issues(scope)
    }


def test_configuration_command_digest_distinguishes_lifecycle_actions() -> None:
    scope = _scope()
    reviewed = SimpleNamespace(
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
        actor_id=ACTOR,
        resulting_version=2,
        reason="Review configuration.",
    )
    activated = SimpleNamespace(
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
        actor_id=ACTOR,
        resulting_version=3,
        reason="Activate configuration.",
    )
    assert lifecycle._configuration_command_request_digest(
        scope=scope,
        receipt=reviewed,
        content_digest="a" * 64,
    ) != lifecycle._configuration_command_request_digest(
        scope=scope,
        receipt=activated,
        content_digest="a" * 64,
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._configuration_command_request_digest(
            scope=scope,
            receipt=SimpleNamespace(
                action="unknown",
                actor_id=ACTOR,
                resulting_version=3,
                reason="Unknown action.",
            ),
            content_digest="a" * 64,
        )


def test_configuration_evidence_rejects_unknown_action_and_timestamp_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._require_configuration_command_evidence(
            scope=scope,
            receipt=SimpleNamespace(
                action="unknown",
                request_digest="a" * 64,
            ),
            content_digest="a" * 64,
        )

    activation = SimpleNamespace(
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
        request_digest="a" * 64,
    )
    monkeypatch.setattr(
        lifecycle,
        "require_setup_command_evidence_graph",
        lambda **_kwargs: SimpleNamespace(
            occurred_at=scope.configuration.activated_at + timedelta(seconds=1)
        ),
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._require_configuration_command_evidence(
            scope=scope,
            receipt=activation,
            content_digest="a" * 64,
        )


def test_review_resolution_fails_closed_for_missing_versions_receipts_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(status=ConfigurationStatus.DRAFT)
    scope.configuration.last_changed_in_setup_version = 0
    assert lifecycle._review_resolved(scope, "a" * 64) is False

    scope.configuration.status = ConfigurationStatus.RETIRED
    scope.configuration.last_changed_in_setup_version = 2
    assert lifecycle._review_resolved(scope, "a" * 64) is False

    scope.configuration.status = ConfigurationStatus.ACTIVE
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "filter",
        lambda **_kwargs: _Query(result=None),
    )
    assert lifecycle._review_resolved(scope, "a" * 64) is False

    activation = SimpleNamespace(action="activation")
    review = SimpleNamespace(action="review")
    monkeypatch.setattr(
        lifecycle.RegistrationSetupCommandReceipt.objects,
        "filter",
        lambda **kwargs: _Query(
            result=(
                activation
                if kwargs["action"]
                == RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED
                else review
            )
        ),
    )
    monkeypatch.setattr(
        lifecycle,
        "_require_configuration_command_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(RegistrationSetupStateConflictError()),
    )
    assert lifecycle._review_resolved(scope, "a" * 64) is False


def test_replayed_result_maps_version_and_evidence_failures_to_closed_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(status=ConfigurationStatus.DRAFT)
    receipt = SimpleNamespace(
        id=UUID(int=40),
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
        request_digest="b" * 64,
        resulting_version=2,
    )
    monkeypatch.setattr(
        lifecycle,
        "_require_exact_configuration_digest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RegistrationSetupVersionConflictError()
        ),
    )
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._result_from_receipt(
            scope=scope,
            receipt=receipt,
            action=receipt.action,
            request_digest=receipt.request_digest,
            content_digest="a" * 64,
        )

    monkeypatch.setattr(
        lifecycle,
        "_require_exact_configuration_digest",
        lambda *_args, **_kwargs: "a" * 64,
    )
    monkeypatch.setattr(lifecycle, "_require_exact_source_digest", lambda _scope: None)
    monkeypatch.setattr(
        lifecycle,
        "_require_configuration_command_evidence",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(lifecycle, "_review_resolved", lambda *_args: False)
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._result_from_receipt(
            scope=scope,
            receipt=receipt,
            action=receipt.action,
            request_digest=receipt.request_digest,
            content_digest="a" * 64,
        )

    monkeypatch.setattr(lifecycle, "_review_resolved", lambda *_args: True)
    scope.configuration.last_changed_in_setup_version = 99
    with pytest.raises(RegistrationSetupStateConflictError):
        lifecycle._result_from_receipt(
            scope=scope,
            receipt=receipt,
            action=receipt.action,
            request_digest=receipt.request_digest,
            content_digest="a" * 64,
        )


def test_editable_draft_and_version_fences_reject_stale_or_closed_scope() -> None:
    scope = _scope()
    lifecycle._require_editable_draft(scope)
    assert lifecycle._require_current_version(scope, 3) == 3

    scope.edition.lifecycle = "archived"
    with pytest.raises(lifecycle.RegistrationSetupLifecycleConflictError):
        lifecycle._require_editable_draft(scope)
    with pytest.raises(RegistrationSetupVersionConflictError):
        lifecycle._require_current_version(scope, 2)
