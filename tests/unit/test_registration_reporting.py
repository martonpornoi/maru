"""Small reporting helpers with security-sensitive output behavior."""

from uuid import uuid4

from maru.registration.reporting import badge_export_csv


def test_badge_export_neutralizes_spreadsheet_formulas() -> None:
    output = badge_export_csv(
        rows=[
            {
                "reference": "MARU-001",
                "badge_name": '=HYPERLINK("https://example.invalid")',
                "badge_name_source": "registration_answer",
                "display_name": "+Synthetic attendee",
                "pronouns": "they/them",
                "spoken_language_codes": ["en"],
                "spoken_languages": ["English"],
                "country_code": "HU",
                "attendance_labels": [
                    {"code": "attendee", "label": "Attendee", "tone": "attendee"}
                ],
                "registration_state": "confirmed",
                "profile_photo_status": "none",
            }
        ],
        edition_name="Synthetic Convention",
        edition_id=uuid4(),
        generated_at="2030-01-01T00:00:00+00:00",
    )

    assert "'=HYPERLINK" in output
    assert "'+Synthetic attendee" in output
