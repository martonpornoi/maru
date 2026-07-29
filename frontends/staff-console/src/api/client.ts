import type { components } from "./schema";

export type MyContext = components["schemas"]["MyContext"];
export type EditionContext = components["schemas"]["EditionContext"];
export type Participation =
  components["schemas"]["StaffParticipationSummary"];
export type ParticipationPage =
  components["schemas"]["PaginatedStaffParticipationSummaryList"];
export type ActionItem = components["schemas"]["ActionItem"];
export type SecurityEvent = components["schemas"]["AccountSecurityEvent"];
export type RegistrationConfiguration =
  components["schemas"]["RegistrationConfiguration"];
export type RegistrationConfigurationWorkspace =
  components["schemas"]["RegistrationConfigurationWorkspace"];
export type MyRegistrationWorkspace =
  components["schemas"]["MyRegistrationWorkspace"];
export type StaffRegistration = components["schemas"]["StaffRegistration"];
export type StaffRegistrationPage =
  components["schemas"]["PaginatedStaffRegistrationList"];
export type RegistrationReconciliation =
  components["schemas"]["RegistrationReconciliation"];
export type RegistrationQuestion =
  components["schemas"]["RegistrationQuestion"];
export type ProfileMediaReviewItem =
  components["schemas"]["ProfileMediaReviewItem"];
export type AttendeeReport = components["schemas"]["AttendeeReport"];
export type AttendeeReportRow = components["schemas"]["AttendeeReportRow"];

type Problem = {
  code?: string;
  detail?: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function csrfToken(): string | undefined {
  return (
    document
      .querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
      ?.getAttribute("content") ?? undefined
  );
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Request-ID", crypto.randomUUID());
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    const token = csrfToken();
    if (token) {
      headers.set("X-CSRFToken", token);
    }
  }

  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) {
    let problem: Problem = {};
    try {
      problem = (await response.json()) as Problem;
    } catch {
      // A proxy or expired HTML session may not return a problem document.
    }
    throw new ApiError(
      response.status,
      problem.detail ?? "Maru could not complete that request.",
      problem.code,
    );
  }
  return (await response.json()) as T;
}

export function loadMyContext(): Promise<MyContext> {
  return requestJson<MyContext>("/api/v1/me/context");
}

export type ParticipationFilters = {
  search?: string;
  status?: string;
  capacity?: string;
  page?: number;
};

export function participationPath(
  edition: EditionContext,
  filters: ParticipationFilters = {},
): string {
  const query = new URLSearchParams({ page_size: "25" });
  if (filters.search) query.set("search", filters.search);
  if (filters.status) query.set("status", filters.status);
  if (filters.capacity) query.set("capacity", filters.capacity);
  if (filters.page && filters.page > 1) {
    query.set("page", String(filters.page));
  }
  return (
    `/api/v1/organizations/${edition.organization_id}` +
    `/editions/${edition.edition_id}/participations?${query.toString()}`
  );
}

export function loadParticipations(
  edition: EditionContext,
  filters: ParticipationFilters = {},
): Promise<ParticipationPage> {
  return requestJson<ParticipationPage>(participationPath(edition, filters));
}

function editionApiPath(edition: EditionContext): string {
  return (
    `/api/v1/organizations/${edition.organization_id}` +
    `/editions/${edition.edition_id}`
  );
}

export function loadActions(edition: EditionContext): Promise<ActionItem[]> {
  return requestJson<ActionItem[]>(`${editionApiPath(edition)}/actions`);
}

export function loadSecurityHistory(): Promise<SecurityEvent[]> {
  return requestJson<SecurityEvent[]>("/api/v1/me/security-history");
}

export function loadRegistrationConfiguration(
  edition: EditionContext,
): Promise<RegistrationConfigurationWorkspace> {
  return requestJson<RegistrationConfigurationWorkspace>(
    `${editionApiPath(edition)}/registration/configuration`,
  );
}

export type CreateRegistrationDraftInput = {
  name: string;
  reason: string;
  source_template_id?: string;
  source_edition_id?: string;
  opens_at?: string;
  closes_at?: string;
  capacity?: number;
  currency?: string;
};

export function createRegistrationDraft(
  edition: EditionContext,
  input: CreateRegistrationDraftInput,
): Promise<RegistrationConfiguration> {
  return requestJson<RegistrationConfiguration>(
    `${editionApiPath(edition)}/registration/configuration/drafts`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function activateRegistrationConfiguration(
  edition: EditionContext,
  configurationId: string,
  reason: string,
): Promise<RegistrationConfiguration> {
  return requestJson<RegistrationConfiguration>(
    `${editionApiPath(edition)}/registration/configuration/activate`,
    {
      method: "POST",
      body: JSON.stringify({
        configuration_id: configurationId,
        reason,
      }),
    },
  );
}

export type PublishRegistrationTemplateInput = {
  configuration_id: string;
  code: string;
  name: string;
  description: string;
  series_limited: boolean;
  reason: string;
};

export function publishRegistrationTemplate(
  edition: EditionContext,
  input: PublishRegistrationTemplateInput,
): Promise<components["schemas"]["RegistrationTemplateSummary"]> {
  return requestJson<components["schemas"]["RegistrationTemplateSummary"]>(
    `${editionApiPath(edition)}/registration/templates`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function loadMyRegistration(
  edition: EditionContext,
): Promise<MyRegistrationWorkspace> {
  return requestJson<MyRegistrationWorkspace>(
    `${editionApiPath(edition)}/registration/me`,
  );
}

export function submitMyRegistration(
  edition: EditionContext,
  productId: string,
  answers: Record<string, unknown>,
): Promise<components["schemas"]["SelfRegistration"]> {
  return requestJson<components["schemas"]["SelfRegistration"]>(
    `${editionApiPath(edition)}/registration/me`,
    {
      method: "POST",
      body: JSON.stringify({
        product_id: productId,
        answers,
      }),
    },
  );
}

export function confirmMyDemoPayment(
  edition: EditionContext,
  registrationId: string,
): Promise<components["schemas"]["SelfRegistration"]> {
  return requestJson<components["schemas"]["SelfRegistration"]>(
    `${editionApiPath(edition)}/registration/me/${registrationId}/demo-payment`,
    {
      method: "POST",
      body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
    },
  );
}

export type StaffRegistrationFilters = {
  search?: string;
  state?: string;
  page?: number;
};

export function loadStaffRegistrations(
  edition: EditionContext,
  filters: StaffRegistrationFilters = {},
): Promise<StaffRegistrationPage> {
  const query = new URLSearchParams({ page_size: "25" });
  if (filters.search) query.set("search", filters.search);
  if (filters.state) query.set("state", filters.state);
  if (filters.page && filters.page > 1) {
    query.set("page", String(filters.page));
  }
  return requestJson<StaffRegistrationPage>(
    `${editionApiPath(edition)}/registrations?${query.toString()}`,
  );
}

export function checkInRegistration(
  edition: EditionContext,
  registrationId: string,
  reason: string,
): Promise<StaffRegistration> {
  return requestJson<StaffRegistration>(
    `${editionApiPath(edition)}/registrations/${registrationId}/check-in`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function changeRegistrationPaymentDeadline(
  edition: EditionContext,
  registrationId: string,
  newDeadline: string,
  reason: string,
): Promise<StaffRegistration> {
  return requestJson<StaffRegistration>(
    `${editionApiPath(edition)}/registrations/${registrationId}/payment-deadline`,
    {
      method: "POST",
      body: JSON.stringify({
        new_deadline: newDeadline,
        reason,
      }),
    },
  );
}

export function waiveRegistrationPayment(
  edition: EditionContext,
  registrationId: string,
  reason: string,
): Promise<StaffRegistration> {
  return requestJson<StaffRegistration>(
    `${editionApiPath(edition)}/registrations/${registrationId}/waive-payment`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function loadRegistrationReconciliation(
  edition: EditionContext,
): Promise<RegistrationReconciliation> {
  return requestJson<RegistrationReconciliation>(
    `${editionApiPath(edition)}/registration/reconciliation`,
  );
}

export function loadProfileMediaReviews(
  edition: EditionContext,
): Promise<ProfileMediaReviewItem[]> {
  return requestJson<ProfileMediaReviewItem[]>(
    `${editionApiPath(edition)}/registration/profile-media-reviews`,
  );
}

export type AttendeeReportFilters = {
  search?: string;
  country_code?: string;
  level?: string;
  page?: number;
};

function attendeeReportQuery(filters: AttendeeReportFilters): URLSearchParams {
  const query = new URLSearchParams({ page_size: "25" });
  if (filters.search) query.set("search", filters.search);
  if (filters.country_code) query.set("country_code", filters.country_code);
  if (filters.level) query.set("level", filters.level);
  if (filters.page && filters.page > 1) query.set("page", String(filters.page));
  return query;
}

export function attendeeReportPath(
  edition: EditionContext,
  filters: AttendeeReportFilters = {},
): string {
  return (
    `${editionApiPath(edition)}/registration/attendee-report?` +
    attendeeReportQuery(filters).toString()
  );
}

export function loadAttendeeReport(
  edition: EditionContext,
  filters: AttendeeReportFilters = {},
): Promise<AttendeeReport> {
  return requestJson<AttendeeReport>(attendeeReportPath(edition, filters));
}

export function badgeExportPath(
  edition: EditionContext,
  filters: AttendeeReportFilters = {},
): string {
  return (
    `${editionApiPath(edition)}/registration/badge-export.csv?` +
    attendeeReportQuery(filters).toString()
  );
}

export function reviewProfileMedia(
  edition: EditionContext,
  item: ProfileMediaReviewItem,
  decision: "approved" | "rejected",
  reason: string,
): Promise<ProfileMediaReviewItem> {
  return requestJson<ProfileMediaReviewItem>(
    `${editionApiPath(edition)}/registration/profile-media-reviews/${item.id}`,
    {
      method: "POST",
      body: JSON.stringify({
        media_kind: item.media_kind,
        decision,
        reason,
      }),
    },
  );
}
