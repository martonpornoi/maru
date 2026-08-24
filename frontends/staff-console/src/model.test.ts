import { describe, expect, it } from "vitest";

import type { EditionContext } from "./api/client";
import {
  capacityCounts,
  chooseInitialEdition,
  daysUntil,
  greetingFor,
  lifecycleLabel,
  primaryCapacity,
} from "./model";

describe("Staff Console model helpers", () => {
  it("prefers the administration-selected edition over remembered context", () => {
    window.localStorage.setItem("maru.staff.edition", "remembered");
    const editions: EditionContext[] = [
      {
        organization_id: "organization",
        organization_slug: "organization",
        series_id: "series",
        series_slug: "series",
        series_name: "Series",
        edition_id: "remembered",
        edition_slug: "remembered",
        edition_name: "Remembered",
        lifecycle: "preparing",
        time_zone: "Europe/Budapest",
        language_codes: ["en"],
        currency_codes: ["EUR"],
        starts_on: "2026-08-13",
        ends_on: "2026-08-16",
        participation_status: "active",
        can_transition: true,
        capacities: [],
      },
      {
        organization_id: "organization",
        organization_slug: "organization",
        series_id: "series",
        series_slug: "series",
        series_name: "Series",
        edition_id: "selected",
        edition_slug: "selected",
        edition_name: "Selected",
        lifecycle: "draft",
        time_zone: "Europe/Budapest",
        language_codes: ["en"],
        currency_codes: ["EUR"],
        starts_on: "2027-08-13",
        ends_on: "2027-08-16",
        participation_status: "active",
        can_transition: true,
        capacities: [],
      },
    ];

    expect(chooseInitialEdition(editions, "selected")?.edition_id).toBe(
      "selected",
    );
  });

  it("uses local calendar days for the edition countdown", () => {
    expect(daysUntil("2026-08-13", new Date(2026, 6, 27, 23, 30))).toBe(17);
  });

  it("sorts role counts by frequency and then label", () => {
    expect(
      capacityCounts([
        {
          account_id: "one",
          display_name: "One",
          participation_status: "active",
          capacity_labels: ["Staff", "Volunteer"],
        },
        {
          account_id: "two",
          display_name: "Two",
          participation_status: "active",
          capacity_labels: ["Staff", "Attendee"],
        },
      ]),
    ).toEqual([
      ["Staff", 2],
      ["Attendee", 1],
      ["Volunteer", 1],
    ]);
  });

  it("makes machine lifecycle values readable", () => {
    expect(lifecycleLabel("in-review")).toBe("In Review");
    expect(lifecycleLabel("payment_pending")).toBe("Payment Pending");
  });

  it("uses the current time for the greeting", () => {
    expect(greetingFor(new Date(2026, 6, 27, 8))).toBe("Good morning");
    expect(greetingFor(new Date(2026, 6, 27, 14))).toBe("Good afternoon");
    expect(greetingFor(new Date(2026, 6, 27, 20))).toBe("Good evening");
  });

  it("prefers a specific convention role over generic participation", () => {
    expect(
      primaryCapacity({
        organization_id: "organization",
        organization_slug: "organization",
        series_id: "series",
        series_slug: "series",
        series_name: "Series",
        edition_id: "edition",
        edition_slug: "edition",
        edition_name: "Edition",
        lifecycle: "preparing",
        time_zone: "Europe/Budapest",
        language_codes: ["en"],
        currency_codes: ["EUR"],
        starts_on: "2026-08-13",
        ends_on: "2026-08-16",
        participation_status: "active",
        can_transition: true,
        capacities: [
          {
            code: "attendee",
            label_snapshot: "Attendee",
            status: "active",
            contribution_summary: "",
            public_history_visible: true,
          },
          {
            code: "convention-chair",
            label_snapshot: "Convention Chair",
            status: "active",
            contribution_summary: "",
            public_history_visible: true,
          },
        ],
      }),
    ).toBe("Convention Chair");
  });
});
