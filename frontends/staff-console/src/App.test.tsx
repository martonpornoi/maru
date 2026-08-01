import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const context = {
  account_id: "11111111-1111-4111-8111-111111111111",
  display_name: "Danube Convention Chair (Demo)",
  preferred_language: "hu",
  can_access_advanced_records: true,
  memberships: [
    {
      organization_id: "22222222-2222-4222-8222-222222222222",
      organization_slug: "pannon-paws-foundation",
      organization_name: "Pannon Paws Foundation (Demo)",
      state: "active",
      relationship_label: "Convention Chair",
    },
  ],
  editions: [
    {
      organization_id: "22222222-2222-4222-8222-222222222222",
      organization_slug: "pannon-paws-foundation",
      series_id: "33333333-3333-4333-8333-333333333333",
      series_slug: "danube-furry-convention",
      series_name: "Danube Furry Convention",
      edition_id: "44444444-4444-4444-8444-444444444444",
      edition_slug: "danube-furry-convention-2026",
      edition_name: "Danube Furry Convention 2026",
      lifecycle: "preparing",
      time_zone: "Europe/Budapest",
      language_codes: ["en", "hu", "de"],
      currency_codes: ["EUR", "HUF"],
      starts_on: "2026-08-13",
      ends_on: "2026-08-16",
      participation_status: "active",
      can_transition: true,
      capacities: [
        {
          code: "staff",
          label_snapshot: "Staff",
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
    },
  ],
} as const;

const accessWorkspace = {
  organization_name: "Pannon Paws Foundation (Demo)",
  edition_name: "Danube Furry Convention 2026",
  can_revoke_assignments: true,
  groups: [
    {
      code: "board-member",
      name: "Board",
      description: "Oversee convention preparation and accountable decisions.",
      capability_count: 1,
      capabilities: [
        {
          code: "events.view_basic",
          label: "Events · View Basic",
          description: "View convention edition details.",
        },
      ],
    },
    {
      code: "front-desk",
      name: "Front Desk",
      description: "Serve attendees through arrival and check-in.",
      capability_count: 1,
      capabilities: [
        {
          code: "participation.view_staff_summary",
          label: "Participation · View Staff Summary",
          description: "View minimized participant summaries.",
        },
      ],
    },
  ],
  assignments: [
    {
      id: "abababab-abab-4bab-8bab-abababababab",
      person_display_name: "Front Desk Coordinator",
      person_email: "front-desk@example.invalid",
      group_code: "front-desk",
      group_name: "Front Desk",
      scope_label: "Danube Furry Convention 2026",
      status: "Active",
      effective_from: "2026-07-27T09:00:00Z",
      expires_at: null,
      granted_by_name: "Danube Convention Chair (Demo)",
      approved_by_name: "Board Approver",
    },
  ],
};

const closureReadiness = {
  counts: {},
  gates: [
    {
      id: "90909090-9090-4090-8090-909090909090",
      code: "finance",
      status: "approved",
      evidence_reference: "Finance reconciliation report 2026-08-31",
      review_summary: "All payments, refunds, and disputes were reconciled.",
      reviewed_at: "2026-09-01T09:30:00Z",
    },
  ],
  manifest: null,
};

const people = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      account_id: "55555555-5555-4555-8555-555555555555",
      display_name: "Danube Volunteer Coordinator (Demo)",
      participation_status: "active",
      capacity_labels: ["Staff", "Volunteer Coordination"],
    },
    {
      account_id: "66666666-6666-4666-8666-666666666666",
      display_name: "River Attendee (Demo)",
      participation_status: "confirmed",
      capacity_labels: ["Attendee"],
    },
  ],
};

const actions = [
  {
    key: "registration-configuration-review",
    level: "action",
    title: "Review inherited registration setup",
    summary: "Confirm dates, prices, capacity, questions, and current policy.",
    object_type: "registration_configuration",
    object_id: "77777777-7777-4777-8777-777777777777",
    destination: "commerce",
    owner_label: "Registration configuration",
    due_at: null,
    created_at: "2026-07-27T09:00:00Z",
  },
];

const attendeeReport = {
  generated_at: "2026-07-29T09:00:00Z",
  status_scope: ["confirmed", "checked_in"],
  summary: {
    coming: 3,
    confirmed: 2,
    checked_in: 1,
    countries: 2,
    volunteers: 1,
    approved_profile_photos: 1,
    country_breakdown: [
      { country_code: "HU", count: 2, percentage: 66.7 },
      { country_code: "AT", count: 1, percentage: 33.3 },
    ],
    level_breakdown: [
      { code: "attendee", label: "Attendee", tone: "attendee", count: 2 },
      {
        code: "volunteer",
        label: "Volunteer",
        tone: "volunteer",
        count: 1,
      },
    ],
  },
  count: 1,
  page: 1,
  page_size: 25,
  has_next: false,
  has_previous: false,
  results: [
    {
      registration_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      reference: "MARU-DEMO-001",
      badge_name: "River",
      badge_name_source: "registration_answer",
      display_name: "River Attendee (Demo)",
      pronouns: "they/them",
      spoken_language_codes: ["en", "hu"],
      spoken_languages: ["English", "Hungarian"],
      country_code: "HU",
      registration_state: "confirmed",
      product_name: "Weekend admission",
      attendance_labels: [
        { code: "attendee", label: "Attendee", tone: "attendee" },
        { code: "volunteer", label: "Volunteer", tone: "volunteer" },
      ],
      profile_photo_status: "approved",
    },
  ],
};

const mediaReviews = [
  {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    profile_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    account_id: "55555555-5555-4555-8555-555555555555",
    display_name: "River Attendee (Demo)",
    media_kind: "profile_photo",
    label: "Profile image",
    review_status: "pending",
    preview_path:
      "/register/media/profile/cccccccc-cccc-4ccc-8ccc-cccccccccccc/",
    submitted_at: "2026-07-27T09:00:00Z",
  },
];

const registrationConfiguration = {
  id: "77777777-7777-4777-8777-777777777777",
  name: "Danube attendee registration",
  version: 2,
  status: "active",
  source_summary: {
    kind: "edition",
    id: "88888888-8888-4888-8888-888888888888",
    label: "Copied from Danube Furry Convention 2025",
  },
  review_required: false,
  review_note: "Dates, capacity, products, wording, and policy reviewed.",
  opens_at: "2026-05-01T08:00:00Z",
  closes_at: "2026-08-12T20:00:00Z",
  capacity: 1_000,
  currency: "EUR",
  questions: [
    {
      id: "99999999-9999-4999-8999-999999999991",
      key: "badge_name",
      label: "Badge name",
      help_text: "The name printed on your convention badge.",
      field_type: "short_text",
      required: true,
      position: 10,
      options: [],
      purpose: "Print and issue the attendee badge.",
      visibility: "attendee_and_staff",
      classification: "C2",
      condition_question_key: "",
      condition_value: "",
    },
    {
      id: "99999999-9999-4999-8999-999999999992",
      key: "bringing_fursuit",
      label: "Are you bringing a fursuit?",
      help_text: "",
      field_type: "boolean",
      required: false,
      position: 20,
      options: [],
      purpose: "Plan fursuit lounge capacity.",
      visibility: "registration_staff",
      classification: "C2",
      condition_question_key: "",
      condition_value: "",
    },
    {
      id: "99999999-9999-4999-8999-999999999993",
      key: "fursuit_species",
      label: "Fursuit species",
      help_text: "",
      field_type: "short_text",
      required: false,
      position: 30,
      options: [],
      purpose: "Support badge and lounge preparation.",
      visibility: "registration_staff",
      classification: "C2",
      condition_question_key: "bringing_fursuit",
      condition_value: "true",
    },
  ],
  products: [
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      code: "weekend",
      name: "Weekend admission",
      description: "Admission for the complete convention.",
      price_minor: 8_500,
      capacity: 850,
      position: 10,
      entitlement_code: "weekend-admission",
      entitlement_name: "Weekend admission",
      status: "available",
    },
  ],
};

function jsonResponse(payload: object, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("Management Console", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/admin/workspace/");
    const root = document.getElementById("root");
    if (root) delete root.dataset.mode;
    window.localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/v1/me/context") return jsonResponse(context);
        if (url.includes("/participations?")) return jsonResponse(people);
        if (url.endsWith("/actions")) return jsonResponse(actions);
        if (url.endsWith("/access")) return jsonResponse(accessWorkspace);
        if (url.endsWith("/closure-readiness")) {
          return jsonResponse(closureReadiness);
        }
        if (url.includes("/closure-gates/")) {
          return jsonResponse({
            ...closureReadiness.gates[0],
            code: url.split("/").at(-1),
          });
        }
        if (url.includes("/access/assignments/")) {
          return jsonResponse(accessWorkspace);
        }
        if (url === "/api/v1/me/security-history") return jsonResponse([]);
        if (url.endsWith("/registration/me")) {
          return jsonResponse({
            configuration: registrationConfiguration,
            registration: null,
            demo_payment_enabled: true,
            server_time: "2026-07-27T09:00:00Z",
          });
        }
        if (url.endsWith("/registration/configuration")) {
          return jsonResponse({
            active_configuration: registrationConfiguration,
            drafts: [],
            templates: [],
            source_editions: [],
            bootstrap_editor_path: "/admin/registration/",
          });
        }
        if (url.endsWith("/registration/reconciliation")) {
          return jsonResponse({
            generated_at: "2026-07-27T09:00:00Z",
            products: [],
          });
        }
        if (url.endsWith("/registration/profile-media-reviews")) {
          return jsonResponse(mediaReviews);
        }
        if (url.includes("/registration/attendee-report?")) {
          return jsonResponse(attendeeReport);
        }
        if (url.includes("/registration/profile-media-reviews/")) {
          return jsonResponse({ ...mediaReviews[0], review_status: "approved" });
        }
        if (url.includes("/registrations?")) {
          return jsonResponse({
            count: 0,
            next: null,
            previous: null,
            results: [],
          });
        }
        return jsonResponse({ detail: "Unknown test request" }, 404);
      }),
    );
  });

  it("keeps a workspace-less administrator in the unified console", async () => {
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/me/context") {
        return jsonResponse({
          ...context,
          memberships: [],
          editions: [],
        });
      }
      return jsonResponse({ detail: "Unknown test request" }, 404);
    });

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "No convention workspace yet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open Specialist records" }),
    ).toHaveAttribute("href", "/admin/");
    expect(screen.queryByText("Administration Quick Start")).not.toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([url]) =>
        String(url).includes("convention-bootstrap"),
      ),
    ).toBe(false);
  });

  it("opens the active convention as a useful, honest cockpit", async () => {
    render(<App />);

    expect(
      await screen.findByRole("heading", {
        name: "Danube Furry Convention 2026",
      }),
    ).toBeInTheDocument();
    const peopleMetric = screen.getByText("People in edition").parentElement;
    expect(peopleMetric).not.toBeNull();
    expect(await within(peopleMetric as HTMLElement).findByText("2"))
      .toBeInTheDocument();
    expect(screen.getByText("Review inherited registration setup"))
      .toBeInTheDocument();
    expect(screen.getByText("Convention Chair", { selector: ".role-chip" }))
      .toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Maru administration home" }),
    ).toHaveAttribute("href", "/admin/");
    expect(screen.getByRole("heading", { name: "Forms" })).toBeInTheDocument();
    expect(screen.getByText("Registration staff intake")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Registration staff intake/ }),
    ).toHaveAttribute(
      "href",
      `/admin/registration-assist/${context.editions[0].edition_id}/`,
    );
    expect(document.body.textContent).not.toContain(
      "44444444-4444-4444-8444-444444444444",
    );
  });

  it("embeds convention work without a second global navigation menu", async () => {
    render(<App embeddedInAdmin />);

    expect(
      await screen.findByRole("heading", {
        name: "Danube Furry Convention 2026",
      }),
    ).toBeInTheDocument();
    expect(document.querySelector(".primary-nav")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Convention workspace" }),
    ).not.toBeInTheDocument();
  });

  it("renders convention-specific questions and conditional fields", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(screen.getByRole("button", { name: "My registration" }));

    expect(
      await screen.findByRole("heading", {
        name: "Register for Danube Furry Convention 2026",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Badge name/ }))
      .toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Fursuit species" }))
      .not.toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Are you bringing a fursuit?" }),
      "true",
    );
    expect(screen.getByRole("textbox", { name: "Fursuit species" }))
      .toBeInTheDocument();
  });

  it("explains the purpose and common interactions on every destination", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByText(
        "Use this overview to understand Danube Furry Convention 2026 at a glance.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "People" }));
    expect(
      screen.getByText(
        "Use this page to find who is participating and how they are involved.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "My registration" }));
    expect(
      await screen.findByText(
        "Use this page to choose admission and submit the questions defined for this convention.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Registration" }));
    expect(
      await screen.findByText(
        "Use this page to configure registration and serve attendees through arrival.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reports & badges" }));
    expect(
      await screen.findByText(
        "Use this page to answer attendance questions and prepare a minimized badge-data file.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByText("My account"));
    await user.click(screen.getByRole("button", { name: "Security history" }));
    expect(
      await screen.findByText(
        "Use this page to review important events for your Maru account.",
      ),
    ).toBeInTheDocument();
  });

  it("shows country metrics and exports the filtered badge dataset", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(screen.getByRole("button", { name: "Reports & badges" }));

    expect(
      await screen.findByRole("heading", { name: "Attendees and badges" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Hungary (HU)").length).toBeGreaterThan(0);
    expect(screen.getByText("River")).toBeInTheDocument();
    expect(screen.getAllByText("Volunteer").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Download badge CSV" }))
      .toHaveAttribute(
        "href",
        expect.stringContaining("/registration/badge-export.csv?"),
      );
  });

  it("preserves the people list while opening a minimized person workspace", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(screen.getByRole("button", { name: "People" }));
    const directory = await screen.findByRole("heading", { name: "People" });
    expect(directory).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "Danube Volunteer Coordinator (Demo)",
      }),
    );

    const drawer = await screen.findByRole("complementary", {
      name: "Danube Volunteer Coordinator (Demo)",
    });
    expect(
      within(drawer).getByRole("heading", {
        name: "Danube Volunteer Coordinator (Demo)",
      }),
    ).toBeInTheDocument();
    expect(within(drawer).getByText(/only the fields permitted/))
      .toBeInTheDocument();
  });

  it("sends search terms to the tenant- and edition-scoped endpoint", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });
    await user.click(screen.getByRole("button", { name: "People" }));

    await user.type(
      screen.getByRole("searchbox", { name: "Search by display name" }),
      "Volunteer",
    );
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("search=Volunteer"),
        expect.objectContaining({ credentials: "same-origin" }),
      );
    });
  });

  it("shows the profile-image queue and records a reasoned decision", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });
    await user.click(screen.getByRole("button", { name: "Registration" }));

    expect(
      await screen.findByRole("heading", { name: "Images awaiting review" }),
    ).toBeInTheDocument();
    expect(screen.getByText("River Attendee (Demo)")).toBeInTheDocument();
    await user.type(
      screen.getByRole("textbox", {
        name: "Review reason for River Attendee (Demo) Profile image",
      }),
      "Suitable profile image.",
    );
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/registration/profile-media-reviews/"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Suitable profile image."),
        }),
      );
    });
  });

  it("keeps low-frequency setup in a collapsible ordered guide", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    const setupSection = screen.getByText("Convention setup").closest("details");
    expect(setupSection).not.toHaveAttribute("open");
    await user.click(screen.getByText("Convention setup"));
    await user.click(screen.getByRole("button", { name: "Setup guide" }));

    expect(
      screen.getByRole("heading", { name: "Setup guide" }),
    ).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    expect(steps.some((step) => step.textContent?.includes("Organization")))
      .toBe(true);
    expect(
      screen.getByRole("link", { name: "Browse specialist records" }),
    ).toHaveAttribute("href", "/admin/");
  });

  it("records readiness evidence without asking for IDs or a review time", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(screen.getByText("Convention setup"));
    await user.click(screen.getByRole("button", { name: "Setup guide" }));

    expect(
      await screen.findByRole("heading", { name: "Edition readiness review" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Organization id")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reviewed at")).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/signed-in reviewer and current server time/).length,
    ).toBeGreaterThan(0);

    await user.type(
      screen.getByRole("textbox", {
        name: "Privacy evidence reference",
      }),
      "Privacy closeout checklist 2026",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Privacy review summary" }),
      "Retention and access work is complete.",
    );
    await user.click(screen.getAllByRole("button", { name: "Approve gate" })[0]);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/closure-gates/privacy"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("Privacy closeout checklist 2026"),
        }),
      );
    });
  });

  it("shares named group access with an exact person and independent approver", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(await screen.findByRole("button", { name: "Manage access" }));
    const drawer = screen.getByRole("dialog", { name: "Access to Today" });
    expect(
      within(drawer).getByText("Front Desk Coordinator"),
    ).toBeInTheDocument();
    expect(within(drawer).getByText("Recommended · Board")).toBeInTheDocument();
    const assignmentSearch = within(drawer).getByRole("searchbox", {
      name: "Find a person or group",
    });
    await user.type(assignmentSearch, "no matching person");
    expect(
      within(drawer).getByText("No current assignment matches that search."),
    ).toBeInTheDocument();
    await user.clear(assignmentSearch);

    await user.type(
      within(drawer).getByRole("textbox", { name: "Existing account email" }),
      "helper@example.invalid",
    );
    await user.selectOptions(
      within(drawer).getByRole("combobox", { name: "Group" }),
      "front-desk",
    );
    await user.type(
      within(drawer).getByRole("textbox", {
        name: "Independent approver email",
      }),
      "approver@example.invalid",
    );
    await user.type(
      within(drawer).getByRole("textbox", { name: "Reason" }),
      "Front Desk shift coverage.",
    );
    await user.click(within(drawer).getByRole("button", { name: "Share access" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/access$/),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("helper@example.invalid"),
        }),
      );
    });
  });

  it("does not reveal people, counts, or filters after a policy denial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/v1/me/context") return jsonResponse(context);
        return jsonResponse(
          {
            detail: "Staff participation summaries are unavailable.",
            code: "capability_absent",
          },
          403,
        );
      }),
    );
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", {
      name: "Danube Furry Convention 2026",
    });

    await user.click(screen.getByRole("button", { name: "People" }));

    expect(
      await screen.findByRole("heading", {
        name: "People summaries aren’t available for your role",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/people$/)).not.toBeInTheDocument();
  });
});
