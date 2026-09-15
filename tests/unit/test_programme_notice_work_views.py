"""Guided Work selection through real HTTP/forms, without database certification."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from maru.scheduling import change_notice_views as views
from maru.scheduling.change_catalogs import ChangeRecipientPurpose
from maru.scheduling.change_inputs import ChangeRecipientSelection
from maru.scheduling.change_notice_selection import (
    NoticeSourceSelectionLimitError,
    NoticeWorkSelection,
)
from maru.workforce.change_recipient_queries import ProgrammeWorkChangeRecipient
from maru.workforce.notice_recipient_choices import (
    ProgrammeWorkNoticeChoice,
    ProgrammeWorkNoticeLimitError,
)
from maru.workforce.personal_programme_links import PersonalProgrammeWorkLink
from maru.workforce.programme_staffing_queries import ProgrammeStaffingDeniedError
from tests.unit.test_programme_change_notice_views import call
from tests.unit.test_programme_notice_guided_views import (
    guided as guided,  # noqa: PLC0414
)
from tests.unit.test_programme_notice_guided_views import (
    page as page,  # noqa: PLC0414
)
from tests.unit.test_programme_notice_guided_views import (
    shell as shell,  # noqa: PLC0414
)
from tests.unit.test_programme_notice_guided_views import (
    world as world,  # noqa: PLC0414
)
from tests.unit.test_workforce_notice_choices import (
    work_choices as work_choices,  # noqa: PLC0414
)


@pytest.fixture
def guided_work(page, guided, work_choices, monkeypatch):
    host = guided.return_value
    row = work_choices.row
    choice = ProgrammeWorkNoticeChoice(
        ProgrammeWorkChangeRecipient(
            row.account_id,
            "Synthetic <holder>",
            PersonalProgrammeWorkLink(
                row.id,
                row.version,
                row.status,
                row.demand_id,
                row.demand_version,
                host.occurrences[0].occurrence.id,
                work_choices.link.binding_id,
                work_choices.link.binding_version,
                current=False,
            ),
        ),
        row.title,
        row.starts_at,
        row.ends_at,
    )
    observation = NoticeWorkSelection(
        host.release_id, host.pointer_version, host.occurrences, (choice,)
    )
    loader = Mock(return_value=observation)
    monkeypatch.setattr(views, "load_notice_work_selection", loader)
    return loader


def test_work_choice_uses_escaped_labels_and_exact_commitment_not_person(
    page, guided, guided_work
):
    result = guided_work.return_value
    response = call(
        page, query=f"?task=work&occurrence={result.occurrences[0].occurrence.id}"
    )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    work = result.commitments[0]
    option = soup.select_one(
        f'select[name="target_id"] option[value="{work.recipient.work.commitment_id}"]'
    )
    assert option is not None
    for label in (
        work.title,
        work.recipient.display_label,
        "confirmed",
        "retained work",
        "+00:00",
    ):
        assert label in option.get_text()
    assert str(work.recipient.account_id).encode() not in response.content
    assert b"<holder>" not in response.content
    assert b"<stage>" not in response.content
    assert b"does not mean cancellation" in response.content
    assert soup.select_one('input[name="purpose"]')["value"] == "work"
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    guided.assert_not_called()
    assert guided_work.call_count == 2
    for command in page.submit.values():
        command.assert_not_called()


def test_actual_guided_post_preserves_source_and_existing_native_work_preview(
    page, guided_work
):
    selected = guided_work.return_value
    occurrence = selected.occurrences[0].occurrence.id
    result = call(page, query=f"?task=work&occurrence={occurrence}")
    soup = BeautifulSoup(result.content, "html.parser")
    form = soup.select_one('select[name="target_id"]').find_parent("form")
    data = {node["name"]: node.get("value", "") for node in form.select("input[name]")}
    target = selected.commitments[0].recipient.work.commitment_id
    data["target_id"] = str(target)
    recipient = ChangeRecipientSelection(ChangeRecipientPurpose.WORK, target, None)
    page.preview.return_value = replace(
        page.world.preview, occurrence_id=occurrence, recipient=recipient
    )
    response = call(page, data=data)
    assert response.status_code == 200
    assert page.preview.call_args.kwargs == {
        "release_id": selected.release_id,
        "occurrence_id": occurrence,
        "recipient": recipient,
    }
    assert page.preview.call_count == 2
    assert b"Prepare for independent review" in response.content
    for command in page.submit.values():
        command.assert_not_called()


@pytest.mark.parametrize("empty", ["commitments", "release", "occurrences"])
def test_work_empty_states_offer_no_executable_preview(page, guided_work, empty):
    selected = guided_work.return_value
    guided_work.return_value = replace(
        selected,
        **{
            "commitments": {"commitments": ()},
            "release": {"release_id": None, "pointer_version": 0},
            "occurrences": {"occurrences": (), "commitments": ()},
        }[empty],
    )
    response = call(
        page, query=f"?task=work&occurrence={selected.occurrences[0].occurrence.id}"
    )
    assert response.status_code == 200
    assert not BeautifulSoup(response.content, "html.parser").select(
        'select[name="target_id"]'
    )


@pytest.mark.parametrize(
    "fault",
    ["person", "binding", "title", "interval", "denial", "work_bound", "source_bound"],
)
def test_final_work_observation_fails_closed_with_source_specific_guidance(
    page, guided_work, fault
):
    selected = guided_work.return_value
    choice = selected.commitments[0]
    if fault == "person":
        after = replace(
            selected,
            commitments=(
                replace(
                    choice, recipient=replace(choice.recipient, account_id=uuid4())
                ),
            ),
        )
    elif fault == "binding":
        after = replace(
            selected,
            commitments=(
                replace(
                    choice,
                    recipient=replace(
                        choice.recipient,
                        work=replace(choice.recipient.work, binding_version=9),
                    ),
                ),
            ),
        )
    elif fault == "title":
        after = replace(selected, commitments=(replace(choice, title="Moved title"),))
    elif fault == "interval":
        after = replace(
            selected, commitments=(replace(choice, starts_at=choice.ends_at),)
        )
    else:
        after = {
            "denial": ProgrammeStaffingDeniedError(),
            "work_bound": ProgrammeWorkNoticeLimitError(),
            "source_bound": NoticeSourceSelectionLimitError(),
        }[fault]
    guided_work.side_effect = [selected, after]
    response = call(
        page, query=f"?task=work&occurrence={selected.occurrences[0].occurrence.id}"
    )
    assert response.status_code == {
        "denial": 404,
        "work_bound": 503,
        "source_bound": 503,
    }.get(fault, 409)
    assert b"Synthetic" not in response.content
    assert b"Opening" not in response.content
    if fault.endswith("bound"):
        assert b"No partial list" in response.content
        assert b"Select an exact release" not in response.content
        assert (
            b"accepted-work choices" if fault == "work_bound" else b"source choices"
        ) in response.content


@pytest.mark.parametrize(
    ("query", "personal"),
    [
        ("?task=work", True),
        ("?task=work&task=hosts", False),
        (f"?task=work&release={uuid4()}", False),
        (f"?task=work&notice={uuid4()}", False),
        ("?task=work&occurrence=invalid", False),
    ],
)
def test_closed_work_selectors_do_not_discover_recipient_choices(
    page, guided_work, query, personal
):
    assert call(page, query=query, personal=personal).status_code == 400
    guided_work.assert_not_called()


def test_work_preview_does_not_infer_write_authority(page, guided_work):
    selected = guided_work.return_value
    page.authorize.return_value.accepts_writes = False
    data = {
        "action": "preview",
        "release_id": str(selected.release_id),
        "occurrence_id": str(selected.occurrences[0].occurrence.id),
        "purpose": "work",
        "target_id": str(selected.commitments[0].recipient.work.commitment_id),
    }
    response = call(page, data=data)
    assert response.status_code == 200
    assert b"Prepare for independent review" not in response.content
