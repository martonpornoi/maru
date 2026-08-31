import {
  createContext,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  activateRegistrationConfiguration,
  ApiError,
  type AccessAssignment,
  type AccessGroup,
  type AccessPreview,
  type AccessWorkspace,
  type ActionItem,
  type AssignAccessInput,
  assignAccessGroup,
  type AttendeeReport,
  type AttendeeReportFilters,
  badgeExportPath,
  changeRegistrationPaymentDeadline,
  checkInRegistration,
  type ClosureReadiness,
  confirmMyDemoPayment,
  createRegistrationDraft,
  type EditionContext,
  type EditionTransitionResult,
  loadActions,
  loadAccessWorkspace,
  loadAttendeeReport,
  loadClosureReadiness,
  loadMyContext,
  loadMyProfileExtensions,
  loadMyRegistration,
  loadParticipations,
  loadProfileMediaReviews,
  loadRegistrationConfiguration,
  loadRegistrationReconciliation,
  loadSecurityHistory,
  loadStaffRegistrations,
  loadWorkforceStructure,
  type MyContext,
  type MyRegistrationWorkspace,
  type Participation,
  type ParticipationFilters,
  type ParticipationPage,
  type ProfileMediaReviewItem,
  type ProfileExtensionField,
  type ProfileExtensionWorkspace,
  type PreviewAccessInput,
  type RegistrationConfigurationWorkspace,
  type RegistrationReconciliation,
  type RegistrationQuestion,
  type ReadinessGate,
  type ReadinessGateCode,
  type ReplaceAccessInput,
  reviewReadinessGate,
  type SecurityEvent,
  type StaffRegistration,
  type StaffRegistrationFilters,
  type StaffRegistrationPage,
  type WorkforceStructureDepartment,
  type WorkforceStructurePosition,
  type WorkforceStructureWorkspace,
  publishRegistrationTemplate,
  previewAccess,
  replaceAccessAssignment,
  reviewProfileMedia,
  revokeAccessAssignment,
  submitMyRegistration,
  transitionEdition,
  waiveRegistrationPayment,
  writeMyProfileExtension,
} from "./api/client";
import {
  availableStaffConsoleDestinations,
  capacityCounts,
  chooseInitialEdition,
  daysUntil,
  formatDateRange,
  greetingFor,
  isStaffConsoleDestinationAvailable,
  lifecycleLabel,
  primaryCapacity,
  type StaffConsoleDestination,
  weekdayLabel,
} from "./model";

type Destination = StaffConsoleDestination;

const upcomingDestinations = [
  "Programme & schedule",
  "Team inbox",
  "Live operations",
];

const destinationLabels: Record<Destination, string> = {
  today: "Today",
  "my-registration": "My registration",
  people: "People",
  workforce: "Workforce",
  commerce: "Registration desk",
  reports: "Reports & badges",
  security: "Security history",
  setup: "Setup guide",
};

function isAvailableDestination(
  edition: EditionContext,
  destination: string,
): destination is Destination {
  return isStaffConsoleDestinationAvailable(edition, destination);
}

function availablePresentationDestinations(
  edition: EditionContext,
): Destination[] {
  return availableStaffConsoleDestinations(edition);
}

const recommendedGroups: Record<Destination, string[]> = {
  today: ["convention-chair", "vice-chair", "board-member"],
  "my-registration": [],
  people: ["department-lead", "staff-member", "board-member"],
  workforce: [
    "convention-chair",
    "vice-chair",
    "volunteer-coordinator",
    "department-lead",
  ],
  commerce: [
    "registration-lead",
    "front-desk",
    "treasurer",
    "media-moderator",
  ],
  reports: ["registration-lead", "treasurer", "board-member"],
  security: [],
  setup: ["convention-chair", "vice-chair", "board-member"],
};

const readinessGateDefinitions: Array<{
  code: ReadinessGateCode;
  label: string;
  purpose: string;
}> = [
  {
    code: "privacy",
    label: "Privacy",
    purpose: "Confirm retention, access, and data-rights work is accounted for.",
  },
  {
    code: "finance",
    label: "Finance",
    purpose: "Confirm payments, refunds, disputes, and reconciliation are resolved.",
  },
  {
    code: "operations",
    label: "Operations",
    purpose: "Confirm operational queues and convention follow-up are complete.",
  },
  {
    code: "security",
    label: "Security",
    purpose: "Confirm security incidents and credential concerns are resolved.",
  },
  {
    code: "jurisdiction",
    label: "Jurisdiction & safeguarding",
    purpose: "Confirm legal, safety, and safeguarding obligations are resolved.",
  },
];

function requestedDestination(): Destination {
  const value = new URLSearchParams(window.location.search).get("view");
  return value && value in destinationLabels ? (value as Destination) : "today";
}

function accessWasRequested(): boolean {
  return new URLSearchParams(window.location.search).get("access") === "1";
}

function accountLabel(context: MyContext): string {
  return context.display_name.trim() || "Signed-in account";
}

function isAdminEmbedded(): boolean {
  return document.getElementById("root")?.dataset.mode === "admin-embedded";
}

function selectedAdminEditionId(): string | undefined {
  return document.getElementById("root")?.dataset.selectedEdition || undefined;
}

function registrationSetupPath(edition: EditionContext): string {
  return [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "registration",
    "",
  ].join("/");
}

function workforceStructurePath(edition: EditionContext): string {
  return [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "structure",
    "",
  ].join("/");
}

function workforcePositionsPath(
  edition: EditionContext,
  positionId?: string,
): string {
  const segments = [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "structure",
    "positions",
  ];
  if (positionId) segments.push(encodeURIComponent(positionId));
  segments.push("");
  return segments.join("/");
}

function workforceAssignmentsPath(edition: EditionContext): string {
  return [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "structure",
    "assignments",
    "",
  ].join("/");
}

function workforceAvailabilityPath(edition: EditionContext): string {
  return [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "structure",
    "availability",
    "",
  ].join("/");
}

function workforceShiftsPath(edition: EditionContext): string {
  return [
    "/admin/platform/organizations",
    encodeURIComponent(edition.organization_slug),
    "series",
    encodeURIComponent(edition.series_slug),
    "editions",
    encodeURIComponent(edition.edition_slug),
    "structure",
    "shifts",
    "",
  ].join("/");
}

function workforceWorkspacePath(): string {
  return "/admin/workspace/?view=workforce";
}

function submitEmbeddedEditionContext(editionId: string): boolean {
  const form = document.querySelector<HTMLFormElement>(
    "#maru-admin-context-form",
  );
  const input = form?.querySelector<HTMLInputElement>(
    "input[name='edition_id']",
  );
  if (!form || !input) return false;
  input.value = editionId;
  form.requestSubmit();
  return true;
}

function Icon({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <span className="icon" aria-hidden={label ? undefined : true}>
      {children}
    </span>
  );
}

function CenterState({
  children,
  live,
}: {
  children: ReactNode;
  live?: "polite";
}) {
  if (isAdminEmbedded()) {
    return (
      <div className="center-state" aria-live={live}>
        {children}
      </div>
    );
  }
  return (
    <main className="center-state" aria-live={live}>
      {children}
    </main>
  );
}

function ModalDrawer({
  labelledBy,
  className,
  scrimClassName = "",
  closeLabel,
  onClose,
  children,
}: {
  labelledBy: string;
  className: string;
  scrimClassName?: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const returnFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : undefined;
    const background = (
      isAdminEmbedded()
        ? ["#header", ".breadcrumbs", "#main", "#toggle-nav-sidebar"].map(
            (selector) => document.querySelector<HTMLElement>(selector),
          )
        : [
            document.getElementById("root") ??
              document.querySelector<HTMLElement>(".shell"),
          ]
    ).filter((element): element is HTMLElement => element !== null);
    const previous = background.map((element) => ({
      element,
      ariaHidden: element.getAttribute("aria-hidden"),
      inert: element.hasAttribute("inert"),
    }));
    const focusableSelector = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "summary",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    for (const element of background) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }
    document.body.classList.add("maru-react-drawer-open");

    const focusFirst = () => {
      const first = drawerRef.current?.querySelector<HTMLElement>(
        focusableSelector,
      );
      (first ?? drawerRef.current)?.focus();
    };
    const focusTimer = window.setTimeout(focusFirst, 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(focusableSelector),
      ).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        drawerRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1) ?? first;
      if (!drawerRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);

    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown, true);
      document.body.classList.remove("maru-react-drawer-open");
      for (const state of previous) {
        if (state.inert) state.element.setAttribute("inert", "");
        else state.element.removeAttribute("inert");
        if (state.ariaHidden === null) state.element.removeAttribute("aria-hidden");
        else state.element.setAttribute("aria-hidden", state.ariaHidden);
      }
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, []);

  return createPortal(
    <div
      className={`drawer-scrim ${scrimClassName}`.trim()}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className={className}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        ref={drawerRef}
        tabIndex={-1}
      >
        <button className="drawer-close" onClick={onClose} aria-label={closeLabel}>
          ×
        </button>
        {children}
      </aside>
    </div>,
    document.body,
  );
}

function LoadingScreen() {
  return (
    <CenterState live="polite">
      <img
        className="brand-mark"
        src="/static/core/brand/maru_square_logo_no_text.png"
        alt="Maru"
      />
      <div className="loading-line" />
      <p>Opening your convention workspace…</p>
    </CenterState>
  );
}

function ErrorScreen({ message }: { message: string }) {
  return (
    <CenterState>
      <img
        className="brand-mark"
        src="/static/core/brand/maru_square_logo_no_text.png"
        alt="Maru"
      />
      <h1>We couldn’t open your workspace</h1>
      <PageHelp
        purpose="This page explains why the workspace could not load."
        examples="check the message below, then retry after the problem is resolved"
      />
      <p>{message}</p>
      <button className="primary-button" onClick={() => window.location.reload()}>
        Try again
      </button>
    </CenterState>
  );
}

function EmptyContext({ context }: { context: MyContext }) {
  return (
    <CenterState>
      <img
        className="brand-mark"
        src="/static/core/brand/maru_square_logo_no_text.png"
        alt="Maru"
      />
      <p className="eyebrow">Signed in as {accountLabel(context)}</p>
      <h1>No convention workspace yet</h1>
      <PageHelp
        purpose="This page shows when your account has no convention relationship."
        examples="ask an organizer to add you, or sign out and use another account"
      />
      <p>
        Your account is active, but it is not participating in an event edition.
        Ask an organizer to add the appropriate relationship.
      </p>
      {context.can_access_advanced_records && (
        <a className="primary-button" href="/admin/">
          Open Specialist records
        </a>
      )}
      <button
        className="secondary-button"
        onClick={() =>
          document.querySelector<HTMLFormElement>("#maru-logout-form")?.submit()
        }
      >
        Sign out
      </button>
    </CenterState>
  );
}

function UnsupportedEditionContext({ edition }: { edition: EditionContext }) {
  return (
    <CenterState>
      <img
        className="brand-mark"
        src="/static/core/brand/maru_square_logo_no_text.png"
        alt="Maru"
      />
      <p className="eyebrow">{edition.edition_name}</p>
      <h1>Workspace unavailable in this release</h1>
      <p>
        The {edition.adoption_profile_label} profile returned no destination this
        Staff Console can present. No broader convention workflow was assumed.
      </p>
      <p className="muted-copy">
        Choose another convention workspace or ask an administrator to confirm
        the edition profile and application version.
      </p>
    </CenterState>
  );
}

function Sidebar({
  destination,
  edition,
  onNavigate,
  canManageAccess,
  canAccessAdvancedRecords,
  onOpenAccess,
}: {
  destination: Destination;
  edition: EditionContext;
  onNavigate: (destination: Destination) => void;
  canManageAccess: boolean;
  canAccessAdvancedRecords: boolean;
  onOpenAccess: () => void;
}) {
  const available = new Set(edition.available_destinations);
  const hasOverview = available.has("today") || available.has("my-registration");
  const hasPeopleAndAccess =
    available.has("people") || available.has("workforce") || canManageAccess;
  const hasSetup = available.has("setup");
  const hasAccount = available.has("security");
  const hasConventionWideOperations =
    available.has("people") &&
    available.has("commerce") &&
    available.has("reports");
  return (
    <aside className="sidebar">
      <a className="brand" href="/admin/" aria-label="Maru administration home">
        <img
          className="brand-mark"
          src="/static/core/brand/maru_square_logo_no_text.png"
          alt=""
        />
        <span>
          <strong>Maru</strong>
          <small>Convention work</small>
        </span>
      </a>

      <nav className="primary-nav" aria-label="Convention work">
        {hasOverview && (
          <details className="nav-section" open>
            <summary>Overview</summary>
            {available.has("today") && (
              <button
                className={
                  destination === "today" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "today" ? "page" : undefined}
                onClick={() => onNavigate("today")}
              >
                <Icon>◌</Icon> Today
              </button>
            )}
            {available.has("my-registration") && (
              <button
                className={
                  destination === "my-registration"
                    ? "nav-item active"
                    : "nav-item"
                }
                aria-current={
                  destination === "my-registration" ? "page" : undefined
                }
                onClick={() => onNavigate("my-registration")}
              >
                <Icon>◇</Icon> My registration
              </button>
            )}
          </details>
        )}

        {hasPeopleAndAccess && (
          <details className="nav-section" open>
            <summary>People &amp; access</summary>
            {available.has("people") && (
              <button
                className={
                  destination === "people" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "people" ? "page" : undefined}
                onClick={() => onNavigate("people")}
              >
                <Icon>◎</Icon> People
              </button>
            )}
            {available.has("workforce") && (
              <button
                className={
                  destination === "workforce" ? "nav-item active" : "nav-item"
                }
                aria-current={
                  destination === "workforce" ? "page" : undefined
                }
                onClick={() => onNavigate("workforce")}
              >
                <Icon>⌘</Icon> Workforce
              </button>
            )}
            {canManageAccess && (
              <button className="nav-item" onClick={onOpenAccess}>
                <Icon>⌁</Icon> Access
              </button>
            )}
          </details>
        )}

        {(available.has("commerce") || available.has("reports")) && (
          <details className="nav-section" open>
            <summary>Registration &amp; attendees</summary>
            {available.has("commerce") && (
              <button
                className={
                  destination === "commerce" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "commerce" ? "page" : undefined}
                onClick={() => onNavigate("commerce")}
              >
                <Icon>▣</Icon> Registration desk
              </button>
            )}
            {available.has("reports") && (
              <button
                className={
                  destination === "reports" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "reports" ? "page" : undefined}
                onClick={() => onNavigate("reports")}
              >
                <Icon>▥</Icon> Reports &amp; badges
              </button>
            )}
          </details>
        )}

        {hasSetup && (
          <details className="nav-section">
            <summary>Convention setup</summary>
            {available.has("setup") && (
              <button
                className={
                  destination === "setup" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "setup" ? "page" : undefined}
                onClick={() => onNavigate("setup")}
              >
                <Icon>✓</Icon> Setup guide
              </button>
            )}
            {available.has("setup") && canAccessAdvancedRecords && (
              <a
                className="nav-item"
                href="/admin/?records=open#maru-specialist-heading"
              >
                <Icon>↗</Icon> Specialist records
              </a>
            )}
          </details>
        )}

        {hasAccount && (
          <details className="nav-section">
            <summary>My account</summary>
            {available.has("security") && (
              <button
                className={
                  destination === "security" ? "nav-item active" : "nav-item"
                }
                aria-current={destination === "security" ? "page" : undefined}
                onClick={() => onNavigate("security")}
              >
                <Icon>◈</Icon> Security history
              </button>
            )}
          </details>
        )}

        {hasConventionWideOperations && (
          <details className="nav-section planned">
            <summary>Planned modules</summary>
            {upcomingDestinations.map((label) => (
              <span
                className="nav-item disabled"
                aria-disabled="true"
                title="Planned for a later Maru milestone"
                key={label}
              >
                <Icon>·</Icon> {label}
                <small>soon</small>
              </span>
            ))}
          </details>
        )}
      </nav>

      <div className="sidebar-foot">
        <span>{edition.edition_name}</span>
        <small>Maru · local</small>
      </div>
    </aside>
  );
}

function Topbar({
  context,
  edition,
  onEditionChange,
  canManageAccess,
  onOpenAccess,
}: {
  context: MyContext;
  edition: EditionContext;
  onEditionChange: (edition: EditionContext) => void;
  canManageAccess: boolean;
  onOpenAccess: () => void;
}) {
  return (
    <header className="topbar">
      <label className="edition-switcher">
        <span>Convention workspace</span>
        <select
          aria-label="Convention workspace"
          value={edition.edition_id}
          onChange={(event) => {
            const selected = context.editions.find(
              (candidate) => candidate.edition_id === event.target.value,
            );
            if (selected) onEditionChange(selected);
          }}
        >
          {context.editions.map((candidate) => (
            <option value={candidate.edition_id} key={candidate.edition_id}>
              {candidate.edition_name}
            </option>
          ))}
        </select>
      </label>
      <div className="account-menu">
        {canManageAccess && (
          <button className="secondary-button access-button" onClick={onOpenAccess}>
            Manage access
          </button>
        )}
        <span className="avatar" aria-hidden="true">
          {context.display_name.trim().charAt(0).toUpperCase() || "M"}
        </span>
        <span className="account-name">
          <strong>{accountLabel(context)}</strong>
          <small>{primaryCapacity(edition)}</small>
        </span>
        <button
          className="text-button"
          onClick={() =>
            document.querySelector<HTMLFormElement>("#maru-logout-form")?.submit()
          }
        >
          Sign out
        </button>
      </div>
    </header>
  );
}

function StatusPill({ lifecycle }: { lifecycle: string }) {
  return (
    <span className={`status-pill status-${lifecycle}`}>
      <span aria-hidden="true" />
      {lifecycleLabel(lifecycle)}
    </span>
  );
}

function PageHelp({
  purpose,
  examples,
}: {
  purpose: string;
  examples: string;
}) {
  return (
    <p className="page-help">
      {purpose} <span><strong>For example:</strong> {examples}.</span>
    </p>
  );
}

type EmbeddedPageAccessValue = {
  editionName: string;
  workspace?: AccessWorkspace;
  onOpenAccess?: () => void;
};

const EmbeddedPageAccessContext = createContext<EmbeddedPageAccessValue | null>(
  null,
);

function EmbeddedPageAccess() {
  const access = useContext(EmbeddedPageAccessContext);
  if (!access) return null;
  const effective = access.workspace?.effective_access;
  const allowedActions = effective?.actions.filter((action) => action.allowed) ?? [];

  return (
    <details className="maru-access-summary maru-embedded-page-access">
      <summary id="maru-access-heading">
        <span className="maru-access-summary__label">
          <strong>Access</strong>
          <span className="maru-access-summary__scope">
            {effective?.scope_label ?? access.editionName}
          </span>
        </span>
        <span className="maru-access-summary__policy">Scoped authority</span>
      </summary>
      <div className="maru-access-summary__body">
        <p>
          Your current platform or exact-edition authority determines what this
          page exposes. Changing the selected convention changes context only;
          it never grants access.
        </p>
        {allowedActions.length > 0 && (
          <ul className="maru-access-summary__decisions">
            {allowedActions.map((action) => (
              <li key={action.capability_code}>
                <strong>{action.label}</strong>
                <span>{action.source_label}</span>
              </li>
            ))}
          </ul>
        )}
        {access.onOpenAccess && (
          <button className="secondary-button" onClick={access.onOpenAccess}>
            Manage access
          </button>
        )}
      </div>
    </details>
  );
}

function TodayView({
  context,
  edition,
  people,
  peopleDenied,
  actions,
  actionsDenied,
  onNavigate,
}: {
  context: MyContext;
  edition: EditionContext;
  people?: ParticipationPage;
  peopleDenied: boolean;
  actions: ActionItem[];
  actionsDenied: boolean;
  onNavigate: (destination: Destination) => void;
}) {
  const countdown = daysUntil(edition.starts_on);
  const roleCounts = capacityCounts(people?.results ?? []).slice(0, 6);
  const firstName = context.display_name.trim().split(" ")[0] || "there";
  const available = new Set(edition.available_destinations);
  const hasPeople = available.has("people");
  const hasWorkforce = available.has("workforce");
  const hasSelfRegistration = available.has("my-registration");
  const hasCommerce = available.has("commerce");
  const visibleActions = actions.filter((action) =>
    isAvailableDestination(edition, action.destination),
  );

  return (
    <div className="view">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{weekdayLabel()} · convention overview</p>
          <h1>{greetingFor()}, {firstName}.</h1>
          <PageHelp
            purpose={`Use this overview to understand ${edition.edition_name} at a glance.`}
            examples="open an assigned action or review the current role mix"
          />
        </div>
        <StatusPill lifecycle={edition.lifecycle} />
      </div>
      <EmbeddedPageAccess />

      <section className="event-hero" aria-labelledby="event-heading">
        <div>
          <p className="section-kicker">Current edition</p>
          <h2 id="event-heading">{edition.edition_name}</h2>
          <p>
            {formatDateRange(edition)} · {edition.time_zone}
          </p>
          <div className="chip-row" aria-label="Your roles">
            {edition.capacities.map((capacity) => (
              <span className="role-chip" key={capacity.code}>
                {capacity.label_snapshot}
              </span>
            ))}
          </div>
        </div>
        <div className="countdown">
          <strong>
            {countdown > 0 ? countdown : countdown === 0 ? "Today" : "Past"}
          </strong>
          {countdown > 0 && <span>days to doors</span>}
        </div>
      </section>

      <section className="metric-grid" aria-label="Edition summary">
        <article>
          <span className="metric-label">
            {hasPeople ? "People in edition" : "Adoption profile"}
          </span>
          <strong>
            {hasPeople
              ? peopleDenied
                ? "—"
                : people?.count ?? "…"
              : edition.adoption_profile_label}
          </strong>
          <small>
            {hasPeople
              ? peopleDenied
                ? "Restricted for your role"
                : "Current records"
              : "Purpose-scoped workspace"}
          </small>
        </article>
        <article>
          <span className="metric-label">
            {hasPeople ? "Role types" : "Local time"}
          </span>
          <strong>
            {hasPeople
              ? peopleDenied
                ? "—"
                : roleCounts.length
              : edition.time_zone}
          </strong>
          <small>
            {hasPeople ? "Across this result set" : "Edition operating time"}
          </small>
        </article>
        <article>
          <span className="metric-label">Languages</span>
          <strong>{edition.language_codes.length}</strong>
          <small>{edition.language_codes.join(" · ").toUpperCase()}</small>
        </article>
        <article>
          <span className="metric-label">
            {hasCommerce ? "Currency" : "Workspace"}
          </span>
          <strong>
            {hasCommerce
              ? edition.currency_codes.length
              : edition.adoption_profile_label}
          </strong>
          <small>
            {hasCommerce
              ? edition.currency_codes.join(" · ")
              : "No payment destination adopted"}
          </small>
        </article>
      </section>

      <div className="dashboard-grid">
        <section className="panel" aria-labelledby="attention-heading">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Action center</p>
              <h2 id="attention-heading">
                {hasCommerce ? "What needs attention" : "Workspace next steps"}
              </h2>
            </div>
            <span className="quiet-badge">
              {hasCommerce
                ? actionsDenied
                  ? "Restricted"
                  : `${visibleActions.length} open`
                : "Focused"}
            </span>
          </div>
          {!hasCommerce ? (
            <p className="muted-copy">
              {hasWorkforce
                ? "Continue in Workforce with the Structure, assignment, Availability, and Shift tools pinned by this edition profile. Registration and payment queues are absent."
                : "Continue with the destinations pinned by this edition profile. Registration and payment queues are absent."}
            </p>
          ) : actionsDenied ? (
            <p className="muted-copy">
              No assigned-work projection is available for this role.
            </p>
          ) : visibleActions.length ? (
            <ol className="action-list">
              {visibleActions.map((action) => (
                <li key={action.key} className={`attention-${action.level}`}>
                  <div>
                    <span className="attention-level">
                      {lifecycleLabel(action.level)}
                    </span>
                    <strong>{action.title}</strong>
                    <p>{action.summary}</p>
                    <small>{action.owner_label}</small>
                  </div>
                  <button
                    className="secondary-button"
                    onClick={() =>
                      onNavigate(action.destination as Destination)
                    }
                  >
                    Open
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <div className="empty-action">
              <Icon>✓</Icon>
              <div>
                <strong>No assigned actions need attention</strong>
                <p>
                  Registration review and Front Desk work will appear here when
                  it is assigned to your role.
                </p>
              </div>
            </div>
          )}
        </section>

        {hasPeople && (
          <section className="panel" aria-labelledby="shape-heading">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">People</p>
                <h2 id="shape-heading">Edition shape</h2>
              </div>
            </div>
            {peopleDenied ? (
              <p className="muted-copy">
                Role distribution is available only to authorized staff.
              </p>
            ) : roleCounts.length ? (
              <ol className="role-counts">
                {roleCounts.map(([label, count], index) => (
                  <li key={label}>
                    <span className="rank">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span>{label}</span>
                    <strong>{count}</strong>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted-copy">No role labels have been recorded.</p>
            )}
          </section>
        )}
      </div>

      {(hasSelfRegistration || hasCommerce || hasWorkforce) && (
        <section className="forms-section" aria-labelledby="forms-heading">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">
                {hasSelfRegistration || hasCommerce
                  ? "Published workflows"
                  : "Workforce entry points"}
              </p>
              <h2 id="forms-heading">
                {hasSelfRegistration || hasCommerce
                  ? "Forms"
                  : "Workforce forms"}
              </h2>
              <p className="muted-copy">
                {hasSelfRegistration || hasCommerce
                  ? "Registration and the other workflows pinned by this edition profile stay together here. Newly published forms will appear in this section."
                  : "Volunteer applications and onboarding documents stay together here without creating attendee registration or payment work."}
              </p>
            </div>
          </div>
          <div className="form-card-grid">
            {hasSelfRegistration && (
              <button
                className="form-link-card"
                onClick={() => onNavigate("my-registration")}
              >
                <span className="form-card-icon" aria-hidden="true">◇</span>
                <span>
                  <strong>Attendee registration</strong>
                  <small>Open your registration and payment status</small>
                </span>
                <span aria-hidden="true">→</span>
              </button>
            )}
            {hasCommerce && (
              <a
                className="form-link-card"
                href={`/admin/registration-assist/${edition.edition_id}/`}
              >
                <span className="form-card-icon" aria-hidden="true">+</span>
                <span>
                  <strong>Registration staff intake</strong>
                  <small>Add an attendee outside public opening hours</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            )}
            {hasWorkforce && (
              <a
                className="form-link-card"
                href={`/volunteer/${edition.edition_id}/`}
              >
                <span className="form-card-icon" aria-hidden="true">♡</span>
                <span>
                  <strong>Volunteer applications</strong>
                  <small>Apply for published convention positions</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            )}
            {hasWorkforce && (
              <a
                className="form-link-card"
                href={`/volunteer/${edition.edition_id}/documents/`}
              >
                <span className="form-card-icon" aria-hidden="true">▤</span>
                <span>
                  <strong>Onboarding documents</strong>
                  <small>Submit requested agreements and files</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function PersonDrawer({
  person,
  onClose,
}: {
  person: Participation;
  onClose: () => void;
}) {
  return (
    <ModalDrawer
      className="person-drawer"
      labelledBy="person-name"
      closeLabel="Close person details"
      onClose={onClose}
    >
        <span className="person-monogram" aria-hidden="true">
          {person.display_name.charAt(0).toUpperCase()}
        </span>
        <p className="section-kicker">Participation summary</p>
        <h2 id="person-name">{person.display_name}</h2>
        <StatusPill lifecycle={person.participation_status} />
        <dl>
          <dt>Edition roles</dt>
          <dd>
            <div className="chip-row">
              {person.capacity_labels.length ? (
                person.capacity_labels.map((label) => (
                  <span className="role-chip" key={label}>
                    {label}
                  </span>
                ))
              ) : (
                <span>No active role labels</span>
              )}
            </div>
          </dd>
        </dl>
        <p className="privacy-note">
          This workspace shows only the fields permitted by your staff-summary
          capability. Contact details and sensitive records are intentionally
          outside this view.
        </p>
    </ModalDrawer>
  );
}

function PeopleView({
  page,
  denied,
  loading,
  filters,
  onApplyFilters,
  onPage,
}: {
  page?: ParticipationPage;
  denied: boolean;
  loading: boolean;
  filters: ParticipationFilters;
  onApplyFilters: (filters: ParticipationFilters) => void;
  onPage: (page: number) => void;
}) {
  const [search, setSearch] = useState(filters.search ?? "");
  const [capacity, setCapacity] = useState(filters.capacity ?? "");
  const [status, setStatus] = useState(filters.status ?? "");
  const [selected, setSelected] = useState<Participation>();
  const roleOptions = useMemo(
    () =>
      [...new Set(page?.results.flatMap((person) => person.capacity_labels) ?? [])]
        .sort()
        .map((label) => [label, label]),
    [page],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    onApplyFilters({
      search: search.trim() || undefined,
      capacity: capacity || undefined,
      status: status || undefined,
      page: 1,
    });
  }

  if (denied) {
    return (
      <div className="view">
        <div className="page-heading compact">
          <div>
            <p className="eyebrow">Edition directory</p>
            <h1>People</h1>
            <PageHelp
              purpose="Use this page to find who is participating in the edition."
              examples="search a display name or filter by role and status"
            />
          </div>
        </div>
        <EmbeddedPageAccess />
        <section className="permission-state">
          <span className="permission-lock" aria-hidden="true">◇</span>
          <h2>People summaries aren’t available for your role</h2>
          <p>
            Maru didn’t expose names, counts, filters, or existence details.
            Ask an organizer if this workspace is needed for your duties.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Edition directory</p>
          <h1>People</h1>
          <PageHelp
            purpose="Use this page to find who is participating and how they are involved."
            examples="search a display name or filter by role and status"
          />
        </div>
        <span className="record-count">{page?.count ?? 0} people</span>
      </div>
      <EmbeddedPageAccess />

      <form className="filter-bar" onSubmit={submit} role="search">
        <label className="search-field">
          <span className="sr-only">Search by display name</span>
          <Icon>⌕</Icon>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by display name"
          />
        </label>
        <label>
          <span className="sr-only">Filter by role</span>
          <select
            value={capacity}
            onChange={(event) => setCapacity(event.target.value)}
          >
            <option value="">All roles</option>
            {roleOptions.map(([value, label]) => (
              <option value={value} key={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Filter by participation status</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="interested">Interested</option>
            <option value="pending">Pending</option>
            <option value="confirmed">Confirmed</option>
            <option value="active">Active</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <button className="primary-button" type="submit">Apply</button>
      </form>

      <section className="people-table-wrap" aria-busy={loading}>
        {loading && <div className="table-progress" />}
        <table>
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Convention roles</th>
              <th scope="col">Status</th>
              <th scope="col"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {page?.results.map((person) => (
              <tr key={person.account_id}>
                <td>
                  <button
                    className="person-link"
                    onClick={() => setSelected(person)}
                  >
                    <span className="table-avatar" aria-hidden="true">
                      {person.display_name.charAt(0).toUpperCase()}
                    </span>
                    <strong>{person.display_name}</strong>
                  </button>
                </td>
                <td>
                  <div className="table-roles">
                    {person.capacity_labels.map((label) => (
                      <span key={label}>{label}</span>
                    ))}
                  </div>
                </td>
                <td>
                  <span className="plain-status">
                    {lifecycleLabel(person.participation_status)}
                  </span>
                </td>
                <td>
                  <button
                    className="row-open"
                    aria-label={`Open ${person.display_name}`}
                    onClick={() => setSelected(person)}
                  >
                    →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && page?.results.length === 0 && (
          <div className="table-empty">
            <strong>No people match this view</strong>
            <span>Try removing a filter or using a shorter name.</span>
          </div>
        )}
      </section>

      <div className="pagination" aria-label="People pages">
        <span>
          Showing {page?.results.length ?? 0} of {page?.count ?? 0}
        </span>
        <div>
          <button
            className="secondary-button"
            disabled={!page?.previous || loading}
            onClick={() => onPage(Math.max(1, (filters.page ?? 1) - 1))}
          >
            Previous
          </button>
          <button
            className="secondary-button"
            disabled={!page?.next || loading}
            onClick={() => onPage((filters.page ?? 1) + 1)}
          >
            Next
          </button>
        </div>
      </div>

      {selected && (
        <PersonDrawer person={selected} onClose={() => setSelected(undefined)} />
      )}
    </div>
  );
}

function countryLabel(countryCode: string): string {
  if (!countryCode || countryCode === "unknown") return "Not supplied";
  const label =
    new Intl.DisplayNames(undefined, { type: "region" }).of(countryCode) ??
    countryCode;
  return `${label} (${countryCode})`;
}

function ReportsView({ edition }: { edition: EditionContext }) {
  const [report, setReport] = useState<AttendeeReport>();
  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<AttendeeReportFilters>({ page: 1 });
  const [search, setSearch] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [level, setLevel] = useState("");

  useEffect(() => {
    setLoading(true);
    setDenied(false);
    setError("");
    void loadAttendeeReport(edition, filters)
      .then(setReport)
      .catch((loadError: unknown) => {
        if (loadError instanceof ApiError && loadError.status === 403) {
          setDenied(true);
          setReport(undefined);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "The attendee report could not be loaded.",
        );
      })
      .finally(() => setLoading(false));
  }, [edition, filters]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setFilters({
      search: search.trim() || undefined,
      country_code: countryCode || undefined,
      level: level || undefined,
      page: 1,
    });
  }

  if (denied) {
    return (
      <div className="view">
        <div className="page-heading compact">
          <div>
            <p className="eyebrow">Purpose-limited reporting</p>
            <h1>Attendees and badges</h1>
            <PageHelp
              purpose="Use this page for attendance counts, country summaries, and badge preparation."
              examples="check how many confirmed attendees are coming or export badge-ready data"
            />
          </div>
        </div>
        <EmbeddedPageAccess />
        <section className="permission-state">
          <span className="permission-lock" aria-hidden="true">▥</span>
          <h2>Attendee reporting isn’t available for your role</h2>
          <p>
            Maru did not expose names, totals, countries, filters, or exports.
            Ask an organizer for the attendee-reporting capability if this is
            part of your convention duties.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Purpose-limited reporting</p>
          <h1>Attendees and badges</h1>
          <PageHelp
            purpose="Use this page to answer attendance questions and prepare a minimized badge-data file."
            examples="compare countries, filter volunteers, or download a CSV for badge generation"
          />
        </div>
        <a
          className="primary-button export-link"
          href={badgeExportPath(edition, filters)}
          download
        >
          Download badge CSV
        </a>
      </div>
      <EmbeddedPageAccess />

      {error && <p className="inline-error" role="alert">{error}</p>}

      <section className="metric-grid report-metrics" aria-label="Attendance summary">
        <article>
          <span className="metric-label">Coming</span>
          <strong>{report?.summary.coming ?? "…"}</strong>
          <small>Confirmed and checked in</small>
        </article>
        <article>
          <span className="metric-label">Countries</span>
          <strong>{report?.summary.countries ?? "…"}</strong>
          <small>Registration address country</small>
        </article>
        <article>
          <span className="metric-label">Volunteers</span>
          <strong>{report?.summary.volunteers ?? "…"}</strong>
          <small>Active or proposed capacity</small>
        </article>
        <article>
          <span className="metric-label">Approved photos</span>
          <strong>{report?.summary.approved_profile_photos ?? "…"}</strong>
          <small>Ready for authorized badge use</small>
        </article>
      </section>

      <div className="report-grid">
        <section className="panel report-breakdown">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Country breakdown</p>
              <h2>Where attendees registered from</h2>
            </div>
          </div>
          <ol>
            {report?.summary.country_breakdown.map((country) => (
              <li key={country.country_code}>
                <span>{countryLabel(country.country_code)}</span>
                <strong>{country.count}</strong>
                <small>{country.percentage}%</small>
              </li>
            ))}
          </ol>
        </section>
        <section className="panel report-breakdown">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Attendee levels</p>
              <h2>Badge and directory labels</h2>
            </div>
          </div>
          <ol>
            {report?.summary.level_breakdown.map((item) => (
              <li key={item.code}>
                <span className={`report-level tone-${item.tone}`}>
                  {item.label}
                </span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <div className="report-section-heading">
        <div>
          <p className="eyebrow">Badge preparation</p>
          <h2>Data preview</h2>
          <p>
            This preview and export include confirmed or checked-in attendees
            only. Payment details, legal names, full addresses, and internal
            comments are excluded.
          </p>
        </div>
        <span className="record-count">{report?.count ?? 0} records</span>
      </div>

      <form className="filter-bar" onSubmit={applyFilters} role="search">
        <label className="search-field">
          <span className="sr-only">Search badge name or reference</span>
          <Icon>⌕</Icon>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Badge name, display name, or reference"
          />
        </label>
        <label>
          <span className="sr-only">Filter by country</span>
          <select
            value={countryCode}
            onChange={(event) => setCountryCode(event.target.value)}
          >
            <option value="">All countries</option>
            {report?.summary.country_breakdown.map((country) => (
              <option key={country.country_code} value={country.country_code}>
                {countryLabel(country.country_code)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Filter by attendee level</span>
          <select value={level} onChange={(event) => setLevel(event.target.value)}>
            <option value="">All attendee levels</option>
            {report?.summary.level_breakdown.map((item) => (
              <option key={item.code} value={item.code}>{item.label}</option>
            ))}
          </select>
        </label>
        <button className="primary-button" type="submit">Apply</button>
      </form>

      <section className="people-table-wrap" aria-busy={loading}>
        {loading && <div className="table-progress" />}
        <table className="report-table">
          <thead>
            <tr>
              <th scope="col">Badge name</th>
              <th scope="col">Pronouns</th>
              <th scope="col">Languages</th>
              <th scope="col">Country</th>
              <th scope="col">Attendee level</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {report?.results.map((row) => (
              <tr key={row.registration_id}>
                <td>
                  <strong>{row.badge_name}</strong>
                  <small className="cell-note">{row.reference}</small>
                </td>
                <td>{row.pronouns || "—"}</td>
                <td>{row.spoken_languages.join(", ") || "—"}</td>
                <td>{row.country_code || "—"}</td>
                <td>
                  <div className="report-levels">
                    {row.attendance_labels.map((item) => (
                      <span
                        className={`report-level tone-${item.tone}`}
                        key={item.code}
                      >
                        {item.label}
                      </span>
                    ))}
                  </div>
                </td>
                <td><StatusPill lifecycle={row.registration_state} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && report?.results.length === 0 && (
          <div className="table-empty">
            <strong>No badge records match these filters</strong>
            <span>Try clearing a country, level, or search value.</span>
          </div>
        )}
      </section>

      <div className="pagination" aria-label="Badge data pages">
        <span>
          Showing {report?.results.length ?? 0} of {report?.count ?? 0}
          {report ? ` · Generated ${formatDateTime(report.generated_at)}` : ""}
        </span>
        <div>
          <button
            className="secondary-button"
            disabled={!report?.has_previous || loading}
            onClick={() =>
              setFilters((current) => ({
                ...current,
                page: Math.max(1, (current.page ?? 1) - 1),
              }))
            }
          >
            Previous
          </button>
          <button
            className="secondary-button"
            disabled={!report?.has_next || loading}
            onClick={() =>
              setFilters((current) => ({
                ...current,
                page: (current.page ?? 1) + 1,
              }))
            }
          >
            Next
          </button>
        </div>
      </div>
      <p className="privacy-note">
        Counts use the registration profile’s internal two-letter country,
        scoped to this edition. The public attendee directory uses a separate,
        optional country value and never inherits this address field.
      </p>
    </div>
  );
}

function formatMoney(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
  }).format(amountMinor / 100);
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function questionOptions(question: RegistrationQuestion): string[] {
  return Array.isArray(question.options)
    ? question.options.filter(
        (option): option is string => typeof option === "string",
      )
    : [];
}

function answerConditionValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number" || typeof value === "string") {
    return String(value);
  }
  return "";
}

function RegistrationQuestionField({
  question,
  value,
  onChange,
}: {
  question: RegistrationQuestion;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const id = `registration-${question.key}`;
  const options = questionOptions(question);
  let control: ReactNode;

  if (question.field_type === "boolean") {
    control = (
      <select
        id={id}
        value={
          typeof value === "boolean" ? (value ? "true" : "false") : ""
        }
        onChange={(event) =>
          onChange(
            event.target.value === ""
              ? undefined
              : event.target.value === "true",
          )
        }
        required={question.required}
      >
        <option value="">Choose one</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  } else if (question.field_type === "single_choice") {
    control = (
      <select
        id={id}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value || undefined)}
        required={question.required}
      >
        <option value="">Choose one</option>
        {options.map((option) => (
          <option value={option} key={option}>{option}</option>
        ))}
      </select>
    );
  } else if (question.field_type === "multiple_choice") {
    const selected = Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
    control = (
      <div className="choice-grid" id={id}>
        {options.map((option) => (
          <label key={option}>
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...selected, option]
                    : selected.filter((item) => item !== option),
                )
              }
            />
            {option}
          </label>
        ))}
      </div>
    );
  } else if (question.field_type === "long_text") {
    control = (
      <textarea
        id={id}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
        required={question.required}
        rows={4}
      />
    );
  } else {
    control = (
      <input
        id={id}
        type={question.field_type === "integer" ? "number" : "text"}
        value={
          typeof value === "string" || typeof value === "number" ? value : ""
        }
        onChange={(event) =>
          onChange(
            question.field_type === "integer"
              ? event.target.value === ""
                ? undefined
                : Number.parseInt(event.target.value, 10)
              : event.target.value,
          )
        }
        required={question.required}
      />
    );
  }

  return (
    <div className="form-field">
      <label htmlFor={id}>
        {question.label}
        {question.required && <span aria-label="required"> *</span>}
      </label>
      {question.help_text && <p>{question.help_text}</p>}
      {control}
      <small>
        Why Maru asks: {question.purpose} · {question.classification}
      </small>
    </div>
  );
}

function ProfileExtensionInput({
  field,
  value,
  onChange,
}: {
  field: ProfileExtensionField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const common = {
    id: `profile-extension-${field.id}`,
    disabled: !field.can_write,
  };
  if (field.field_type === "boolean") {
    return (
      <select
        {...common}
        value={value === true ? "true" : value === false ? "false" : ""}
        onChange={(event) =>
          onChange(
            event.target.value === ""
              ? undefined
              : event.target.value === "true",
          )
        }
      >
        <option value="">Choose</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }
  if (field.field_type === "single_choice") {
    return (
      <select
        {...common}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Choose</option>
        {field.options.map((option) => (
          <option value={option} key={option}>{option}</option>
        ))}
      </select>
    );
  }
  if (field.field_type === "multiple_choice") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <div className="checkbox-list" id={common.id}>
        {field.options.map((option) => (
          <label key={option}>
            <input
              type="checkbox"
              disabled={common.disabled}
              checked={selected.includes(option)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...selected, option]
                    : selected.filter((item) => item !== option),
                )
              }
            />
            {option}
          </label>
        ))}
      </div>
    );
  }
  if (field.field_type === "long_text") {
    return (
      <textarea
        {...common}
        rows={4}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return (
    <input
      {...common}
      type={field.field_type === "integer" ? "number" : "text"}
      value={
        typeof value === "string" || typeof value === "number"
          ? value
          : ""
      }
      onChange={(event) =>
        onChange(
          field.field_type === "integer" && event.target.value !== ""
            ? Number(event.target.value)
            : event.target.value,
        )
      }
    />
  );
}

function ProfileExtensionsPanel({ edition }: { edition: EditionContext }) {
  const [workspace, setWorkspace] = useState<ProfileExtensionWorkspace>();
  const [drafts, setDrafts] = useState<Record<string, unknown>>({});
  const [busyField, setBusyField] = useState<string>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    setWorkspace(undefined);
    setDrafts({});
    setError(undefined);
    void loadMyProfileExtensions(edition)
      .then((loaded) => {
        setWorkspace(loaded);
        setDrafts(
          Object.fromEntries(
            loaded.fields.map((field) => [field.id, field.current_value]),
          ),
        );
      })
      .catch((caught: unknown) =>
        setError(
          caught instanceof Error
            ? caught.message
            : "Additional profile fields could not be loaded.",
        ),
      );
  }, [edition]);

  async function save(field: ProfileExtensionField) {
    setBusyField(field.id);
    setError(undefined);
    try {
      const loaded = await writeMyProfileExtension(
        edition,
        field.id,
        drafts[field.id],
      );
      setWorkspace(loaded);
      setDrafts(
        Object.fromEntries(
          loaded.fields.map((item) => [item.id, item.current_value]),
        ),
      );
    } catch (caught: unknown) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The profile detail could not be saved.",
      );
    } finally {
      setBusyField(undefined);
    }
  }

  if (!workspace && !error) {
    return (
      <section className="panel profile-extensions-panel">
        <p className="muted-copy">Checking for additional profile details…</p>
      </section>
    );
  }
  if (error && !workspace) return null;
  if (!workspace?.fields.length) {
    return (
      <section className="panel profile-extensions-panel">
        <div className="panel-heading">
          <h2>Additional profile details</h2>
        </div>
        <p className="muted-copy">
          This convention has not requested any additional current information.
        </p>
      </section>
    );
  }
  return (
    <section className="panel profile-extensions-panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Current information</p>
          <h2>Additional profile details</h2>
        </div>
        <span className="quiet-badge">Submission stays unchanged</span>
      </div>
      <p className="muted-copy">
        Organizers can request a missing detail after registration. Saving here
        adds a revision to your current profile; it never rewrites the form you
        originally submitted.
      </p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="profile-extension-fields">
        {workspace.fields.map((field) => (
          <div className="form-field" key={field.id}>
            <label htmlFor={`profile-extension-${field.id}`}>
              {field.label}{field.required ? " *" : ""}
            </label>
            <ProfileExtensionInput
              field={field}
              value={drafts[field.id]}
              onChange={(value) =>
                setDrafts((current) => ({ ...current, [field.id]: value }))
              }
            />
            <small>
              {field.help_text ? `${field.help_text} ` : ""}
              Purpose: {field.purpose}
              {!field.can_write ? " Registration staff maintains this field." : ""}
            </small>
            {field.can_write && (
              <button
                type="button"
                className="secondary-button"
                disabled={busyField !== undefined}
                onClick={() => void save(field)}
              >
                {busyField === field.id ? "Saving…" : "Save detail"}
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function MyRegistrationView({ edition }: { edition: EditionContext }) {
  const [workspace, setWorkspace] = useState<MyRegistrationWorkspace>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [productId, setProductId] = useState("");
  const [answers, setAnswers] = useState<Record<string, unknown>>({});

  useEffect(() => {
    setLoading(true);
    setError(undefined);
    setAnswers({});
    void loadMyRegistration(edition)
      .then((loaded) => {
        setWorkspace(loaded);
        setProductId(loaded.configuration?.products[0]?.id ?? "");
      })
      .catch((loadError: unknown) => {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Registration could not be opened.",
        );
      })
      .finally(() => setLoading(false));
  }, [edition]);

  const visibleQuestions =
    workspace?.configuration?.questions.filter(
      (question) =>
        !question.condition_question_key ||
        answerConditionValue(answers[question.condition_question_key]) ===
          question.condition_value,
    ) ?? [];

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!productId) return;
    setBusy(true);
    setError(undefined);
    try {
      const registration = await submitMyRegistration(
        edition,
        productId,
        answers,
      );
      setWorkspace((current) =>
        current ? { ...current, registration } : current,
      );
    } catch (submitError: unknown) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Registration could not be submitted.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function completeDemoPayment() {
    const registration = workspace?.registration;
    if (!registration) return;
    setBusy(true);
    setError(undefined);
    try {
      const paid = await confirmMyDemoPayment(
        edition,
        registration.id,
      );
      setWorkspace((current) =>
        current ? { ...current, registration: paid } : current,
      );
    } catch (paymentError: unknown) {
      setError(
        paymentError instanceof Error
          ? paymentError.message
          : "The demo payment could not be confirmed.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="view">
        <p className="lede">Opening your registration…</p>
      </div>
    );
  }

  if (error && !workspace) {
    return (
      <div className="view">
        <section className="permission-state">
          <h1>My registration</h1>
          <PageHelp
            purpose="Use this page to manage your attendee registration for the selected edition."
            examples="choose an admission product or review your current status"
          />
          <p>{error}</p>
        </section>
      </div>
    );
  }

  const registration = workspace?.registration;
  const configuration = workspace?.configuration;
  if (registration) {
    return (
      <div className="view">
        <div className="page-heading compact">
          <div>
            <p className="eyebrow">Personal convention journey</p>
            <h1>My registration</h1>
            <PageHelp
              purpose={`Use this page to track your admission for ${edition.edition_name}.`}
              examples="complete payment, copy your reference, or review your timeline"
            />
          </div>
          <StatusPill lifecycle={registration.state} />
        </div>
        <EmbeddedPageAccess />
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="registration-layout">
          <section className="panel registration-summary">
            <p className="section-kicker">Admission</p>
            <h2>{registration.product_name}</h2>
            <dl className="summary-list">
              <div>
                <dt>Reference</dt>
                <dd>{registration.reference}</dd>
              </div>
              <div>
                <dt>Amount</dt>
                <dd>{formatMoney(registration.amount_minor, registration.currency)}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{lifecycleLabel(registration.state)}</dd>
              </div>
            </dl>
            {registration.state === "payment_pending" &&
              workspace?.demo_payment_enabled && (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => void completeDemoPayment()}
                >
                  {busy ? "Confirming…" : "Complete demo payment"}
                </button>
              )}
            {registration.entitlements.length > 0 && (
              <div className="entitlement-card">
                <strong>Active entitlement</strong>
                {registration.entitlements.map((entitlement) => (
                  <span key={entitlement.code}>
                    {entitlement.label_snapshot}
                  </span>
                ))}
              </div>
            )}
          </section>
          <section className="panel">
            <p className="section-kicker">Operational history</p>
            <h2>Your timeline</h2>
            <ol className="timeline-list">
              {registration.timeline.map((entry) => (
                <li key={entry.id}>
                  <strong>{entry.title}</strong>
                  <p>{entry.summary}</p>
                  <time dateTime={entry.occurred_at}>
                    {formatDateTime(entry.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          </section>
        </div>
        <ProfileExtensionsPanel edition={edition} />
      </div>
    );
  }

  if (!configuration) {
    return (
      <div className="view">
        <section className="permission-state">
          <h1>Registration is not open</h1>
          <PageHelp
            purpose="This page will hold your attendee registration when the edition opens it."
            examples="return after an organizer activates a registration version"
          />
          <p>This convention has no active attendee registration setup yet.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Personal convention journey</p>
          <h1>Register for {edition.edition_name}</h1>
          <PageHelp
            purpose="Use this page to choose admission and submit the questions defined for this convention."
            examples="select Sponsor admission and answer only the questions that apply to you"
          />
        </div>
      </div>
      <EmbeddedPageAccess />
      {error && <p className="form-error" role="alert">{error}</p>}
      <form className="registration-form" onSubmit={(event) => void submit(event)}>
        <section className="panel">
          <p className="section-kicker">Admission</p>
          <h2>Choose your registration</h2>
          <div className="product-grid">
            {configuration.products
              .filter((product) => product.status === "available")
              .map((product) => (
                <label
                  className={
                    productId === product.id
                      ? "product-option selected"
                      : "product-option"
                  }
                  key={product.id}
                >
                  <input
                    type="radio"
                    name="product"
                    value={product.id}
                    checked={productId === product.id}
                    onChange={() => setProductId(product.id)}
                  />
                  <strong>{product.name}</strong>
                  <span>{product.description}</span>
                  <b>{formatMoney(product.price_minor, configuration.currency)}</b>
                </label>
              ))}
          </div>
        </section>
        <section className="panel question-panel">
          <p className="section-kicker">About your registration</p>
          <h2>Convention questions</h2>
          {visibleQuestions.map((question) => (
            <RegistrationQuestionField
              question={question}
              value={answers[question.key]}
              onChange={(value) =>
                setAnswers((current) => {
                  const next = { ...current };
                  if (value === undefined) delete next[question.key];
                  else next[question.key] = value;
                  return next;
                })
              }
              key={question.id}
            />
          ))}
        </section>
        <div className="form-actions">
          <p>
            Answers are retained with this exact form version and are visible only
            according to each question’s stated purpose.
          </p>
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit registration"}
          </button>
        </div>
      </form>
    </div>
  );
}

function RegistrationTimeline({
  registration,
}: {
  registration: StaffRegistration;
}) {
  return (
    <ol className="timeline-list compact">
      {registration.timeline.map((entry) => (
        <li key={entry.id}>
          <strong>{entry.title}</strong>
          <p>{entry.summary}</p>
          <time dateTime={entry.occurred_at}>
            {formatDateTime(entry.occurred_at)}
          </time>
        </li>
      ))}
    </ol>
  );
}

function RegistrationQueue({
  page,
  denied,
  loading,
  filters,
  onApplyFilters,
  onPage,
  onOpen,
}: {
  page?: StaffRegistrationPage;
  denied: boolean;
  loading: boolean;
  filters: StaffRegistrationFilters;
  onApplyFilters: (filters: StaffRegistrationFilters) => void;
  onPage: (page: number) => void;
  onOpen: (registration: StaffRegistration) => void;
}) {
  const [search, setSearch] = useState(filters.search ?? "");
  const [state, setState] = useState(filters.state ?? "");

  useEffect(() => {
    setSearch(filters.search ?? "");
    setState(filters.state ?? "");
  }, [filters.search, filters.state]);

  function submit(event: FormEvent) {
    event.preventDefault();
    onApplyFilters({
      search: search.trim() || undefined,
      state: state || undefined,
      page: 1,
    });
  }

  if (denied) {
    return (
      <section className="permission-state">
        <h2>Registration service is not available for your role</h2>
        <p>
          Maru did not expose attendee names, counts, payment state, or
          registration existence.
        </p>
      </section>
    );
  }

  return (
    <section className="attendee-queue" aria-labelledby="attendee-queue-title">
      <div className="panel-heading attendee-queue-heading">
        <div>
          <p className="section-kicker">Attendee queue</p>
          <h2 id="attendee-queue-title">Find an attendee</h2>
        </div>
        <span className="record-count">{page?.count ?? 0} attendees</span>
      </div>
      <form className="filter-bar" onSubmit={submit} role="search">
        <label className="search-field">
          <span className="sr-only">Search attendee name or reference</span>
          <Icon>⌕</Icon>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Name or registration reference"
          />
        </label>
        <label>
          <span className="sr-only">Filter by registration state</span>
          <select
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            <option value="">All states</option>
            <option value="guardian_pending">Guardian consent pending</option>
            <option value="waitlisted">Waitlisted</option>
            <option value="payment_pending">Payment pending</option>
            <option value="confirmed">Confirmed</option>
            <option value="checked_in">Checked in</option>
            <option value="expired">Payment expired</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <button className="primary-button" type="submit">Apply</button>
      </form>
      <div className="people-table-wrap commerce-table" aria-busy={loading}>
        {loading && <div className="table-progress" />}
        <table className="attendee-table">
          <thead>
            <tr>
              <th scope="col">Attendee</th>
              <th scope="col">Reference</th>
              <th scope="col">Admission</th>
              <th scope="col">State</th>
              <th scope="col"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {page?.results.map((registration) => (
              <tr key={registration.id}>
                <td data-label="Attendee">
                  <button
                    className="person-link"
                    onClick={() => onOpen(registration)}
                  >
                    <span className="table-avatar" aria-hidden="true">
                      {registration.display_name.charAt(0).toUpperCase()}
                    </span>
                    <strong>{registration.display_name}</strong>
                  </button>
                </td>
                <td data-label="Reference">{registration.reference}</td>
                <td data-label="Admission">{registration.product_name}</td>
                <td data-label="State">
                  <StatusPill lifecycle={registration.state} />
                </td>
                <td className="attendee-row-action">
                  <button
                    className="row-open"
                    aria-label={`Open ${registration.reference}`}
                    onClick={() => onOpen(registration)}
                  >
                    <span aria-hidden="true">→</span>
                    <span className="row-open-label" aria-hidden="true">
                      Open attendee
                    </span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && page?.results.length === 0 && (
          <div className="table-empty">
            <strong>No attendees match this view</strong>
            <span>Try removing a filter or using a shorter name or reference.</span>
          </div>
        )}
      </div>
      <div className="pagination" aria-label="Attendee pages">
        <span>
          Showing {page?.results.length ?? 0} of {page?.count ?? 0}
        </span>
        <div>
          <button
            className="secondary-button"
            disabled={!page?.previous || loading}
            onClick={() => onPage(Math.max(1, (filters.page ?? 1) - 1))}
          >
            Previous
          </button>
          <button
            className="secondary-button"
            disabled={!page?.next || loading}
            onClick={() => onPage((filters.page ?? 1) + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}

type WorkforceDepartmentRow = {
  department: WorkforceStructureDepartment;
  depth: number;
};

function flattenWorkforceDepartments(
  departments: WorkforceStructureDepartment[],
  depth = 0,
): WorkforceDepartmentRow[] {
  return departments.flatMap((department) => [
    { department, depth },
    ...flattenWorkforceDepartments(department.children, depth + 1),
  ]);
}

function positionOccupancy(position: WorkforceStructurePosition): string {
  return `${position.holders.length} of ${position.headcount} assigned`;
}

function WorkforceView({ edition }: { edition: EditionContext }) {
  const assignmentUsesParticipation =
    edition.assignment_uses_participation_evidence;
  const [workspace, setWorkspace] = useState<WorkforceStructureWorkspace>();
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState<string>();
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    let current = true;
    setWorkspace(undefined);
    setDenied(false);
    setError(undefined);
    void loadWorkforceStructure(edition)
      .then((loaded) => {
        if (current) setWorkspace(loaded);
      })
      .catch((loadError: unknown) => {
        if (!current) return;
        if (loadError instanceof ApiError && loadError.status === 403) {
          setDenied(true);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "The Workforce workspace could not be loaded.",
        );
      });
    return () => {
      current = false;
    };
  }, [edition, retryVersion]);

  const departmentRows = useMemo(
    () => flattenWorkforceDepartments(workspace?.structure.departments ?? []),
    [workspace],
  );
  const positions = departmentRows.flatMap(
    ({ department }) => department.positions,
  );
  const activeAssignments = positions.reduce(
    (count, position) => count + position.holders.length,
    0,
  );
  const vacancies = positions.reduce(
    (count, position) =>
      count + Math.max(0, position.headcount - position.holders.length),
    0,
  );
  const activeDepartments = departmentRows.filter(
    ({ department }) => department.state === "active",
  ).length;

  return (
    <div className="view workforce-view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Teams &amp; volunteer operations</p>
          <h1>Workforce</h1>
          <PageHelp
            purpose="Use this page to understand how departments become staffed positions, shared availability, and workable shifts."
            examples="review a vacancy, confirm its active holder, or plan a Shift from current assignments and deliberately shared availability"
          />
        </div>
        {workspace?.structure.state === "complete" && (
          <span className="record-count">
            {positions.length} position{positions.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <EmbeddedPageAccess />

      {denied ? (
        <section className="permission-state">
          <span className="permission-lock" aria-hidden="true">◇</span>
          <h2>Workforce structure is not available for your role</h2>
          <p>
            Maru did not expose Department names, positions, assignments, or
            staffing counts. Ask an organizer for exact-edition Workforce view
            authority if this is part of your duties.
          </p>
        </section>
      ) : error ? (
        <section className="permission-state" role="alert">
          <span className="permission-lock" aria-hidden="true">!</span>
          <h2>Workforce could not be loaded</h2>
          <p>{error}</p>
          <button
            className="primary-button"
            onClick={() => setRetryVersion((current) => current + 1)}
          >
            Try again
          </button>
        </section>
      ) : !workspace ? (
        <section className="panel workforce-loading" role="status">
          <span className="table-progress" />
          <p>Loading the complete authorized Workforce structure…</p>
        </section>
      ) : (
        <>
          {workspace.structure.state === "structure_limit_exceeded" && (
            <section className="permission-state" role="alert">
              <span className="permission-lock" aria-hidden="true">!</span>
              <h2>The complete structure is too large to show safely</h2>
              <p>
                Maru did not substitute a partial hierarchy. Ask a platform
                operator to review the edition before continuing.
              </p>
            </section>
          )}

          {workspace.structure.state === "complete" && (
            <section
              className="panel workforce-journey-panel"
              aria-labelledby="workforce-journey-title"
            >
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">Operational sequence</p>
                  <h2 id="workforce-journey-title">
                    From structure to a workable rota
                  </h2>
                </div>
                <span className="quiet-badge">One connected journey</span>
              </div>
              <p className="muted-copy workforce-journey-intro">
                Each stage depends on the one before it. Maru shows implemented
                records as working steps and labels unavailable continuations
                plainly instead of presenting dead controls.
              </p>
              <ol className="workforce-journey">
                <li>
                  <span className="workforce-step-number" aria-hidden="true">
                    1
                  </span>
                  <div>
                    <span className="workforce-step-state ready">Available</span>
                    <h3>Structure</h3>
                    <p>
                      {activeDepartments} active Department
                      {activeDepartments === 1 ? "" : "s"} place accountable work
                      beneath {workspace.governance.label}.
                    </p>
                  </div>
                  <a
                    className="secondary-button"
                    href={workforceStructurePath(edition)}
                  >
                    Open structure
                  </a>
                </li>
                <li>
                  <span className="workforce-step-number" aria-hidden="true">
                    2
                  </span>
                  <div>
                    <span className="workforce-step-state ready">Available</span>
                    <h3>Positions</h3>
                    <p>
                      {positions.length} defined position
                      {positions.length === 1 ? "" : "s"} describe responsibility,
                      reporting, approved headcount, and the authority bundle an
                      appointment would receive.
                    </p>
                  </div>
                  <a
                    className="secondary-button"
                    href={
                      workspace.can_manage_positions
                        ? workforcePositionsPath(edition)
                        : "#workforce-positions-title"
                    }
                  >
                    {workspace.can_manage_positions
                      ? "Manage positions"
                      : "Review positions"}
                  </a>
                </li>
                <li>
                  <span className="workforce-step-number" aria-hidden="true">
                    3
                  </span>
                  <div>
                    <span className="workforce-step-state ready">Available</span>
                    <h3>Assignments</h3>
                    <p>
                      {activeAssignments} active assignment
                      {activeAssignments === 1 ? "" : "s"} fill those positions;{" "}
                      {vacancies} approved place
                      {vacancies === 1 ? " is" : "s are"} currently unfilled.
                      Activation remains a two-person, prerequisite-checked
                      decision.
                    </p>
                  </div>
                  <a
                    className="secondary-button"
                    href={
                      workspace.can_manage_assignments
                        ? workforceAssignmentsPath(edition)
                        : "#workforce-positions-title"
                    }
                  >
                    {workspace.can_manage_assignments
                      ? "Manage assignments"
                      : "Review active holders"}
                  </a>
                </li>
                <li className={workspace.can_view_availability ? undefined : "planned-step"}>
                  <span className="workforce-step-number" aria-hidden="true">
                    4
                  </span>
                  <div>
                    <span className={`workforce-step-state ${workspace.can_view_availability ? "ready" : "planned"}`}>
                      {workspace.can_view_availability ? "Available" : "Access required"}
                    </span>
                    <h3>Availability</h3>
                    <p>
                      Assigned people own their current workable periods and
                      decide when to share them. Private drafts remain hidden,
                      and no availability is inferred from an assignment.
                    </p>
                  </div>
                  {workspace.can_view_availability && (
                    <a
                      className="secondary-button"
                      href={workforceAvailabilityPath(edition)}
                    >
                      Review availability
                    </a>
                  )}
                </li>
                <li className={workspace.can_view_shifts ? undefined : "planned-step"}>
                  <span className="workforce-step-number" aria-hidden="true">
                    5
                  </span>
                  <div>
                    <span className={`workforce-step-state ${workspace.can_view_shifts ? "ready" : "planned"}`}>
                      {workspace.can_view_shifts ? "Available" : "Access required"}
                    </span>
                    <h3>Shifts</h3>
                    <p>
                      Position demand becomes published work, person-owned claims,
                      independently confirmed coverage, and an explicit lock.
                      Availability is checked without assigning anyone automatically.
                    </p>
                  </div>
                  {workspace.can_view_shifts && (
                    <a className="secondary-button" href={workforceShiftsPath(edition)}>
                      {workspace.can_manage_shifts ? "Plan shifts" : "Review shifts"}
                    </a>
                  )}
                </li>
              </ol>
            </section>
          )}

          {workspace.structure.state === "complete" && (
            <section className="panel workforce-positions-panel" aria-labelledby="workforce-positions-title">
              <div className="panel-heading">
                <div>
                  <p className="section-kicker">Current edition</p>
                  <h2 id="workforce-positions-title">Positions &amp; active assignments</h2>
                </div>
                <span className="quiet-badge">
                  {activeAssignments} assigned · {vacancies} vacant
                </span>
              </div>
              {positions.length ? (
                <div className="workforce-departments">
                  {departmentRows
                    .filter(({ department }) => department.positions.length > 0)
                    .map(({ department, depth }) => (
                      <section
                        className="workforce-department"
                        style={{ "--department-depth": depth } as CSSProperties}
                        aria-labelledby={`workforce-department-${department.id}`}
                        key={department.id}
                      >
                        <div className="workforce-department-heading">
                          <div>
                            <p className="section-kicker">Department</p>
                            <h3 id={`workforce-department-${department.id}`}>
                              {department.name}
                            </h3>
                          </div>
                          {department.state === "retired" && (
                            <span className="quiet-badge">Retired</span>
                          )}
                        </div>
                        <ul className="workforce-position-list">
                          {department.positions.map((position) => (
                            <li key={position.id}>
                              <div className="workforce-position-heading">
                                <div>
                                  <h4>{position.title}</h4>
                                  <p>
                                    {position.reports_to_title
                                      ? `Reports to ${position.reports_to_title}`
                                      : "Top-level operational position"}
                                  </p>
                                </div>
                                <span className={`status-pill ${position.status}`}>
                                  {lifecycleLabel(position.status)}
                                </span>
                              </div>
                              {position.description && <p>{position.description}</p>}
                              <div className="workforce-assignment-summary">
                                <strong>{positionOccupancy(position)}</strong>
                                {position.holders.length ? (
                                  <ul aria-label={`Active assignments for ${position.title}`}>
                                    {position.holders.map((holder, index) => (
                                      <li key={`${position.id}-${index}`}>
                                        {holder.display_name}
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <span>No active holder</span>
                                )}
                              </div>
                              {workspace.can_manage_positions && (
                                <a
                                  className="secondary-button workforce-position-action"
                                  href={workforcePositionsPath(edition, position.id)}
                                >
                                  Manage {position.title}
                                </a>
                              )}
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                </div>
              ) : (
                <div className="table-empty">
                  <strong>No positions have been defined</strong>
                  <span>
                    {workspace.can_manage_positions
                      ? "Create the first Position from the governed Position workspace."
                      : "An organizer with structure-management authority can define the first Position."}
                  </span>
                  {workspace.can_manage_positions && (
                    <a
                      className="secondary-button"
                      href={workforcePositionsPath(edition)}
                    >
                      Create a Position
                    </a>
                  )}
                </div>
              )}
            </section>
          )}

          <section className="panel workforce-tools" aria-labelledby="workforce-tools-title">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Continue the work</p>
                <h2 id="workforce-tools-title">Current Workforce tools</h2>
              </div>
            </div>
            <div className="workforce-tool-grid">
              <a className="form-link-card" href={workforceStructurePath(edition)}>
                <span className="form-card-icon" aria-hidden="true">⌘</span>
                <span>
                  <strong>Department structure</strong>
                  <small>Manage the exact edition-owned hierarchy</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
              {workspace.can_manage_positions && (
                <a
                  className="form-link-card"
                  href={workforcePositionsPath(edition)}
                >
                  <span className="form-card-icon" aria-hidden="true">P</span>
                  <span>
                    <strong>Position management</strong>
                    <small>
                      Define responsibilities, reporting, headcount, and public
                      opportunities
                    </small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </a>
              )}
              {workspace.can_manage_assignments && (
                <a
                  className="form-link-card"
                  href={workforceAssignmentsPath(edition)}
                >
                  <span className="form-card-icon" aria-hidden="true">A</span>
                  <span>
                    <strong>Assignment management</strong>
                    <small>
                      Propose known people, review onboarding readiness, and
                      make independently controlled decisions
                    </small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </a>
              )}
              {workspace.can_view_availability && (
                <a
                  className="form-link-card"
                  href={workforceAvailabilityPath(edition)}
                >
                  <span className="form-card-icon" aria-hidden="true">◷</span>
                  <span>
                    <strong>Availability planning</strong>
                    <small>
                      Review only current periods deliberately shared by people
                      with open assignments
                    </small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </a>
              )}
              {workspace.can_view_shifts && (
                <a className="form-link-card" href={workforceShiftsPath(edition)}>
                  <span className="form-card-icon" aria-hidden="true">S</span>
                  <span>
                    <strong>Shift planning</strong>
                    <small>
                      Publish demand, review claims, confirm coverage, and lock work
                    </small>
                  </span>
                  <span aria-hidden="true">↗</span>
                </a>
              )}
              <a className="form-link-card" href={`/volunteer/${edition.edition_id}/`}>
                <span className="form-card-icon" aria-hidden="true">♡</span>
                <span>
                  <strong>Published opportunities</strong>
                  <small>See the applicant-facing position openings</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
              <a
                className="form-link-card"
                href={`/volunteer/${edition.edition_id}/documents/`}
              >
                <span className="form-card-icon" aria-hidden="true">▤</span>
                <span>
                  <strong>My onboarding documents</strong>
                  <small>Complete agreements requested from this account</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            </div>
            {!workspace.can_manage_assignments && (
              <p className="privacy-note workforce-owner-boundary">
                {workspace.can_manage_positions
                  ? "Position management is available, but assignment decisions also require current scoped assignment and role authority."
                  : "This workspace is safe for viewing. Position editing and assignment activation require additional authority, so Maru does not link this account to inaccessible specialist screens."}
              </p>
            )}
          </section>

          <aside className="setup-note workforce-boundary" aria-labelledby="workforce-boundary-title">
            <div>
              <p className="section-kicker">Authority boundary</p>
              <h2 id="workforce-boundary-title">Appointment is not ordinary access</h2>
              <p>
                {assignmentUsesParticipation
                  ? "A Workforce assignment can require documents, headcount, a distinct approver, a scoped role, and Participation capacity."
                  : "A Workforce assignment can require documents, headcount, a distinct approver, and a scoped role. This edition profile creates no attendee Registration, attendance, payment, or Participation record."}{" "}
                Sharing a software-access group does not fill a Position.
              </p>
            </div>
          </aside>
        </>
      )}
    </div>
  );
}

function RegistrationOperationsView({ edition }: { edition: EditionContext }) {
  const [configuration, setConfiguration] =
    useState<RegistrationConfigurationWorkspace>();
  const [configurationDenied, setConfigurationDenied] = useState(false);
  const [registrations, setRegistrations] = useState<StaffRegistrationPage>();
  const [registrationsDenied, setRegistrationsDenied] = useState(false);
  const [registrationsLoading, setRegistrationsLoading] = useState(false);
  const [registrationFilters, setRegistrationFilters] =
    useState<StaffRegistrationFilters>({ page: 1 });
  const [reconciliation, setReconciliation] =
    useState<RegistrationReconciliation>();
  const [mediaReviews, setMediaReviews] =
    useState<ProfileMediaReviewItem[]>();
  const [mediaReviewsDenied, setMediaReviewsDenied] = useState(false);
  const [mediaReviewReasons, setMediaReviewReasons] = useState<
    Record<string, string>
  >({});
  const [selected, setSelected] = useState<StaffRegistration>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [templateId, setTemplateId] = useState("");
  const [sourceEditionId, setSourceEditionId] = useState("");
  const [draftId, setDraftId] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [publishName, setPublishName] = useState("");
  const [publishCode, setPublishCode] = useState("");
  const [seriesLimited, setSeriesLimited] = useState(true);
  const [exceptionReason, setExceptionReason] = useState("");
  const [newPaymentDeadline, setNewPaymentDeadline] = useState("");

  function refreshConfiguration() {
    setConfigurationDenied(false);
    void loadRegistrationConfiguration(edition)
      .then((loaded) => {
        setConfiguration(loaded);
        setTemplateId((current) => current || loaded.templates[0]?.id || "");
        setSourceEditionId(
          (current) => current || loaded.source_editions[0]?.edition_id || "",
        );
        setDraftId((current) => current || loaded.drafts[0]?.id || "");
      })
      .catch((loadError: unknown) => {
        if (loadError instanceof ApiError && loadError.status === 403) {
          setConfiguration(undefined);
          setConfigurationDenied(true);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Registration setup could not be loaded.",
        );
      });
  }

  function refreshRegistrations(
    filters: StaffRegistrationFilters = registrationFilters,
  ) {
    setRegistrationsDenied(false);
    setRegistrationsLoading(true);
    void loadStaffRegistrations(edition, filters)
      .then(setRegistrations)
      .catch((loadError: unknown) => {
        if (loadError instanceof ApiError && loadError.status === 403) {
          setRegistrations(undefined);
          setRegistrationsDenied(true);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "The registration queue could not be loaded.",
        );
      })
      .finally(() => setRegistrationsLoading(false));
  }

  function refreshReconciliation() {
    void loadRegistrationReconciliation(edition)
      .then(setReconciliation)
      .catch((loadError: unknown) => {
        if (loadError instanceof ApiError && loadError.status === 403) {
          setReconciliation(undefined);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Payment reconciliation could not be loaded.",
        );
      });
  }

  function refreshMediaReviews() {
    setMediaReviewsDenied(false);
    void loadProfileMediaReviews(edition)
      .then(setMediaReviews)
      .catch((loadError: unknown) => {
        if (loadError instanceof ApiError && loadError.status === 403) {
          setMediaReviews(undefined);
          setMediaReviewsDenied(true);
          return;
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Profile-image reviews could not be loaded.",
        );
      });
  }

  useEffect(() => {
    const initialRegistrationFilters = { page: 1 };
    setError(undefined);
    setSelected(undefined);
    setRegistrationFilters(initialRegistrationFilters);
    refreshConfiguration();
    refreshRegistrations(initialRegistrationFilters);
    refreshReconciliation();
    refreshMediaReviews();
  }, [edition]);

  async function decideMediaReview(
    item: ProfileMediaReviewItem,
    decision: "approved" | "rejected",
  ) {
    const reason = mediaReviewReasons[item.id]?.trim() ?? "";
    if (!reason) return;
    setBusy(true);
    setError(undefined);
    try {
      await reviewProfileMedia(edition, item, decision, reason);
      setMediaReviewReasons((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      refreshMediaReviews();
    } catch (reviewError: unknown) {
      setError(
        reviewError instanceof Error
          ? reviewError.message
          : "The image review could not be recorded.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cloneTemplate() {
    if (!templateId) return;
    setBusy(true);
    setError(undefined);
    const active = configuration?.active_configuration;
    try {
      await createRegistrationDraft(edition, {
        name: `${edition.edition_name} attendee registration`,
        reason: "Create an edition-owned draft from the selected template.",
        source_template_id: templateId,
        opens_at: active?.opens_at ?? new Date().toISOString(),
        closes_at:
          active?.closes_at ?? `${edition.starts_on}T00:00:00.000Z`,
        capacity: active?.capacity ?? 1_000,
        currency: active?.currency ?? edition.currency_codes[0] ?? "EUR",
      });
      refreshConfiguration();
    } catch (cloneError: unknown) {
      setError(
        cloneError instanceof Error
          ? cloneError.message
          : "The template could not be copied.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function activateDraft(event: FormEvent) {
    event.preventDefault();
    if (!draftId || !reviewReason.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await activateRegistrationConfiguration(
        edition,
        draftId,
        reviewReason,
      );
      setReviewReason("");
      refreshConfiguration();
    } catch (activationError: unknown) {
      setError(
        activationError instanceof Error
          ? activationError.message
          : "The registration version could not be activated.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cloneSourceEdition() {
    if (!sourceEditionId) return;
    setBusy(true);
    setError(undefined);
    const active = configuration?.active_configuration;
    try {
      await createRegistrationDraft(edition, {
        name: `${edition.edition_name} attendee registration`,
        reason: "Create an edition-owned draft from another edition.",
        source_edition_id: sourceEditionId,
        opens_at: active?.opens_at ?? new Date().toISOString(),
        closes_at:
          active?.closes_at ?? `${edition.starts_on}T00:00:00.000Z`,
        capacity: active?.capacity ?? 1_000,
        currency: active?.currency ?? edition.currency_codes[0] ?? "EUR",
      });
      refreshConfiguration();
    } catch (cloneError: unknown) {
      setError(
        cloneError instanceof Error
          ? cloneError.message
          : "The edition setup could not be copied.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function publishTemplate(event: FormEvent) {
    event.preventDefault();
    const active = configuration?.active_configuration;
    if (!active || !publishName.trim() || !publishCode.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await publishRegistrationTemplate(edition, {
        configuration_id: active.id,
        code: publishCode.trim(),
        name: publishName.trim(),
        description: `Reusable configuration published from ${edition.edition_name}.`,
        series_limited: seriesLimited,
        reason: "Publish the reviewed active configuration for controlled reuse.",
      });
      setPublishName("");
      setPublishCode("");
      refreshConfiguration();
    } catch (publishError: unknown) {
      setError(
        publishError instanceof Error
          ? publishError.message
          : "The reusable template could not be published.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function checkInSelected() {
    if (!selected) return;
    setBusy(true);
    setError(undefined);
    try {
      const updated = await checkInRegistration(
        edition,
        selected.id,
        "Front Desk confirmed the attendee and admission entitlement.",
      );
      replaceRegistration(updated);
    } catch (checkInError: unknown) {
      setError(
        checkInError instanceof Error
          ? checkInError.message
          : "Check-in could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }

  function replaceRegistration(updated: StaffRegistration) {
    setSelected(updated);
    setRegistrations((current) =>
      current
        ? {
            ...current,
            results: current.results.map((registration) =>
              registration.id === updated.id ? updated : registration,
            ),
          }
        : current,
    );
    refreshReconciliation();
  }

  async function changePaymentDeadline(event: FormEvent) {
    event.preventDefault();
    if (!selected || !newPaymentDeadline || !exceptionReason.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      const updated = await changeRegistrationPaymentDeadline(
        edition,
        selected.id,
        new Date(newPaymentDeadline).toISOString(),
        exceptionReason.trim(),
      );
      replaceRegistration(updated);
      setExceptionReason("");
      setNewPaymentDeadline("");
    } catch (changeError: unknown) {
      setError(
        changeError instanceof Error
          ? changeError.message
          : "The payment deadline could not be changed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function waivePayment() {
    if (!selected || !exceptionReason.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      const updated = await waiveRegistrationPayment(
        edition,
        selected.id,
        exceptionReason.trim(),
      );
      replaceRegistration(updated);
      setExceptionReason("");
      setNewPaymentDeadline("");
    } catch (waiverError: unknown) {
      setError(
        waiverError instanceof Error
          ? waiverError.message
          : "The payment waiver could not be recorded.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Attendee service</p>
          <h1>Registration desk</h1>
          <PageHelp
            purpose="Use this page to find and serve attendees from registration through arrival."
            examples="add an attendee outside public hours, reconcile payment, or check in a confirmed attendee"
          />
        </div>
        <div className="page-heading-actions">
          <a className="secondary-button" href={registrationSetupPath(edition)}>
            Registration setup
          </a>
          <span className="record-count">
            {registrationsDenied ? "Restricted" : `${registrations?.count ?? 0} attendees`}
          </span>
        </div>
      </div>
      <EmbeddedPageAccess />
      {error && <p className="form-error" role="alert">{error}</p>}

      <RegistrationQueue
        page={registrations}
        denied={registrationsDenied}
        loading={registrationsLoading}
        filters={registrationFilters}
        onApplyFilters={(filters) => {
          setRegistrationFilters(filters);
          refreshRegistrations(filters);
        }}
        onPage={(page) => {
          const filters = { ...registrationFilters, page };
          setRegistrationFilters(filters);
          refreshRegistrations(filters);
        }}
        onOpen={setSelected}
      />

      {!configurationDenied && configuration && (
        <section className="panel configuration-panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Edition-owned setup</p>
              <h2>Registration configuration</h2>
            </div>
            {configuration.active_configuration && (
              <StatusPill lifecycle="active" />
            )}
          </div>
          {configuration.active_configuration ? (
            <div className="configuration-summary">
              <div>
                <strong>{configuration.active_configuration.name}</strong>
                <span>
                  Version {configuration.active_configuration.version} ·{" "}
                  {configuration.active_configuration.source_summary.label}
                </span>
              </div>
              <div>
                <strong>
                  {configuration.active_configuration.questions.length}
                </strong>
                <span>questions</span>
              </div>
              <div>
                <strong>
                  {configuration.active_configuration.products.length}
                </strong>
                <span>products</span>
              </div>
              <div>
                <strong>{configuration.active_configuration.capacity}</strong>
                <span>edition capacity</span>
              </div>
            </div>
          ) : (
            <p className="muted-copy">
              No active registration version exists for this edition.
            </p>
          )}
          {configuration.active_configuration && (
            <div className="template-tools">
              <a
                className="secondary-button"
                href={`/admin/registration-assist/${edition.edition_id}/`}
              >
                Add attendee outside public hours
              </a>
              <a
                href={workforceWorkspacePath()}
              >
                Continue to Workforce: positions, assignments, availability, and shifts ↗
              </a>
            </div>
          )}

          <details className="configuration-details">
            <summary>Questions, products, and template tools</summary>
            {configuration.active_configuration && (
              <div className="configuration-columns">
                <div>
                  <h3>Questions</h3>
                  <ol>
                    {configuration.active_configuration.questions.map((question) => (
                      <li key={question.id}>
                        <strong>{question.label}</strong>
                        <span>{question.purpose}</span>
                      </li>
                    ))}
                  </ol>
                </div>
                <div>
                  <h3>Products</h3>
                  <ol>
                    {configuration.active_configuration.products.map((product) => (
                      <li key={product.id}>
                        <strong>{product.name}</strong>
                        <span>
                          {formatMoney(
                            product.price_minor,
                            configuration.active_configuration?.currency ?? "EUR",
                          )} · capacity {product.capacity}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            )}
            <div className="template-tools">
              <div>
                <h3>Start from a template</h3>
                <p>
                  Copying creates an independent draft and always requires review.
                </p>
                <select
                  aria-label="Registration template"
                  value={templateId}
                  onChange={(event) => setTemplateId(event.target.value)}
                >
                  <option value="">Choose a template</option>
                  {configuration.templates.map((template) => (
                    <option value={template.id} key={template.id}>
                      {template.name} v{template.version}
                    </option>
                  ))}
                </select>
                <button
                  className="secondary-button"
                  disabled={!templateId || busy}
                  onClick={() => void cloneTemplate()}
                >
                  Create reviewed draft copy
                </button>
              </div>
              <div>
                <h3>Copy another edition</h3>
                <p>
                  Start from the latest active or retired registration version.
                  The new draft is independent.
                </p>
                <select
                  aria-label="Source convention edition"
                  value={sourceEditionId}
                  onChange={(event) => setSourceEditionId(event.target.value)}
                >
                  <option value="">Choose an edition</option>
                  {configuration.source_editions.map((source) => (
                    <option value={source.edition_id} key={source.edition_id}>
                      {source.edition__name} · version {source.latest_version}
                    </option>
                  ))}
                </select>
                <button
                  className="secondary-button"
                  disabled={!sourceEditionId || busy}
                  onClick={() => void cloneSourceEdition()}
                >
                  Create independent draft
                </button>
              </div>
              <form onSubmit={(event) => void activateDraft(event)}>
                <h3>Review a draft</h3>
                <select
                  aria-label="Registration draft"
                  value={draftId}
                  onChange={(event) => setDraftId(event.target.value)}
                >
                  <option value="">Choose a draft</option>
                  {configuration.drafts.map((draft) => (
                    <option value={draft.id} key={draft.id}>
                      {draft.name} v{draft.version}
                    </option>
                  ))}
                </select>
                {draftId && (
                  <a
                    href={registrationSetupPath(edition)}
                  >
                    Open the registration builder ↗
                  </a>
                )}
                <textarea
                  aria-label="Registration review reason"
                  value={reviewReason}
                  onChange={(event) => setReviewReason(event.target.value)}
                  placeholder="What dates, prices, capacity, wording, and policy did you review?"
                  rows={3}
                  required
                />
                <button
                  className="primary-button"
                  disabled={!draftId || !reviewReason.trim() || busy}
                  type="submit"
                >
                  Activate reviewed version
                </button>
              </form>
              <form onSubmit={(event) => void publishTemplate(event)}>
                <h3>Publish the active setup</h3>
                <p>
                  Save the reviewed questions and products as an immutable,
                  versioned template.
                </p>
                <input
                  aria-label="New template name"
                  value={publishName}
                  onChange={(event) => setPublishName(event.target.value)}
                  placeholder="Standard attendee registration"
                  required
                />
                <input
                  aria-label="New template code"
                  value={publishCode}
                  onChange={(event) => setPublishCode(event.target.value)}
                  placeholder="standard-attendee"
                  required
                />
                <label className="inline-choice">
                  <input
                    type="checkbox"
                    checked={seriesLimited}
                    onChange={(event) => setSeriesLimited(event.target.checked)}
                  />
                  Limit reuse to this convention series
                </label>
                <button
                  className="primary-button"
                  disabled={
                    !configuration.active_configuration ||
                    !publishName.trim() ||
                    !publishCode.trim() ||
                    busy
                  }
                  type="submit"
                >
                  Publish reusable template
                </button>
              </form>
            </div>
          </details>
        </section>
      )}

      {!mediaReviewsDenied && mediaReviews && (
        <section className="panel media-review-panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Public profile safety</p>
              <h2>Images awaiting review</h2>
              <p className="muted-copy">
                Approval applies to this exact file. A replacement returns to
                the queue; an already-approved file may be reused without
                another wait.
              </p>
            </div>
            <span className="record-count">
              {mediaReviews.length} pending
            </span>
          </div>
          {mediaReviews.length ? (
            <div className="media-review-grid">
              {mediaReviews.map((item) => (
                <article className="media-review-card" key={item.id}>
                  <a href={item.preview_path} target="_blank" rel="noreferrer">
                    <img src={item.preview_path} alt={`${item.label} submitted by ${item.display_name}`} />
                  </a>
                  <div>
                    <strong>{item.display_name}</strong>
                    <span>{item.label}</span>
                    <time dateTime={item.submitted_at}>
                      {formatDateTime(item.submitted_at)}
                    </time>
                  </div>
                  <textarea
                    aria-label={`Review reason for ${item.display_name} ${item.label}`}
                    value={mediaReviewReasons[item.id] ?? ""}
                    onChange={(event) =>
                      setMediaReviewReasons((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))
                    }
                    placeholder="Record why this image is suitable or unsuitable."
                    rows={3}
                  />
                  <div className="form-actions">
                    <button
                      className="primary-button"
                      disabled={!mediaReviewReasons[item.id]?.trim() || busy}
                      onClick={() => void decideMediaReview(item, "approved")}
                    >
                      Approve
                    </button>
                    <button
                      className="danger-button"
                      disabled={!mediaReviewReasons[item.id]?.trim() || busy}
                      onClick={() => void decideMediaReview(item, "rejected")}
                    >
                      Reject
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="table-empty">
              <strong>No images are waiting</strong>
              <span>New or replaced attendee images will appear here.</span>
            </div>
          )}
        </section>
      )}

      {reconciliation && (
        <section className="panel reconciliation-panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Payment evidence</p>
              <h2>Registration reconciliation</h2>
              <p className="muted-copy">
                Provider-paid, waived, free, outstanding, and waitlisted places
                stay distinguishable.
              </p>
            </div>
            <time dateTime={reconciliation.generated_at}>
              {formatDateTime(reconciliation.generated_at)}
            </time>
          </div>
          <div className="configuration-columns">
            {reconciliation.products.map((product) => (
              <article
                className="reconciliation-product"
                key={`${product.product_name}-${product.currency}`}
              >
                <h3>{product.product_name}</h3>
                <dl className="summary-list">
                  <div>
                    <dt>Provider paid</dt>
                    <dd>
                      {product.provider_paid} ·{" "}
                      {formatMoney(
                        product.provider_paid_minor,
                        product.currency,
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Waived</dt>
                    <dd>
                      {product.waived} ·{" "}
                      {formatMoney(product.waived_minor, product.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt>Payment pending</dt>
                    <dd>{product.payment_pending}</dd>
                  </div>
                  <div>
                    <dt>Waitlisted</dt>
                    <dd>{product.waitlisted}</dd>
                  </div>
                  <div>
                    <dt>Expired / cancelled</dt>
                    <dd>{product.expired + product.cancelled}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      )}

      {selected && (
        <ModalDrawer
          className="person-drawer registration-drawer"
          labelledBy="registration-person"
          closeLabel="Close attendee details"
          onClose={() => setSelected(undefined)}
        >
            <p className="section-kicker">Front Desk service view</p>
            <h2 id="registration-person">{selected.display_name}</h2>
            <StatusPill lifecycle={selected.state} />
            <dl className="summary-list">
              <div>
                <dt>Reference</dt>
                <dd>{selected.reference}</dd>
              </div>
              <div>
                <dt>Admission</dt>
                <dd>{selected.product_name}</dd>
              </div>
              <div>
                <dt>Payment amount</dt>
                <dd>{formatMoney(selected.amount_minor, selected.currency)}</dd>
              </div>
              <div>
                <dt>Payment evidence</dt>
                <dd>
                  {selected.confirmation_basis
                    ? lifecycleLabel(selected.confirmation_basis)
                    : selected.state === "payment_pending"
                      ? "Awaiting payment"
                      : "Not recorded"}
                </dd>
              </div>
              {selected.payment_due_at && (
                <div>
                  <dt>Payment deadline</dt>
                  <dd>{formatDateTime(selected.payment_due_at)}</dd>
                </div>
              )}
              <div>
                <dt>Entitlements</dt>
                <dd>
                  {selected.entitlements.map((item) => item.label_snapshot).join(", ") ||
                    "None active"}
                </dd>
              </div>
            </dl>
            {selected.state === "confirmed" && (
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void checkInSelected()}
              >
                {busy ? "Checking in…" : "Check in attendee"}
              </button>
            )}
            {selected.state === "payment_pending" && (
              <form
                className="exception-form"
                onSubmit={(event) => void changePaymentDeadline(event)}
              >
                <h3>Controlled payment exception</h3>
                <p className="muted-copy">
                  A waiver never pretends that a provider payment occurred. Both
                  actions require a reason and remain visible in history.
                </p>
                <label>
                  Reason
                  <textarea
                    value={exceptionReason}
                    onChange={(event) => setExceptionReason(event.target.value)}
                    rows={3}
                    required
                  />
                </label>
                <label>
                  New payment deadline
                  <input
                    type="datetime-local"
                    value={newPaymentDeadline}
                    onChange={(event) => setNewPaymentDeadline(event.target.value)}
                  />
                </label>
                <div className="button-row">
                  <button
                    className="secondary-button"
                    type="submit"
                    disabled={
                      busy ||
                      !exceptionReason.trim() ||
                      !newPaymentDeadline
                    }
                  >
                    Change deadline
                  </button>
                  <button
                    className="danger-button"
                    type="button"
                    disabled={busy || !exceptionReason.trim()}
                    onClick={() => void waivePayment()}
                  >
                    Waive payment requirement
                  </button>
                </div>
              </form>
            )}
            <h3>Operational timeline</h3>
            <RegistrationTimeline registration={selected} />
            <p className="privacy-note">
              This purpose-limited view excludes form answers, email, HR records,
              safety cases, and unrelated participation data.
            </p>
        </ModalDrawer>
      )}
    </div>
  );
}

function ReadinessGateCard({
  definition,
  gate,
  busy,
  onReview,
}: {
  definition: (typeof readinessGateDefinitions)[number];
  gate?: ReadinessGate;
  busy: boolean;
  onReview: (
    code: ReadinessGateCode,
    approve: boolean,
    evidenceReference: string,
    summary: string,
  ) => Promise<void>;
}) {
  const [evidenceReference, setEvidenceReference] = useState(
    gate?.evidence_reference ?? "",
  );
  const [summary, setSummary] = useState(gate?.review_summary ?? "");
  const ready = Boolean(evidenceReference.trim() && summary.trim());

  useEffect(() => {
    setEvidenceReference(gate?.evidence_reference ?? "");
    setSummary(gate?.review_summary ?? "");
  }, [gate?.evidence_reference, gate?.review_summary]);

  return (
    <details className="readiness-gate" open={gate?.status !== "approved"}>
      <summary>
        <span>
          <strong>{definition.label}</strong>
          <small>{definition.purpose}</small>
        </span>
        <span className={`status-pill ${gate?.status ?? "pending"}`}>
          {lifecycleLabel(gate?.status ?? "pending")}
        </span>
      </summary>
      <div className="readiness-gate-body">
        <label>
          <span>Evidence reference</span>
          <input
            value={evidenceReference}
            onChange={(event) => setEvidenceReference(event.target.value)}
            maxLength={240}
            placeholder="For example: Finance reconciliation report 2027-04-12"
            aria-label={`${definition.label} evidence reference`}
          />
          <small>
            Use a readable report name, ticket, checklist, or secure document
            link. This is not an organization ID.
          </small>
        </label>
        <label>
          <span>Review summary</span>
          <textarea
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            maxLength={500}
            rows={3}
            placeholder="What was checked, and what did the evidence show?"
            aria-label={`${definition.label} review summary`}
          />
        </label>
        <p className="privacy-note">
          Maru records the signed-in reviewer and current server time
          automatically.
        </p>
        {gate?.reviewed_at && (
          <p className="muted-copy">
            Last reviewed {formatDateTime(gate.reviewed_at)}.
          </p>
        )}
        <div className="button-row">
          <button
            className="primary-button"
            type="button"
            disabled={busy || !ready}
            onClick={() =>
              void onReview(
                definition.code,
                true,
                evidenceReference.trim(),
                summary.trim(),
              )
            }
          >
            Approve gate
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy || !ready}
            onClick={() =>
              void onReview(
                definition.code,
                false,
                evidenceReference.trim(),
                summary.trim(),
              )
            }
          >
            Record not ready
          </button>
        </div>
      </div>
    </details>
  );
}

type LifecycleAction = {
  to: EditionContext["lifecycle"];
  label: string;
  consequence: string;
  dangerous?: boolean;
};

const lifecycleActions: Record<
  EditionContext["lifecycle"],
  LifecycleAction[]
> = {
  draft: [
    {
      to: "preparing",
      label: "Start planning",
      consequence:
        "Makes this edition an active planning workspace while configuration remains editable.",
    },
    {
      to: "cancelled",
      label: "Cancel edition",
      consequence:
        "Permanently closes this edition. A cancelled edition cannot return to planning.",
      dangerous: true,
    },
  ],
  preparing: [
    {
      to: "ready",
      label: "Mark ready",
      consequence:
        "Records that leadership considers the convention prepared for operation.",
    },
    {
      to: "draft",
      label: "Return to draft",
      consequence:
        "Moves the edition back to early configuration without deleting existing records.",
    },
    {
      to: "cancelled",
      label: "Cancel edition",
      consequence:
        "Permanently closes this edition. A cancelled edition cannot return to planning.",
      dangerous: true,
    },
  ],
  ready: [
    {
      to: "live",
      label: "Go live",
      consequence:
        "Marks the convention as currently operating. Use this when event operations begin.",
    },
    {
      to: "preparing",
      label: "Return to preparation",
      consequence:
        "Reopens preparation because the edition is not yet ready to operate.",
    },
    {
      to: "cancelled",
      label: "Cancel edition",
      consequence:
        "Permanently closes this edition. A cancelled edition cannot return to planning.",
      dangerous: true,
    },
  ],
  live: [
    {
      to: "closing",
      label: "Begin closeout",
      consequence:
        "Ends live operation and starts finance, privacy, security, and operational closeout.",
    },
  ],
  closing: [
    {
      to: "archived",
      label: "Archive edition",
      consequence:
        "Makes historical edition records read-only. All five readiness gates must be approved.",
      dangerous: true,
    },
  ],
  archived: [],
  cancelled: [],
};

function EditionLifecyclePanel({
  edition,
  onTransitioned,
}: {
  edition: EditionContext;
  onTransitioned: (result: EditionTransitionResult) => void;
}) {
  const actions = lifecycleActions[edition.lifecycle];
  const [target, setTarget] = useState<EditionContext["lifecycle"]>(
    actions[0]?.to ?? edition.lifecycle,
  );
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [success, setSuccess] = useState<string>();

  useEffect(() => {
    const nextActions = lifecycleActions[edition.lifecycle];
    setTarget(nextActions[0]?.to ?? edition.lifecycle);
    setReason("");
    setConfirmed(false);
    setError(undefined);
  }, [edition.edition_id, edition.lifecycle]);

  const selectedAction = actions.find((action) => action.to === target);
  const ready = Boolean(
    selectedAction &&
      reason.trim() &&
      (!selectedAction.dangerous || confirmed),
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAction || !ready) return;
    setBusy(true);
    setError(undefined);
    setSuccess(undefined);
    try {
      const result = await transitionEdition(edition, target, reason.trim());
      setSuccess(
        `${edition.edition_name} is now ${lifecycleLabel(result.lifecycle)}.`,
      );
      onTransitioned(result);
    } catch (caught: unknown) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The edition lifecycle could not be changed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel lifecycle-panel" aria-labelledby="lifecycle-heading">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Edition lifecycle</p>
          <h2 id="lifecycle-heading">Convention state</h2>
          <p className="muted-copy">
            Lifecycle describes the convention’s operational phase. Registration
            opening and ticket sales are configured separately.
          </p>
        </div>
        <StatusPill lifecycle={edition.lifecycle} />
      </div>
      {!edition.can_transition ? (
        <div className="permission-state compact-permission">
          <span className="permission-lock" aria-hidden="true">◇</span>
          <h3>Lifecycle changes are restricted</h3>
          <p>
            Ask a convention leader to assign a group with edition lifecycle
            authority.
          </p>
        </div>
      ) : actions.length === 0 ? (
        <p className="muted-copy">
          {edition.lifecycle === "archived"
            ? "This historical edition is archived and has no further lifecycle actions."
            : "This edition was cancelled and has no further lifecycle actions."}
        </p>
      ) : (
        <form className="lifecycle-form" onSubmit={submit}>
          <div className="form-field">
            <label htmlFor="lifecycle-target">Next state</label>
            <select
              id="lifecycle-target"
              value={target}
              onChange={(event) => {
                setTarget(
                  event.target.value as EditionContext["lifecycle"],
                );
                setConfirmed(false);
              }}
            >
              {actions.map((action) => (
                <option value={action.to} key={action.to}>
                  {action.label} · {lifecycleLabel(action.to)}
                </option>
              ))}
            </select>
          </div>
          {selectedAction && (
            <div
              className={
                selectedAction.dangerous
                  ? "transition-consequence dangerous-consequence"
                  : "transition-consequence"
              }
            >
              <strong>{selectedAction.label}</strong>
              <span>{selectedAction.consequence}</span>
            </div>
          )}
          <div className="form-field">
            <label htmlFor="lifecycle-reason">Reason for this transition</label>
            <textarea
              id="lifecycle-reason"
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <small>The signed-in actor, server time, reason, and state change are audited.</small>
          </div>
          {selectedAction?.dangerous && (
            <label className="impact-confirmation">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>I understand this transition is terminal and cannot be undone.</span>
            </label>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
          {success && <p className="success-copy" role="status">{success}</p>}
          <div className="form-actions">
            <button
              className={
                selectedAction?.dangerous ? "danger-button" : "primary-button"
              }
              disabled={!ready || busy}
            >
              {busy ? "Recording transition…" : selectedAction?.label}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function SetupView({
  edition,
  canAccessAdvancedRecords,
  onTransitioned,
}: {
  edition: EditionContext;
  canAccessAdvancedRecords: boolean;
  onTransitioned: (result: EditionTransitionResult) => void;
}) {
  const available = new Set(edition.available_destinations);
  const hasWorkforce = available.has("workforce");
  const hasRegistrationOperations = available.has("commerce");
  const hasCloseoutReadiness =
    hasRegistrationOperations && available.has("reports");
  const [readiness, setReadiness] = useState<ClosureReadiness>();
  const [readinessDenied, setReadinessDenied] = useState(false);
  const [readinessError, setReadinessError] = useState<string>();
  const [reviewingGate, setReviewingGate] = useState<ReadinessGateCode>();

  useEffect(() => {
    setReadiness(undefined);
    setReadinessDenied(false);
    setReadinessError(undefined);
    if (!hasCloseoutReadiness) return;
    loadClosureReadiness(edition)
      .then(setReadiness)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 403) {
          setReadinessDenied(true);
          return;
        }
        setReadinessError(
          error instanceof Error
            ? error.message
            : "Readiness evidence could not be loaded.",
        );
      });
  }, [edition, hasCloseoutReadiness]);

  async function reviewGate(
    code: ReadinessGateCode,
    approve: boolean,
    evidenceReference: string,
    summary: string,
  ) {
    setReviewingGate(code);
    setReadinessError(undefined);
    try {
      const reviewed = await reviewReadinessGate(edition, code, {
        approve,
        evidence_reference: evidenceReference,
        summary,
      });
      setReadiness((current) => {
        if (!current) return current;
        const remaining = current.gates.filter((gate) => gate.code !== code);
        return { ...current, gates: [...remaining, reviewed] };
      });
    } catch (error) {
      setReadinessError(
        error instanceof Error
          ? error.message
          : "The readiness decision could not be recorded.",
      );
    } finally {
      setReviewingGate(undefined);
    }
  }

  const foundationSteps = [
    {
      title: "Organization",
      summary: "Set the legal organizer, working languages, and default time zone.",
      href: `/admin/platform/organizations/${encodeURIComponent(edition.organization_slug)}/`,
    },
    {
      title: "Convention series",
      summary: "Define the recurring convention identity shared by its editions.",
      href: `/admin/platform/organizations/${encodeURIComponent(edition.organization_slug)}/series/${encodeURIComponent(edition.series_slug)}/`,
    },
    {
      title: "Event edition",
      summary: hasRegistrationOperations
        ? "Review the dated convention occurrence, locale, and payment currency."
        : "Review the dated purpose-scoped workspace and its local time. No payment currency is required.",
      href: `/admin/platform/organizations/${encodeURIComponent(edition.organization_slug)}/series/${encodeURIComponent(edition.series_slug)}/editions/${encodeURIComponent(edition.edition_slug)}/`,
    },
  ];
  const steps: Array<{
    title: string;
    summary: string;
    href?: string;
    action?: "access";
  }> = [
    ...foundationSteps,
    {
      title: "Accountable access",
      summary:
        "Keep at least two accountable Maru operators; this does not claim Executive Board office.",
      href: `/admin/platform/organizations/${encodeURIComponent(edition.organization_slug)}/representation/`,
    },
  ];
  if (hasRegistrationOperations) {
    steps.push({
      title: "Registration",
      summary:
        "Prepare products, form questions, opening windows, and payment rules.",
      href: registrationSetupPath(edition),
    });
  }
  if (hasWorkforce) {
    steps.push(
      {
        title: "Structure & Positions",
        summary: "Define Departments and Positions before assigning volunteers.",
        href: workforceStructurePath(edition),
      },
      {
        title: "Assignments",
        summary:
          "Place volunteers in approved Positions under this profile's exact assignment boundary.",
        href: workforceAssignmentsPath(edition),
      },
      {
        title: "Availability",
        summary:
          "Collect when assigned volunteers can work in local convention time.",
        href: workforceAvailabilityPath(edition),
      },
      {
        title: "Shifts",
        summary:
          "Plan coverage and publish Shift commitments after Availability is known.",
        href: workforceShiftsPath(edition),
      },
    );
  }
  steps.push({
    title: "Teams & access",
    summary:
      "Share system capabilities without treating access as a workforce appointment.",
    action: "access",
  });
  if (hasCloseoutReadiness) {
    steps.push({
      title: "Edition closeout readiness",
      summary:
        "Review privacy, finance, operations, security, and safeguarding evidence before archive.",
      href: "#readiness-review",
    });
  }

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Convention setup</p>
          <h1>Setup guide</h1>
          <PageHelp
            purpose={`Use this ordered guide for the tools pinned by the ${edition.adoption_profile_label} profile.`}
            examples={hasWorkforce
              ? "define Positions before assigning volunteers"
              : "review the edition before opening its adopted workflows"}
          />
        </div>
      </div>
      <EmbeddedPageAccess />
      <EditionLifecyclePanel
        edition={edition}
        onTransitioned={onTransitioned}
      />
      <>
        <ol className="setup-steps">
          {steps.map((step, index) => (
            <li key={step.title}>
              <span className="setup-step-number">{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.summary}</p>
              </div>
              {"href" in step ? (
                <a className="secondary-button" href={step.href}>
                  Open <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <span className="quiet-badge">Use Manage access</span>
              )}
            </li>
          ))}
        </ol>
        {hasRegistrationOperations && (
          <section className="panel planned-capabilities" aria-labelledby="planned-capabilities-title">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Product roadmap</p>
                <h2 id="planned-capabilities-title">Planned capabilities</h2>
              </div>
              <span className="quiet-badge">Not available yet</span>
            </div>
            <p className="muted-copy">
              These areas have an intentional home in Maru, but they are not
              links until their workflows and authorization contracts are ready.
            </p>
            <ul className="planned-capability-list">
              {upcomingDestinations.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          </section>
        )}
        {canAccessAdvancedRecords ? (
          <section className="setup-note">
            <div>
              <p className="section-kicker">Occasional maintenance</p>
              <h2>Specialist records</h2>
              <p>
                The record directory holds specialist and historical data that
                should not clutter everyday convention work.
              </p>
            </div>
            <a
              className="primary-button"
              href="/admin/?records=open#maru-specialist-heading"
            >
              Browse specialist records
            </a>
          </section>
        ) : (
          <section className="permission-state compact-permission">
            <span className="permission-lock" aria-hidden="true">◇</span>
            <h2>Specialist records are restricted</h2>
            <p>
              Your purpose-built setup pages remain available. Account staff
              status is required only for the low-frequency record directory.
            </p>
          </section>
        )}
      </>
      {hasCloseoutReadiness && (
        <section
          className="panel readiness-review"
          id="readiness-review"
          aria-labelledby="readiness-heading"
        >
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Accountable closeout</p>
              <h2 id="readiness-heading">Edition readiness review</h2>
              <p className="muted-copy">
                These five checks preserve the evidence behind a decision to
                archive an edition. They are not IDs or ordinary configuration
                fields.
              </p>
            </div>
            {readiness && (
              <span className="quiet-badge">
                {
                  readiness.gates.filter((gate) => gate.status === "approved")
                    .length
                }{" "}
                of {readinessGateDefinitions.length} approved
              </span>
            )}
          </div>
          {readinessError && (
            <p className="form-error" role="alert">{readinessError}</p>
          )}
          {readinessDenied ? (
            <div className="permission-state compact-permission">
              <span className="permission-lock" aria-hidden="true">◇</span>
              <h3>Readiness review is restricted</h3>
              <p>
                Ask a convention leader to assign a group with edition lifecycle
                authority.
              </p>
            </div>
          ) : readiness ? (
            <div className="readiness-gates">
              {readinessGateDefinitions.map((definition) => (
                <ReadinessGateCard
                  key={definition.code}
                  definition={definition}
                  gate={readiness.gates.find(
                    (gate) => gate.code === definition.code,
                  )}
                  busy={reviewingGate === definition.code}
                  onReview={reviewGate}
                />
              ))}
            </div>
          ) : (
            <p className="muted-copy">Loading readiness evidence…</p>
          )}
        </section>
      )}
    </div>
  );
}

function recommendedForPage(
  group: AccessGroup,
  destination: Destination,
): boolean {
  return recommendedGroups[destination].includes(group.code);
}

function AccessAssignmentCard({
  assignment,
  groups,
  canModify,
  busy,
  onReplace,
  onRevoke,
}: {
  assignment: AccessAssignment;
  groups: AccessGroup[];
  canModify: boolean;
  busy: boolean;
  onReplace: (assignmentId: string, input: ReplaceAccessInput) => Promise<void>;
  onRevoke: (assignmentId: string, reason: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [groupCode, setGroupCode] = useState(assignment.group_code);
  const [approverEmail, setApproverEmail] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");

  async function submitReplacement(event: FormEvent) {
    event.preventDefault();
    try {
      await onReplace(assignment.id, {
        group_code: groupCode,
        approver_email: approverEmail.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        reason: reason.trim(),
      });
      setEditing(false);
      setApproverEmail("");
      setReason("");
    } catch {
      // The drawer-level error keeps the form intact so the operator can correct it.
    }
  }

  async function submitRevocation(event: FormEvent) {
    event.preventDefault();
    try {
      await onRevoke(assignment.id, reason.trim());
      setRemoving(false);
      setReason("");
    } catch {
      // The drawer-level error keeps the reason available for correction.
    }
  }

  return (
    <article className="access-assignment">
      <div className="access-person">
        <span className="avatar" aria-hidden="true">
          {assignment.person_display_name.charAt(0).toUpperCase()}
        </span>
        <span>
          <strong>{assignment.person_display_name}</strong>
          <small>{assignment.person_email}</small>
        </span>
      </div>
      <div className="access-group-summary">
        <strong>{assignment.group_name}</strong>
        <small>
          {assignment.scope_label}
          {assignment.expires_at
            ? ` · until ${formatDateTime(assignment.expires_at)}`
            : " · no expiry"}
        </small>
      </div>
      {canModify && !editing && !removing && (
        <div className="access-card-actions">
          <button className="text-button" onClick={() => setEditing(true)}>
            Change
          </button>
          <button className="text-button danger-text" onClick={() => setRemoving(true)}>
            Remove
          </button>
        </div>
      )}
      {editing && (
        <form className="access-inline-form" onSubmit={submitReplacement}>
          <label>
            <span>Group</span>
            <select
              value={groupCode}
              onChange={(event) => setGroupCode(event.target.value)}
              required
            >
              {groups.map((group) => (
                <option key={group.code} value={group.code}>{group.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Independent approver email</span>
            <input
              type="email"
              value={approverEmail}
              onChange={(event) => setApproverEmail(event.target.value)}
              required
            />
          </label>
          <label>
            <span>Expires (optional)</span>
            <input
              type="datetime-local"
              value={expiresAt}
              onChange={(event) => setExpiresAt(event.target.value)}
            />
          </label>
          <label className="wide-field">
            <span>Reason for changing access</span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={240}
              required
            />
          </label>
          <div className="access-inline-actions">
            <button className="primary-button" type="submit" disabled={busy}>
              Save change
            </button>
            <button className="text-button" type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {removing && (
        <form className="access-inline-form revoke-form" onSubmit={submitRevocation}>
          <label className="wide-field">
            <span>Reason for removing access</span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={240}
              required
            />
          </label>
          <div className="access-inline-actions">
            <button className="danger-button" type="submit" disabled={busy}>
              Remove access
            </button>
            <button className="text-button" type="button" onClick={() => setRemoving(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </article>
  );
}

function AccessPreviewPanel({
  preview,
  onExit,
}: {
  preview: AccessPreview;
  onExit: () => void;
}) {
  return (
    <section className="access-preview" aria-labelledby="access-preview-heading">
      <div className="access-preview-banner" role="status">
        <div>
          <strong>Preview only · your session has not changed</strong>
          <span>
            You are still signed in as yourself. This explanation is capped by
            your own disclosure authority, and no action can be taken as the
            previewed person or role.
          </span>
        </div>
        <button className="secondary-button" type="button" onClick={onExit}>
          Exit preview
        </button>
      </div>
      <div className="access-preview-heading">
        <p className="section-kicker">
          {preview.mode === "person" ? "Exact person" : "Hypothetical role"}
        </p>
        <h3 id="access-preview-heading">{preview.subject_label}</h3>
        <p>
          Effective at {formatDateTime(preview.evaluated_at)} for {preview.scope_label}.
          This is a policy explanation, not an impersonated page.
        </p>
      </div>
      {preview.capabilities.length ? (
        <ul className="access-preview-capabilities">
          {preview.capabilities.map((item) => (
            <li key={item.capability_code}>
              <div>
                <strong>{item.label}</strong>
                <span>{item.description}</span>
                <small>{item.source_label}</small>
              </div>
              <span
                className={
                  item.data_preview_available
                    ? "quiet-badge"
                    : "quiet-badge preview-limited"
                }
              >
                {item.data_preview_available
                  ? item.visible_fields.length
                    ? `${item.visible_fields.length} visible fields`
                    : "Action visible"
                  : "Details capped"}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted-copy">
          No convention-management capability is effective at this exact scope.
        </p>
      )}
      {preview.disclosure_limited_count > 0 && (
        <p className="access-preview-limit-note">
          {preview.disclosure_limited_count} capability
          {preview.disclosure_limited_count === 1 ? " is" : "ies are"} shown
          without protected record fields because your own access does not allow
          those fields to be disclosed.
        </p>
      )}
    </section>
  );
}

function AccessDrawer({
  workspace,
  edition,
  destination,
  busy,
  error,
  onClose,
  onAssign,
  onReplace,
  onRevoke,
}: {
  workspace: AccessWorkspace;
  edition: EditionContext;
  destination: Destination;
  busy: boolean;
  error?: string;
  onClose: () => void;
  onAssign: (input: AssignAccessInput) => Promise<void>;
  onReplace: (assignmentId: string, input: ReplaceAccessInput) => Promise<void>;
  onRevoke: (assignmentId: string, reason: string) => Promise<void>;
}) {
  const assignmentUsesParticipation =
    edition.assignment_uses_participation_evidence;
  const orderedGroups = [...workspace.groups].sort((left, right) => {
    const recommendation =
      Number(recommendedForPage(right, destination)) -
      Number(recommendedForPage(left, destination));
    return recommendation || left.name.localeCompare(right.name);
  });
  const [personEmail, setPersonEmail] = useState("");
  const [groupCode, setGroupCode] = useState(
    orderedGroups.find((group) => recommendedForPage(group, destination))?.code ??
      orderedGroups[0]?.code ??
      "",
  );
  const [approverEmail, setApproverEmail] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");
  const [previewPersonEmail, setPreviewPersonEmail] = useState("");
  const [previewRoleVersionId, setPreviewRoleVersionId] = useState(
    orderedGroups[0]?.role_version_id ?? "",
  );
  const [preview, setPreview] = useState<AccessPreview>();
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string>();
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const normalizedAssignmentSearch = assignmentSearch.trim().toLocaleLowerCase();
  const visibleAssignments = workspace.assignments.filter((assignment) =>
    [
      assignment.person_display_name,
      assignment.person_email,
      assignment.group_name,
      assignment.scope_label,
    ].some((value) =>
      value.toLocaleLowerCase().includes(normalizedAssignmentSearch),
    ),
  );

  async function submitAssignment(event: FormEvent) {
    event.preventDefault();
    try {
      await onAssign({
        person_email: personEmail.trim(),
        group_code: groupCode,
        approver_email: approverEmail.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        reason: reason.trim(),
      });
      setPersonEmail("");
      setReason("");
    } catch {
      // The drawer-level error keeps the form intact so the operator can correct it.
    }
  }

  async function runPreview(input: PreviewAccessInput): Promise<void> {
    setPreviewBusy(true);
    setPreviewError(undefined);
    try {
      setPreview(await previewAccess(edition, input));
    } catch (previewFailure: unknown) {
      setPreviewError(
        previewFailure instanceof Error
          ? previewFailure.message
          : "Access preview could not be calculated.",
      );
    } finally {
      setPreviewBusy(false);
    }
  }

  function submitPersonPreview(event: FormEvent) {
    event.preventDefault();
    void runPreview({
      mode: "person",
      person_email: previewPersonEmail.trim(),
    });
  }

  function submitRolePreview(event: FormEvent) {
    event.preventDefault();
    void runPreview({
      mode: "role",
      role_version_id: previewRoleVersionId,
    });
  }

  return (
    <ModalDrawer
      className="access-drawer"
      scrimClassName="access-scrim"
      labelledBy="access-heading"
      closeLabel="Close access workspace"
      onClose={onClose}
    >
        <p className="section-kicker">People &amp; groups</p>
        <h2 id="access-heading">Access to {destinationLabels[destination]}</h2>
        <p className="muted-copy">
          Assign a convention group to an existing account by exact email.
          Groups grant real capabilities across {workspace.edition_name}; the
          recommendations below are guidance for this page, not page-only
          permissions.
        </p>
        <div className="access-safety-note">
          <strong>Two-person approval protects powerful access.</strong>
          <span>
            Enter a different authorized person as approver. Every add
            {workspace.can_revoke_assignments ? ", change, and removal" : ""} is
            recorded with its reason.
          </span>
        </div>
        <div className="access-safety-note access-purpose-note">
          <strong>Access is not a workforce appointment.</strong>
          <span>
            {assignmentUsesParticipation
              ? "Use a Position assignment when someone must fill a hierarchy role, satisfy an agreement, receive capacities, or appear with an official convention title."
              : "Use a Position assignment when someone must fill a hierarchy role, satisfy an agreement, or appear with an official convention title. This edition profile does not create attendee Participation capacities."}{" "}
            Sharing here grants only the selected system capabilities.
          </span>
        </div>
        {preview ? (
          <AccessPreviewPanel preview={preview} onExit={() => setPreview(undefined)} />
        ) : (
          <section className="access-preview-launcher" aria-labelledby="preview-heading">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Read-only policy simulation</p>
                <h3 id="preview-heading">Preview access</h3>
              </div>
              <span className="quiet-badge">No impersonation</span>
            </div>
            <p className="muted-copy">
              Check an exact active person or one immutable group version at this
              convention scope. Preview never changes your login or creates access.
            </p>
            <div className="access-preview-forms">
              <form onSubmit={submitPersonPreview}>
                <label>
                  <span>Exact person email</span>
                  <input
                    type="email"
                    value={previewPersonEmail}
                    onChange={(event) => setPreviewPersonEmail(event.target.value)}
                    placeholder="person@example.com"
                    required
                  />
                </label>
                <button className="secondary-button" type="submit" disabled={previewBusy}>
                  Preview person
                </button>
              </form>
              <form onSubmit={submitRolePreview}>
                <label>
                  <span>Immutable group version</span>
                  <select
                    value={previewRoleVersionId}
                    onChange={(event) => setPreviewRoleVersionId(event.target.value)}
                    required
                  >
                    {orderedGroups.map((group) => (
                      <option value={group.role_version_id} key={group.role_version_id}>
                        {group.name} · v{group.version}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="secondary-button"
                  type="submit"
                  disabled={previewBusy || !previewRoleVersionId}
                >
                  Preview role
                </button>
              </form>
            </div>
            {previewError && <p className="form-error" role="alert">{previewError}</p>}
          </section>
        )}
        {!preview && (
          <section className="access-effective-summary" aria-labelledby="access-effective-heading">
            <p className="section-kicker">Computed access</p>
            <h3 id="access-effective-heading">Your effective access</h3>
            <p>{workspace.effective_access.scope_label}</p>
            <ul>
              {workspace.effective_access.actions.map((action) => (
                <li key={action.capability_code}>
                  <strong>{action.label}</strong>
                  <span>{action.allowed ? action.source_label : "Unavailable"}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {!preview && error && <p className="form-error" role="alert">{error}</p>}

        <form
          className="access-share-form"
          onSubmit={submitAssignment}
          hidden={Boolean(preview)}
        >
          <h3>Add a person</h3>
          <label className="wide-field">
            <span>Existing account email</span>
            <input
              type="email"
              aria-label="Existing account email"
              aria-describedby="access-person-email-help"
              value={personEmail}
              onChange={(event) => setPersonEmail(event.target.value)}
              placeholder="person@example.com"
              required
            />
            <small id="access-person-email-help">
              Maru matches this exact email; it never guesses a person.
            </small>
          </label>
          <label>
            <span>Group</span>
            <select
              value={groupCode}
              onChange={(event) => setGroupCode(event.target.value)}
              required
            >
              {orderedGroups.map((group) => (
                <option value={group.code} key={group.code}>
                  {recommendedForPage(group, destination) ? "Recommended · " : ""}
                  {group.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Independent approver email</span>
            <input
              type="email"
              value={approverEmail}
              onChange={(event) => setApproverEmail(event.target.value)}
              placeholder="approver@example.com"
              required
            />
          </label>
          <label>
            <span>Expires (optional)</span>
            <input
              type="datetime-local"
              value={expiresAt}
              onChange={(event) => setExpiresAt(event.target.value)}
            />
          </label>
          <label className="wide-field">
            <span>Reason</span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why this person needs this access"
              maxLength={240}
              required
            />
          </label>
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Share access"}
          </button>
        </form>

        <section
          className="access-groups"
          aria-labelledby="groups-heading"
          hidden={Boolean(preview)}
        >
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Reusable access groups</p>
              <h3 id="groups-heading">What each group can do</h3>
            </div>
          </div>
          {orderedGroups.map((group) => (
            <details className="access-group" key={group.code}>
              <summary>
                <span>
                  <strong>{group.name}</strong>
                  <small>{group.description}</small>
                </span>
                <span className="quiet-badge">
                  {recommendedForPage(group, destination)
                    ? "Recommended here"
                    : `${group.capability_count} permission${
                        group.capability_count === 1 ? "" : "s"
                      }`}
                </span>
              </summary>
              <ul>
                {group.capabilities.map((capability) => (
                  <li key={capability.code}>
                    <strong>{capability.label}</strong>
                    <span>{capability.description}</span>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </section>

        <section
          className="access-assignments"
          aria-labelledby="assignments-heading"
          hidden={Boolean(preview)}
        >
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Current access</p>
              <h3 id="assignments-heading">People with assigned groups</h3>
            </div>
            <span className="quiet-badge">
              {visibleAssignments.length === workspace.assignments.length
                ? `${workspace.assignments.length} assignments`
                : `${visibleAssignments.length} of ${workspace.assignments.length}`}
            </span>
          </div>
          <label className="access-assignment-search">
            <span className="sr-only">Find a person or group</span>
            <Icon>⌕</Icon>
            <input
              type="search"
              value={assignmentSearch}
              onChange={(event) => setAssignmentSearch(event.target.value)}
              placeholder="Find a person, email, or group"
              aria-label="Find a person or group"
            />
          </label>
          {visibleAssignments.length ? (
            visibleAssignments.map((assignment) => (
              <AccessAssignmentCard
                key={assignment.id}
                assignment={assignment}
                groups={workspace.groups}
                canModify={workspace.can_revoke_assignments}
                busy={busy}
                onReplace={onReplace}
                onRevoke={onRevoke}
              />
            ))
          ) : (
            <p className="muted-copy">
              {workspace.assignments.length
                ? "No current assignment matches that search."
                : "No access groups have been assigned at this convention scope."}
            </p>
          )}
        </section>
    </ModalDrawer>
  );
}

function SecurityView() {
  const [events, setEvents] = useState<SecurityEvent[]>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    void loadSecurityHistory()
      .then(setEvents)
      .catch((loadError: unknown) =>
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Security history could not be loaded.",
        ),
      );
  }, []);

  return (
    <div className="view">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">Your platform account</p>
          <h1>Security history</h1>
          <PageHelp
            purpose="Use this page to review important events for your Maru account."
            examples="confirm that recent sign-ins and sign-outs were yours"
          />
        </div>
      </div>
      <EmbeddedPageAccess />
      <section className="panel security-history">
        {error && <p className="form-error" role="alert">{error}</p>}
        {events?.length ? (
          <ol className="timeline-list">
            {events.map((event) => (
              <li key={event.id}>
                <strong>{event.event_label}</strong>
                <p>
                  {lifecycleLabel(event.outcome)} ·{" "}
                  {lifecycleLabel(event.source_channel)}
                </p>
                <time dateTime={event.occurred_at}>
                  {formatDateTime(event.occurred_at)}
                </time>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted-copy">
            {events ? "No account security events are recorded yet." : "Loading…"}
          </p>
        )}
      </section>
    </div>
  );
}

export default function App({
  embeddedInAdmin = isAdminEmbedded(),
}: {
  embeddedInAdmin?: boolean;
} = {}) {
  const [context, setContext] = useState<MyContext>();
  const [edition, setEdition] = useState<EditionContext>();
  const [destination, setDestination] = useState<Destination>(
    requestedDestination,
  );
  const [people, setPeople] = useState<ParticipationPage>();
  const [peopleDenied, setPeopleDenied] = useState(false);
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [actionsDenied, setActionsDenied] = useState(false);
  const [accessWorkspace, setAccessWorkspace] = useState<AccessWorkspace>();
  const [accessOpen, setAccessOpen] = useState(false);
  const [accessBusy, setAccessBusy] = useState(false);
  const [accessError, setAccessError] = useState<string>();
  const [filters, setFilters] = useState<ParticipationFilters>({ page: 1 });
  const [fatalError, setFatalError] = useState<string>();

  useEffect(() => {
    let current = true;
    void loadMyContext()
      .then((loaded) => {
        if (!current) return;
        const initialEdition = chooseInitialEdition(
          loaded.editions,
          selectedAdminEditionId(),
        );
        setContext(loaded);
        if (
          embeddedInAdmin &&
          initialEdition &&
          !selectedAdminEditionId() &&
          submitEmbeddedEditionContext(initialEdition.edition_id)
        ) {
          return;
        }
        setEdition(initialEdition);
      })
      .catch((error: unknown) => {
        if (!current) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          window.location.assign("/accounts/login/?next=/admin/workspace/");
          return;
        }
        setFatalError(
          error instanceof Error ? error.message : "An unexpected error occurred.",
        );
      });
    return () => {
      current = false;
    };
  }, [embeddedInAdmin]);

  useEffect(() => {
    if (!edition) return;
    if (!isAvailableDestination(edition, destination)) {
      const fallback = availablePresentationDestinations(edition)[0];
      if (fallback) setDestination(fallback);
    }
  }, [destination, edition]);

  useEffect(() => {
    if (!edition) return;
    if (!edition.available_destinations.includes("people")) {
      setPeople(undefined);
      setPeopleDenied(false);
      setPeopleLoading(false);
      return;
    }
    setPeopleLoading(true);
    setPeopleDenied(false);
    void loadParticipations(edition, filters)
      .then(setPeople)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 403) {
          setPeople(undefined);
          setPeopleDenied(true);
          return;
        }
        setFatalError(
          error instanceof Error ? error.message : "The people view failed.",
        );
      })
      .finally(() => setPeopleLoading(false));
  }, [edition, filters]);

  useEffect(() => {
    if (!edition) return;
    setActions([]);
    setActionsDenied(false);
    if (!edition.available_destinations.includes("commerce")) return;
    void loadActions(edition)
      .then(setActions)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 403) {
          setActionsDenied(true);
          return;
        }
        setFatalError(
          error instanceof Error ? error.message : "The action center failed.",
        );
      });
  }, [edition]);

  useEffect(() => {
    if (!edition) return;
    setAccessWorkspace(undefined);
    setAccessOpen(false);
    setAccessError(undefined);
    if (!availablePresentationDestinations(edition).length) return;
    void loadAccessWorkspace(edition)
      .then((workspace) => {
        setAccessWorkspace(workspace);
        if (accessWasRequested()) setAccessOpen(true);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 403) {
          return;
        }
        setAccessError(
          error instanceof Error
            ? error.message
            : "Access settings could not be loaded.",
        );
      });
  }, [edition]);

  function recordLifecycleTransition(result: EditionTransitionResult) {
    setEdition((current) =>
      current && current.edition_id === result.id
        ? { ...current, lifecycle: result.lifecycle }
        : current,
    );
    setContext((current) =>
      current
        ? {
            ...current,
            editions: current.editions.map((item) =>
              item.edition_id === result.id
                ? { ...item, lifecycle: result.lifecycle }
                : item,
            ),
          }
        : current,
    );
  }

  if (fatalError) return <ErrorScreen message={fatalError} />;
  if (!context) return <LoadingScreen />;
  if (!edition) return <EmptyContext context={context} />;
  const activeEdition = edition;
  const presentationDestinations = availablePresentationDestinations(edition);
  const activeDestination = isAvailableDestination(edition, destination)
    ? destination
    : presentationDestinations[0];

  function changeEdition(next: EditionContext) {
    window.localStorage.setItem("maru.staff.edition", next.edition_id);
    if (embeddedInAdmin && submitEmbeddedEditionContext(next.edition_id)) {
      return;
    }
    setEdition(next);
    setFilters({ page: 1 });
    setPeople(undefined);
    setActions([]);
    setAccessWorkspace(undefined);
    setAccessOpen(false);
    setAccessError(undefined);
  }

  async function assignAccess(input: AssignAccessInput): Promise<void> {
    setAccessBusy(true);
    setAccessError(undefined);
    try {
      setAccessWorkspace(await assignAccessGroup(activeEdition, input));
    } catch (error: unknown) {
      setAccessError(
        error instanceof Error ? error.message : "Access could not be shared.",
      );
      throw error;
    } finally {
      setAccessBusy(false);
    }
  }

  async function replaceAccess(
    assignmentId: string,
    input: ReplaceAccessInput,
  ): Promise<void> {
    setAccessBusy(true);
    setAccessError(undefined);
    try {
      setAccessWorkspace(
        await replaceAccessAssignment(activeEdition, assignmentId, input),
      );
    } catch (error: unknown) {
      setAccessError(
        error instanceof Error ? error.message : "Access could not be changed.",
      );
      throw error;
    } finally {
      setAccessBusy(false);
    }
  }

  async function revokeAccess(
    assignmentId: string,
    reason: string,
  ): Promise<void> {
    setAccessBusy(true);
    setAccessError(undefined);
    try {
      setAccessWorkspace(
        await revokeAccessAssignment(activeEdition, assignmentId, reason),
      );
    } catch (error: unknown) {
      setAccessError(
        error instanceof Error ? error.message : "Access could not be removed.",
      );
      throw error;
    } finally {
      setAccessBusy(false);
    }
  }

  const destinationContent = activeDestination ? (
    <>
      {activeDestination === "today" && (
        <TodayView
          context={context}
          edition={edition}
          people={people}
          peopleDenied={peopleDenied}
          actions={actions}
          actionsDenied={actionsDenied}
          onNavigate={setDestination}
        />
      )}
      {activeDestination === "my-registration" && (
        <MyRegistrationView edition={edition} />
      )}
      {activeDestination === "people" && (
        <PeopleView
          page={people}
          denied={peopleDenied}
          loading={peopleLoading}
          filters={filters}
          onApplyFilters={setFilters}
          onPage={(page) => setFilters((current) => ({ ...current, page }))}
        />
      )}
      {activeDestination === "workforce" && (
        <WorkforceView edition={edition} />
      )}
      {activeDestination === "commerce" && (
        <RegistrationOperationsView edition={edition} />
      )}
      {activeDestination === "reports" && <ReportsView edition={edition} />}
      {activeDestination === "security" && <SecurityView />}
      {activeDestination === "setup" && (
        <SetupView
          edition={edition}
          canAccessAdvancedRecords={context.can_access_advanced_records}
          onTransitioned={recordLifecycleTransition}
        />
      )}
    </>
  ) : (
    <UnsupportedEditionContext edition={edition} />
  );
  const accessDrawer = accessOpen && accessWorkspace && activeDestination && (
    <AccessDrawer
      workspace={accessWorkspace}
      edition={activeEdition}
      destination={activeDestination}
      busy={accessBusy}
      error={accessError}
      onClose={() => setAccessOpen(false)}
      onAssign={assignAccess}
      onReplace={replaceAccess}
      onRevoke={revokeAccess}
    />
  );
  const embeddedPageAccess = {
    editionName: activeEdition.edition_name,
    workspace: accessWorkspace,
    onOpenAccess:
      embeddedInAdmin && accessWorkspace
        ? () => setAccessOpen(true)
        : undefined,
  };

  if (embeddedInAdmin) {
    return (
      <EmbeddedPageAccessContext.Provider value={embeddedPageAccess}>
        <div className="admin-embedded-shell">
          <div id="main-content" className="admin-embedded-content">
            {destinationContent}
          </div>
          {accessDrawer}
        </div>
      </EmbeddedPageAccessContext.Provider>
    );
  }

  return (
    <EmbeddedPageAccessContext.Provider value={embeddedPageAccess}>
      <div className="shell">
        <a className="skip-link" href="#main-content">Skip to content</a>
        <Sidebar
          destination={activeDestination ?? destination}
          edition={edition}
          onNavigate={setDestination}
          canManageAccess={Boolean(accessWorkspace)}
          canAccessAdvancedRecords={context.can_access_advanced_records}
          onOpenAccess={() => setAccessOpen(true)}
        />
        <div className="workspace">
          <Topbar
            context={context}
            edition={edition}
            onEditionChange={changeEdition}
            canManageAccess={Boolean(accessWorkspace)}
            onOpenAccess={() => setAccessOpen(true)}
          />
          <main id="main-content">{destinationContent}</main>
        </div>
        {accessDrawer}
      </div>
    </EmbeddedPageAccessContext.Provider>
  );
}
