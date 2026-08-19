from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.test import RequestFactory
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.registration import api
from maru.registration.profile_extension_values import (
    ProfileExtensionValueError,
    ProfileExtensionValueEvidenceConflictError,
    ProfileExtensionValueLimitExceededError,
    ProfileExtensionValueRetryConflictError,
    ProfileExtensionValueSequenceConflictError,
    ProfileExtensionValueUnavailableError,
)


class StubInputSerializer:
    validated_template: ClassVar[dict[str, object]] = {
        "target_product_id": UUID(int=10),
        "expected_registration_version": 3,
        "product_id": UUID(int=11),
        "new_capacity": 200,
        "batch_size": 25,
        "reason": "Exercise the governed commerce API command.",
        "expected_control_version": 4,
    }

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.validated_data = dict(self.validated_template)

    def is_valid(self, **_kwargs: object) -> bool:
        return True


class StubOutputSerializer:
    def __init__(
        self, instance: object = None, *_args: object, **_kwargs: object
    ) -> None:
        self.data = instance if isinstance(instance, dict) else {"id": instance.id}


def _request(*, idempotency_key: str | None = None) -> SimpleNamespace:
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return SimpleNamespace(
        user=Account(id=UUID(int=1)),
        data={},
        headers=headers,
        correlation_id=str(UUID(int=9)),
        _request=RequestFactory().post("/api/registration/"),
    )


def _authorization_error() -> AuthorizationDenied:
    return AuthorizationDenied("Synthetic denial.", reason_code="permission_absent")


def _raise(error: Exception):  # type: ignore[no-untyped-def]
    def raiser(*_args: object, **_kwargs: object) -> None:
        raise error

    return raiser


def test_account_boundary_requires_a_platform_account_instance() -> None:
    account = Account(id=UUID(int=1))
    assert api._account(SimpleNamespace(user=account)) is account
    with pytest.raises(TypeError):
        api._account(SimpleNamespace(user=SimpleNamespace(id=UUID(int=1))))


def test_step_up_is_optional_and_maps_stale_authentication_to_closed_api_error(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    request = _request()
    account = request.user
    settings.REQUIRE_PRIVILEGED_STEP_UP = False  # type: ignore[attr-defined]
    api._require_step_up(request, account)

    settings.REQUIRE_PRIVILEGED_STEP_UP = True  # type: ignore[attr-defined]
    monkeypatch.setattr(
        api,
        "require_recent_step_up",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValidationError("Expired", code="step_up_expired")
        ),
    )
    with pytest.raises(ApiValidationError) as raised:
        api._require_step_up(request, account)
    assert raised.value.detail["code"] == "step_up_expired"


def test_scope_decision_uses_exactly_one_owned_self_or_edition_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account(id=UUID(int=1))
    organization_id, edition_id = uuid4(), uuid4()
    targets: list[str] = []
    monkeypatch.setattr(
        api,
        "resolve_owned_target",
        lambda **_kwargs: targets.append("owned") or "owned-target",
    )
    monkeypatch.setattr(
        api,
        "resolve_self_target",
        lambda **_kwargs: targets.append("self") or "self-target",
    )
    monkeypatch.setattr(
        api,
        "resolve_edition_target",
        lambda **_kwargs: targets.append("edition") or "edition-target",
    )
    monkeypatch.setattr(
        api,
        "decide",
        lambda **kwargs: SimpleNamespace(allowed=True, resource=kwargs["resource"]),
    )
    with pytest.raises(ValueError, match="owning record"):
        api._scope_decision(
            account=account,
            capability_code="registration.view_service",
            organization_id=organization_id,
            edition_id=edition_id,
            owned_resource=SimpleNamespace(),
            self_intent=True,
        )

    assert (
        api._scope_decision(
            account=account,
            capability_code="registration.view_service",
            organization_id=organization_id,
            edition_id=edition_id,
            owned_resource=SimpleNamespace(),
        ).resource
        == "owned-target"
    )
    assert (
        api._scope_decision(
            account=account,
            capability_code="registration.view_service",
            organization_id=organization_id,
            edition_id=edition_id,
            self_intent=True,
        ).resource
        == "self-target"
    )
    assert (
        api._scope_decision(
            account=account,
            capability_code="registration.view_service",
            organization_id=organization_id,
            edition_id=edition_id,
        ).resource
        == "edition-target"
    )
    assert targets == ["owned", "self", "edition"]


@pytest.mark.parametrize(
    "raw_value",
    [
        None,
        "",
        " " + str(UUID(int=1)),
        "abcdefab-cdef-abcd-efab-cdefabcdefab".upper(),
        "not-a-uuid",
        "a" * 65,
    ],
)
def test_idempotency_header_requires_one_canonical_lowercase_uuid(
    raw_value: str | None,
) -> None:
    with pytest.raises(ApiValidationError):
        api._profile_extension_idempotency_key(_request(idempotency_key=raw_value))

    canonical = str(UUID(int=7))
    assert api._profile_extension_idempotency_key(
        _request(idempotency_key=canonical)
    ) == UUID(int=7)
    assert api._commerce_idempotency_key(_request(idempotency_key=canonical)) == UUID(
        int=7
    )


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (_authorization_error(), NotFound),
        (ProfileExtensionValueUnavailableError(), NotFound),
        (
            ProfileExtensionValueSequenceConflictError(),
            api.ProfileExtensionValueConflict,
        ),
        (ProfileExtensionValueRetryConflictError(), api.ProfileExtensionValueConflict),
        (ProfileExtensionValueLimitExceededError(), api.ProfileExtensionValueConflict),
        (ProfileExtensionValueEvidenceConflictError(), api.DependencyUnavailable),
        (ProfileExtensionValueError(), api.DependencyUnavailable),
        (RuntimeError(), RuntimeError),
    ],
)
def test_profile_extension_error_mapping_is_non_disclosing_and_closed(
    error: Exception,
    raised: type[Exception],
) -> None:
    with pytest.raises(raised):
        api._raise_profile_extension_error(error)


def _patch_commerce_action(
    monkeypatch: pytest.MonkeyPatch,
    *,
    action: str,
    command: object,
    authorize: object = None,
) -> None:
    monkeypatch.setattr(api, "_account", lambda _request: Account(id=UUID(int=1)))
    monkeypatch.setattr(
        api,
        "authorize_registration_commerce_edition_api_scope",
        authorize or (lambda **_kwargs: None),
    )
    monkeypatch.setattr(api, "_correlation_id", lambda _request: UUID(int=9))
    monkeypatch.setattr(api, "_commerce_idempotency_key", lambda _request: UUID(int=8))
    if action == "capacity":
        monkeypatch.setattr(
            api, "RegistrationCapacityAdjustmentCommandSerializer", StubInputSerializer
        )
        monkeypatch.setattr(
            api, "RegistrationCapacityAdjustmentResultSerializer", StubOutputSerializer
        )
        monkeypatch.setattr(api, "adjust_registration_capacity", command)
    else:
        monkeypatch.setattr(
            api, "WaitlistBatchOfferCommandSerializer", StubInputSerializer
        )
        monkeypatch.setattr(
            api, "WaitlistBatchOfferResultSerializer", StubOutputSerializer
        )
        monkeypatch.setattr(api, "offer_next_waitlist_batch", command)


def _invoke_commerce(action: str):  # type: ignore[no-untyped-def]
    view = (
        api.RegistrationCapacityAdjustmentView()
        if action == "capacity"
        else api.RegistrationWaitlistBatchOfferView()
    )
    return view.post(
        _request(idempotency_key=str(UUID(int=8))), UUID(int=2), UUID(int=3)
    )


@pytest.mark.parametrize("action", ["capacity", "waitlist"])
def test_commerce_actions_authorize_before_parsing_body(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    _patch_commerce_action(
        monkeypatch,
        action=action,
        command=lambda **_kwargs: None,
        authorize=_raise(_authorization_error()),
    )
    with pytest.raises(PermissionDenied) as raised:
        _invoke_commerce(action)
    assert raised.value.detail.code == "permission_absent"


@pytest.mark.parametrize("action", ["capacity", "waitlist"])
@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (_authorization_error(), PermissionDenied),
        (ObjectDoesNotExist(), NotFound),
        (ValidationError({"reason": ["Review reason."]}), ApiValidationError),
        (ValidationError("Invalid command."), ApiValidationError),
    ],
)
def test_commerce_actions_map_command_failures_without_partial_results(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    error: Exception,
    raised: type[Exception],
) -> None:
    _patch_commerce_action(monkeypatch, action=action, command=_raise(error))
    with pytest.raises(raised):
        _invoke_commerce(action)


@pytest.mark.parametrize("action", ["capacity", "waitlist"])
@pytest.mark.parametrize("replayed", [False, True])
def test_commerce_actions_return_explicit_new_or_replayed_receipts(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    replayed: bool,
) -> None:
    occurred_at = datetime(2027, 1, 2, tzinfo=UTC)
    if action == "capacity":
        domain_object = SimpleNamespace(
            id=UUID(int=20),
            scope="product",
            product_id=UUID(int=11),
            previous_capacity=100,
            new_capacity=200,
            hard_ceiling=250,
            occurred_at=occurred_at,
        )
        result = SimpleNamespace(
            adjustment=domain_object,
            control_version=5,
            replayed=replayed,
        )
    else:
        domain_object = SimpleNamespace(
            id=UUID(int=21),
            product_id=UUID(int=11),
            requested_size=25,
            offered_count=20,
            occurred_at=occurred_at,
        )
        result = SimpleNamespace(
            batch=domain_object,
            offered_registration_ids=(UUID(int=30),),
            control_version=5,
            replayed=replayed,
        )
    _patch_commerce_action(
        monkeypatch,
        action=action,
        command=lambda **_kwargs: result,
    )

    response = _invoke_commerce(action)

    assert response.status_code == (200 if replayed else 201)
    assert response["Idempotent-Replay"] == str(replayed).lower()
    assert response.data["control_version"] == 5


class FakeCountQuery:
    def __init__(self, *, count: int = 4) -> None:
        self.count_value = count

    def filter(self, **_kwargs: object) -> FakeCountQuery:
        return self

    def count(self) -> int:
        return self.count_value


class FakeConfigurationQuery:
    def __init__(self, configuration: object) -> None:
        self.configuration = configuration

    def prefetch_related(self, *_args: str) -> FakeConfigurationQuery:
        return self

    def get(self, **_kwargs: object) -> object:
        return self.configuration


class FakeControlQuery:
    def filter(self, **_kwargs: object) -> FakeControlQuery:
        return self

    def values_list(self, *_args: object, **_kwargs: object) -> FakeControlQuery:
        return self

    def first(self) -> int:
        return 7


def test_commerce_workspace_returns_bounded_capacity_and_activity_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = SimpleNamespace(id=UUID(int=11), name="Standard", capacity=100)
    configuration = SimpleNamespace(
        id=UUID(int=12),
        capacity=200,
        products=SimpleNamespace(all=lambda: (product,)),
    )
    monkeypatch.setattr(api, "_account", lambda _request: Account(id=UUID(int=1)))
    monkeypatch.setattr(api, "_correlation_id", lambda _request: UUID(int=9))
    monkeypatch.setattr(api, "registration_commerce_activity", lambda **_kwargs: ())
    monkeypatch.setattr(
        api.RegistrationConfiguration,
        "objects",
        FakeConfigurationQuery(configuration),
    )
    monkeypatch.setattr(api.Registration, "objects", FakeCountQuery())
    monkeypatch.setattr(
        api.RegistrationCommerceControl,
        "objects",
        FakeControlQuery(),
    )
    monkeypatch.setattr(api, "effective_configuration_capacity", lambda _item: 210)
    monkeypatch.setattr(api, "configuration_capacity_ceiling", lambda _item: 250)
    monkeypatch.setattr(api, "effective_product_capacity", lambda _item: 110)
    monkeypatch.setattr(api, "product_capacity_ceiling", lambda _item: 125)
    monkeypatch.setattr(api, "pending_target_capacity_holds", lambda _item: 3)

    response = api.RegistrationCommerceWorkspaceView().get(
        _request(), UUID(int=2), UUID(int=3)
    )

    assert response.status_code == 200
    assert response.data["control_version"] == 7
    assert response.data["capacities"][0]["effective_capacity"] == 210
    assert response.data["capacities"][1]["pending_target_holds"] == 3


@pytest.mark.parametrize(
    ("error", "raised"),
    [(_authorization_error(), PermissionDenied), (ObjectDoesNotExist(), NotFound)],
)
def test_commerce_workspace_maps_authority_and_configuration_absence(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(api, "_account", lambda _request: Account(id=UUID(int=1)))
    monkeypatch.setattr(api, "_correlation_id", lambda _request: UUID(int=9))
    monkeypatch.setattr(api, "registration_commerce_activity", _raise(error))
    with pytest.raises(raised):
        api.RegistrationCommerceWorkspaceView().get(
            _request(), UUID(int=2), UUID(int=3)
        )


@pytest.mark.parametrize("replayed", [False, True])
def test_tier_replacement_returns_new_or_replayed_result(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    replacement = SimpleNamespace(id=UUID(int=20))
    monkeypatch.setattr(api, "_account", lambda _request: Account(id=UUID(int=1)))
    monkeypatch.setattr(api, "authorize_tier_replacement_api_scope", lambda **_: None)
    monkeypatch.setattr(
        api, "ReserveAdmissionTierReplacementSerializer", StubInputSerializer
    )
    monkeypatch.setattr(api, "AdmissionTierReplacementSerializer", StubOutputSerializer)
    monkeypatch.setattr(api, "_commerce_idempotency_key", lambda _request: UUID(int=8))
    monkeypatch.setattr(api, "_correlation_id", lambda _request: UUID(int=9))
    monkeypatch.setattr(
        api,
        "reserve_admission_tier_replacement",
        lambda **_: SimpleNamespace(
            replacement=replacement,
            control_version=5,
            replayed=replayed,
        ),
    )

    response = api.MyAdmissionTierReplacementView().post(
        _request(), UUID(int=2), UUID(int=3), UUID(int=4)
    )

    assert response.status_code == (200 if replayed else 201)
    assert response["Idempotent-Replay"] == str(replayed).lower()


@pytest.mark.parametrize(
    ("stage", "error", "raised"),
    [
        ("authorize", _authorization_error(), NotFound),
        ("command", _authorization_error(), NotFound),
        ("command", ObjectDoesNotExist(), NotFound),
        (
            "command",
            ValidationError({"reason": ["Review reason."]}),
            ApiValidationError,
        ),
        ("command", ValidationError("Invalid replacement."), ApiValidationError),
    ],
)
def test_tier_replacement_maps_non_disclosing_failures(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(api, "_account", lambda _request: Account(id=UUID(int=1)))
    monkeypatch.setattr(
        api,
        "authorize_tier_replacement_api_scope",
        _raise(error) if stage == "authorize" else lambda **_: None,
    )
    monkeypatch.setattr(
        api, "ReserveAdmissionTierReplacementSerializer", StubInputSerializer
    )
    monkeypatch.setattr(api, "_commerce_idempotency_key", lambda _request: UUID(int=8))
    monkeypatch.setattr(api, "_correlation_id", lambda _request: UUID(int=9))
    monkeypatch.setattr(
        api,
        "reserve_admission_tier_replacement",
        _raise(error) if stage == "command" else lambda **_: None,
    )
    with pytest.raises(raised):
        api.MyAdmissionTierReplacementView().post(
            _request(), UUID(int=2), UUID(int=3), UUID(int=4)
        )
