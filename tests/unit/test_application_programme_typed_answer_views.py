"""Shared real-template answer behavior for three independently admitted roles."""

import json
from dataclasses import replace

import pytest

from tests.unit import test_application_programme_decider_views as decider
from tests.unit import test_application_programme_moderation_views as moderator
from tests.unit import test_application_programme_reviewer_work_views as reviewer
from tests.unit.test_application_programme_answer_display import ADDRESS, OPTIONS
from tests.unit.test_application_programme_review_setup_views import shell, soup

pytestmark = pytest.mark.usefixtures(shell.__name__)


@pytest.fixture(
    params=[reviewer, moderator, decider], ids=["reviewer", "moderator", "decider"]
)
def role(request, monkeypatch):
    adapter = request.param
    page = adapter.page.__wrapped__(monkeypatch)
    if adapter is reviewer:
        page.source.return_value = reviewer.context(state="active")
    return adapter, page


def row(kind, value, **extra):
    return {
        "key": "synthetic_answer",
        "label": "Synthetic answer",
        "classification": "C2",
        "type": kind,
        "value": value,
        **extra,
    }


def response(role, rows):
    adapter, page = role
    page.detail.return_value = replace(
        page.detail.return_value, answers_json=json.dumps(rows)
    )
    return adapter.request(task="answers")


def test_three_roles_read_labels_and_only_protected_file_task_links(role):
    result = response(
        role,
        [
            row("single_choice", "workshop", selected_options=[OPTIONS[1]]),
            row(
                "multiple_choice",
                ["workshop", "talk"],
                selected_options=[OPTIONS[1], OPTIONS[0]],
            ),
            row("multiple_choice", [], selected_options=[]),
            row("address", ADDRESS),
            row("boolean", value=False),
            row("integer", 0),
            row("long_text", None),
            row("long_text", "<script>attack</script>\nSecond line"),
            row("instant", "2026-09-15T18:30:00+02:00"),
            row("url", "https://example.invalid/untrusted"),
            row("email", "synthetic@example.invalid"),
            row("safe_file", "PRIVATE-REFERENCE"),
        ],
    )
    assert result.status_code == 200
    html = soup(result)
    text = html.get_text()
    assert "Practical <workshop>" in text
    assert "Talk & discussion" in text
    assert "City or locality: Example city" in text
    assert "Country code: HU" in text
    assert "No options selected in this exact revision." in text
    assert "No answer in this exact revision." in text
    assert "2026-09-15 18:30:00+02:00" in text
    assert "<script>attack</script>" in text
    assert html.find("script", string="attack") is None
    assert "PRIVATE-REFERENCE" not in text
    assert html.select_one('a[href$="answers/file/synthetic_answer/"]')
    assert "Unselected private option" not in text
    assert html.find("a", href="https://example.invalid/untrusted") is None
    assert html.find("a", href="mailto:synthetic@example.invalid") is None
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    scope = role[1].detail.call_args.kwargs["request"]
    assert scope.requested_fields == frozenset({"review_answers"})
    role[1].command.assert_not_called()


@pytest.mark.parametrize(
    "malformed",
    [
        row("unknown", "secret"),
        row("single_choice", "unknown"),
        row("address", ADDRESS | {"private-extra": "secret"}),
    ],
)
def test_invalid_typed_value_discards_the_entire_prepared_answer_page(role, malformed):
    result = response(role, [row("short_text", "Earlier private answer"), malformed])
    assert result.status_code == 503
    assert b"Earlier private answer" not in result.content
    assert b"secret" not in result.content
    role[1].command.assert_not_called()
