"""Native labelled controls for the separate operator-notice read stages."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from django import forms

from .change_notice_forms import OperatorNoticeLookupForm, OperatorNoticePreviewForm
from .command_support import SchedulingVersionConflictError
from .operator_notice_choices import (
    NoticeOperatorChoices,
    admit_notice_operator_selection,
    load_notice_operator_choices,
)
from .operator_scope import OperatorScopeKind

if TYPE_CHECKING:
    from uuid import UUID

    from .operator_notice_person_selection import OperatorNoticePersonSelection
    from .planning_queries import SchedulingReadRequest


def operator_notice_controls(
    scope: SchedulingReadRequest,
    *,
    occurrence_id: UUID | None,
    kind: OperatorScopeKind | None,
    target_id: UUID | None,
) -> dict[str, object]:
    """Build labelled native selectors without treating a choice as authority.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Actual notice-admitted sender; each protected owner admits independently.
    occurrence_id : UUID | None
        Optional deliberate current occurrence.
    kind : OperatorScopeKind | None
        Optional deliberate closed operator purpose.
    target_id : UUID | None
        Optional exact member of current owner-admitted target choices.

    Returns
    -------
    dict[str, object]
        Native form context and full owner observation for final render comparison.
    """
    choices = load_notice_operator_choices(
        scope, occurrence_id=occurrence_id, kind=kind, target_id=target_id
    )
    source_form = forms.Form(
        auto_id="operator-source-%s",
        initial={
            "task": "operators",
            "occurrence": occurrence_id,
            "operator_kind": kind,
        },
    )
    source_form.fields["task"] = forms.CharField(widget=forms.HiddenInput)
    source_form.fields["occurrence"] = forms.ChoiceField(
        label="Current Programme occurrence",
        choices=[
            ("", "Choose an occurrence"),
            *(
                (str(row.occurrence.id), row.label)
                for row in choices.source.occurrences
            ),
        ],
    )
    source_form.fields["operator_kind"] = forms.ChoiceField(
        label="Operator purpose",
        choices=[
            ("", "Choose a purpose"),
            *((value.value, value.value.title()) for value in OperatorScopeKind),
        ],
    )
    target_form = None
    if kind is not None and choices.targets:
        target_form = forms.Form(
            auto_id="operator-target-%s",
            initial={
                "task": "operators",
                "occurrence": occurrence_id,
                "operator_kind": kind,
                "operator_target": target_id,
            },
        )
        for name in ("task", "occurrence", "operator_kind"):
            target_form.fields[name] = forms.CharField(widget=forms.HiddenInput)
        target_form.fields["operator_target"] = forms.ChoiceField(
            label="Current operator scope",
            choices=[
                ("", "Choose a scope"),
                *((str(row.id), row.label) for row in choices.targets),
            ],
        )
    lookup_form = None
    if target_id is not None and choices.source.release_id is not None:
        lookup_form = OperatorNoticeLookupForm(
            initial={
                "action": "operator_lookup",
                "release_id": choices.source.release_id,
                "occurrence_id": occurrence_id,
                "pointer_version": choices.source.pointer_version,
                "kind": kind,
                "target_id": target_id,
                "lookup_retry_key": uuid4(),
            }
        )
    return {
        "operator_selection": True,
        "operator_choices": choices,
        "operator_source_form": source_form,
        "operator_target_form": target_form,
        "operator_lookup_form": lookup_form,
    }


def operator_notice_selected_controls(
    selection: OperatorNoticePersonSelection,
) -> dict[str, object]:
    """Present one eligible person for deliberate preview, without echoing email.

    Parameters
    ----------
    selection : OperatorNoticePersonSelection
        Current independently admitted person and original signed intent.

    Returns
    -------
    dict[str, object]
        Named choice and signed preview form; no arbitrary account field.
    """
    return {
        "operator_selection": True,
        "operator_person": selection,
        "operator_choices": selection.choices,
        "operator_preview_form": OperatorNoticePreviewForm(
            initial={"action": "operator_preview", "token": selection.token}
        ),
    }


def verify_operator_notice_choices(
    scope: SchedulingReadRequest, context: dict[str, object]
) -> None:
    """Repeat recipient admission even for empty results and invalid lookup forms.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Actual current sender and trusted exact owner scope.
    context : dict[str, object]
        Rendered protected observations; never a dispatched command.

    Raises
    ------
    SchedulingVersionConflictError
        If a current labelled source or target observation moved during rendering.
    """
    if not context.get("operator_selection"):
        return
    admit_notice_operator_selection(scope)
    choices = context.get("operator_choices")
    if (
        isinstance(choices, NoticeOperatorChoices)
        and load_notice_operator_choices(
            scope,
            occurrence_id=choices.occurrence_id,
            kind=choices.kind,
            target_id=choices.target_id,
        )
        != choices
    ):
        raise SchedulingVersionConflictError
