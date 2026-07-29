import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  activateRegistrationConfiguration,
  ApiError,
  type ActionItem,
  type AttendeeReport,
  type AttendeeReportFilters,
  badgeExportPath,
  changeRegistrationPaymentDeadline,
  checkInRegistration,
  confirmMyDemoPayment,
  createRegistrationDraft,
  type EditionContext,
  loadActions,
  loadAttendeeReport,
  loadMyContext,
  loadMyRegistration,
  loadParticipations,
  loadProfileMediaReviews,
  loadRegistrationConfiguration,
  loadRegistrationReconciliation,
  loadSecurityHistory,
  loadStaffRegistrations,
  type MyContext,
  type MyRegistrationWorkspace,
  type Participation,
  type ParticipationFilters,
  type ParticipationPage,
  type ProfileMediaReviewItem,
  type RegistrationConfigurationWorkspace,
  type RegistrationReconciliation,
  type RegistrationQuestion,
  type SecurityEvent,
  type StaffRegistration,
  type StaffRegistrationPage,
  publishRegistrationTemplate,
  reviewProfileMedia,
  submitMyRegistration,
  waiveRegistrationPayment,
} from "./api/client";
import {
  capacityCounts,
  chooseInitialEdition,
  daysUntil,
  formatDateRange,
  greetingFor,
  lifecycleLabel,
  primaryCapacity,
  weekdayLabel,
} from "./model";

type Destination =
  | "today"
  | "my-registration"
  | "people"
  | "commerce"
  | "reports"
  | "security";

const upcomingDestinations = [
  "Work",
  "Plan",
  "Programme",
  "Workforce",
  "Communications",
  "Operations",
];

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

function LoadingScreen() {
  return (
    <main className="center-state" aria-live="polite">
      <span className="brand-mark">M</span>
      <div className="loading-line" />
      <p>Opening your convention workspace…</p>
    </main>
  );
}

function ErrorScreen({ message }: { message: string }) {
  return (
    <main className="center-state">
      <span className="brand-mark">M</span>
      <h1>We couldn’t open your workspace</h1>
      <PageHelp
        purpose="This page explains why the workspace could not load."
        examples="check the message below, then retry after the problem is resolved"
      />
      <p>{message}</p>
      <button className="primary-button" onClick={() => window.location.reload()}>
        Try again
      </button>
    </main>
  );
}

function EmptyContext({ context }: { context: MyContext }) {
  return (
    <main className="center-state">
      <span className="brand-mark">M</span>
      <p className="eyebrow">Signed in as {context.display_name}</p>
      <h1>No convention workspace yet</h1>
      <PageHelp
        purpose="This page shows when your account has no convention relationship."
        examples="ask an organizer to add you, or sign out and use another account"
      />
      <p>
        Your account is active, but it is not participating in an event edition.
        Ask an organizer to add the appropriate relationship.
      </p>
      <button
        className="secondary-button"
        onClick={() =>
          document.querySelector<HTMLFormElement>("#maru-logout-form")?.submit()
        }
      >
        Sign out
      </button>
    </main>
  );
}

function Sidebar({
  destination,
  edition,
  onNavigate,
}: {
  destination: Destination;
  edition: EditionContext;
  onNavigate: (destination: Destination) => void;
}) {
  return (
    <aside className="sidebar">
      <a className="brand" href="/staff/" aria-label="Maru Staff Console home">
        <span className="brand-mark">M</span>
        <span>
          <strong>Maru</strong>
          <small>Staff Console</small>
        </span>
      </a>

      <nav className="primary-nav" aria-label="Staff Console">
        <p className="nav-heading">Workspace</p>
        <button
          className={destination === "today" ? "nav-item active" : "nav-item"}
          aria-current={destination === "today" ? "page" : undefined}
          onClick={() => onNavigate("today")}
        >
          <Icon>◌</Icon> Today
        </button>
        <button
          className={
            destination === "my-registration" ? "nav-item active" : "nav-item"
          }
          aria-current={destination === "my-registration" ? "page" : undefined}
          onClick={() => onNavigate("my-registration")}
        >
          <Icon>◇</Icon> My registration
        </button>
        <button
          className={destination === "people" ? "nav-item active" : "nav-item"}
          aria-current={destination === "people" ? "page" : undefined}
          onClick={() => onNavigate("people")}
        >
          <Icon>◎</Icon> People
        </button>
        <button
          className={destination === "commerce" ? "nav-item active" : "nav-item"}
          aria-current={destination === "commerce" ? "page" : undefined}
          onClick={() => onNavigate("commerce")}
        >
          <Icon>▣</Icon> Commerce
        </button>
        <button
          className={destination === "reports" ? "nav-item active" : "nav-item"}
          aria-current={destination === "reports" ? "page" : undefined}
          onClick={() => onNavigate("reports")}
        >
          <Icon>▥</Icon> Reports
        </button>
        <button
          className={destination === "security" ? "nav-item active" : "nav-item"}
          aria-current={destination === "security" ? "page" : undefined}
          onClick={() => onNavigate("security")}
        >
          <Icon>◈</Icon> Security
        </button>
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
      </nav>

      <div className="sidebar-foot">
        <button
          type="submit"
          form="maru-admin-context-form"
          name="edition_id"
          value={edition.edition_id}
        >
          Bootstrap admin <span aria-hidden="true">↗</span>
        </button>
        <span>Maru foundation · local</span>
      </div>
    </aside>
  );
}

function Topbar({
  context,
  edition,
  onEditionChange,
}: {
  context: MyContext;
  edition: EditionContext;
  onEditionChange: (edition: EditionContext) => void;
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
        <span className="avatar" aria-hidden="true">
          {context.display_name.trim().charAt(0).toUpperCase() || "M"}
        </span>
        <span className="account-name">
          <strong>{context.display_name}</strong>
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
  const firstName = context.display_name.split(" ")[0] || context.display_name;

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
          <span className="metric-label">People in edition</span>
          <strong>{peopleDenied ? "—" : people?.count ?? "…"}</strong>
          <small>{peopleDenied ? "Restricted for your role" : "Current records"}</small>
        </article>
        <article>
          <span className="metric-label">Role types</span>
          <strong>{peopleDenied ? "—" : roleCounts.length}</strong>
          <small>Across this result set</small>
        </article>
        <article>
          <span className="metric-label">Languages</span>
          <strong>{edition.language_codes.length}</strong>
          <small>{edition.language_codes.join(" · ").toUpperCase()}</small>
        </article>
        <article>
          <span className="metric-label">Currencies</span>
          <strong>{edition.currency_codes.length}</strong>
          <small>{edition.currency_codes.join(" · ")}</small>
        </article>
      </section>

      <div className="dashboard-grid">
        <section className="panel" aria-labelledby="attention-heading">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Action center</p>
              <h2 id="attention-heading">What needs attention</h2>
            </div>
            <span className="quiet-badge">
              {actionsDenied ? "Restricted" : `${actions.length} open`}
            </span>
          </div>
          {actionsDenied ? (
            <p className="muted-copy">
              No assigned-work projection is available for this role.
            </p>
          ) : actions.length ? (
            <ol className="action-list">
              {actions.map((action) => (
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
                  <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                  <span>{label}</span>
                  <strong>{count}</strong>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted-copy">No role labels have been recorded.</p>
          )}
        </section>
      </div>
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
    <div className="drawer-scrim" onMouseDown={onClose}>
      <aside
        className="person-drawer"
        aria-labelledby="person-name"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="drawer-close" onClick={onClose} aria-label="Close">
          ×
        </button>
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
      </aside>
    </div>
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

function CommerceView({ edition }: { edition: EditionContext }) {
  const [configuration, setConfiguration] =
    useState<RegistrationConfigurationWorkspace>();
  const [configurationDenied, setConfigurationDenied] = useState(false);
  const [registrations, setRegistrations] = useState<StaffRegistrationPage>();
  const [registrationsDenied, setRegistrationsDenied] = useState(false);
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

  function refreshRegistrations() {
    setRegistrationsDenied(false);
    void loadStaffRegistrations(edition)
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
      });
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
    setError(undefined);
    setSelected(undefined);
    refreshConfiguration();
    refreshRegistrations();
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
          <p className="eyebrow">Registration and attendee service</p>
          <h1>Commerce</h1>
          <PageHelp
            purpose="Use this page to configure registration and serve attendees through arrival."
            examples="copy last year’s setup, activate a reviewed draft, or check in a paid attendee"
          />
        </div>
        <span className="record-count">
          {registrationsDenied ? "Restricted" : `${registrations?.count ?? 0} records`}
        </span>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}

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
                href={`/staff/registration-assist/${edition.edition_id}/`}
              >
                Add attendee outside public hours
              </a>
              <a
                href={`/admin/workforce/position/?edition__id__exact=${edition.edition_id}`}
              >
                Manage hierarchy and positions in bootstrap admin ↗
              </a>
              <a
                href={`/admin/workforce/onboardingdocumentrequest/?edition__id__exact=${edition.edition_id}`}
              >
                Request or review volunteer agreements ↗
              </a>
              <a href={`/volunteer/${edition.edition_id}/`}>
                Preview published volunteer opportunities ↗
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
                    href={`/admin/registration/registrationconfiguration/${draftId}/change/`}
                  >
                    Edit questions and products in bootstrap admin ↗
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
                      {product.provider_paid} Â·{" "}
                      {formatMoney(
                        product.provider_paid_minor,
                        product.currency,
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Waived</dt>
                    <dd>
                      {product.waived} Â·{" "}
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

      {registrationsDenied ? (
        <section className="permission-state">
          <h2>Registration service is not available for your role</h2>
          <p>
            Maru did not expose attendee names, counts, payment state, or
            registration existence.
          </p>
        </section>
      ) : (
        <section className="people-table-wrap commerce-table">
          <table>
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
              {registrations?.results.map((registration) => (
                <tr key={registration.id}>
                  <td>
                    <button
                      className="person-link"
                      onClick={() => setSelected(registration)}
                    >
                      <span className="table-avatar" aria-hidden="true">
                        {registration.display_name.charAt(0).toUpperCase()}
                      </span>
                      <strong>{registration.display_name}</strong>
                    </button>
                  </td>
                  <td>{registration.reference}</td>
                  <td>{registration.product_name}</td>
                  <td><StatusPill lifecycle={registration.state} /></td>
                  <td>
                    <button
                      className="row-open"
                      aria-label={`Open ${registration.reference}`}
                      onClick={() => setSelected(registration)}
                    >
                      →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {registrations?.results.length === 0 && (
            <div className="table-empty">
              <strong>No attendee registrations yet</strong>
              <span>New submissions will appear in this edition-scoped queue.</span>
            </div>
          )}
        </section>
      )}

      {selected && (
        <div className="drawer-scrim" onMouseDown={() => setSelected(undefined)}>
          <aside
            className="person-drawer registration-drawer"
            aria-labelledby="registration-person"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              className="drawer-close"
              onClick={() => setSelected(undefined)}
              aria-label="Close"
            >
              ×
            </button>
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
          </aside>
        </div>
      )}
    </div>
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

export default function App() {
  const [context, setContext] = useState<MyContext>();
  const [edition, setEdition] = useState<EditionContext>();
  const [destination, setDestination] = useState<Destination>("today");
  const [people, setPeople] = useState<ParticipationPage>();
  const [peopleDenied, setPeopleDenied] = useState(false);
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [actionsDenied, setActionsDenied] = useState(false);
  const [filters, setFilters] = useState<ParticipationFilters>({ page: 1 });
  const [fatalError, setFatalError] = useState<string>();

  useEffect(() => {
    void loadMyContext()
      .then((loaded) => {
        setContext(loaded);
        setEdition(chooseInitialEdition(loaded.editions));
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          window.location.assign("/accounts/login/?next=/staff/");
          return;
        }
        setFatalError(
          error instanceof Error ? error.message : "An unexpected error occurred.",
        );
      });
  }, []);

  useEffect(() => {
    if (!edition) return;
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

  if (fatalError) return <ErrorScreen message={fatalError} />;
  if (!context) return <LoadingScreen />;
  if (!edition) return <EmptyContext context={context} />;

  function changeEdition(next: EditionContext) {
    window.localStorage.setItem("maru.staff.edition", next.edition_id);
    setEdition(next);
    setFilters({ page: 1 });
    setPeople(undefined);
    setActions([]);
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <Sidebar
        destination={destination}
        edition={edition}
        onNavigate={setDestination}
      />
      <div className="workspace">
        <Topbar
          context={context}
          edition={edition}
          onEditionChange={changeEdition}
        />
        <main id="main-content">
          {destination === "today" && (
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
          {destination === "my-registration" && (
            <MyRegistrationView edition={edition} />
          )}
          {destination === "people" && (
            <PeopleView
              page={people}
              denied={peopleDenied}
              loading={peopleLoading}
              filters={filters}
              onApplyFilters={setFilters}
              onPage={(page) => setFilters((current) => ({ ...current, page }))}
            />
          )}
          {destination === "commerce" && <CommerceView edition={edition} />}
          {destination === "reports" && <ReportsView edition={edition} />}
          {destination === "security" && <SecurityView />}
        </main>
      </div>
    </div>
  );
}
