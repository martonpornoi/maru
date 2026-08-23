import type { EditionContext, Participation } from "./api/client";

const activeLifecycles = new Set(["preparing", "ready", "live", "closing"]);

export function chooseInitialEdition(
  editions: EditionContext[],
  preferredEditionId?: string,
): EditionContext | undefined {
  const preferredEdition = editions.find(
    (edition) => edition.edition_id === preferredEditionId,
  );
  if (preferredEdition) return preferredEdition;

  const remembered = window.localStorage.getItem("maru.staff.edition");
  const rememberedEdition = editions.find(
    (edition) => edition.edition_id === remembered,
  );
  if (rememberedEdition) return rememberedEdition;

  return (
    [...editions]
      .filter((edition) => activeLifecycles.has(edition.lifecycle))
      .sort((left, right) => left.starts_on.localeCompare(right.starts_on))[0] ??
    [...editions].sort((left, right) =>
      right.starts_on.localeCompare(left.starts_on),
    )[0]
  );
}

export function formatDateRange(edition: EditionContext): string {
  const format = new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return `${format.format(new Date(`${edition.starts_on}T12:00:00`))} – ${format.format(
    new Date(`${edition.ends_on}T12:00:00`),
  )}`;
}

export function daysUntil(startsOn: string, now = new Date()): number {
  const start = new Date(`${startsOn}T12:00:00`);
  const today = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
    12,
  );
  return Math.ceil((start.getTime() - today.getTime()) / 86_400_000);
}

export function capacityCounts(
  participations: Participation[],
): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const participation of participations) {
    for (const label of participation.capacity_labels) {
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort(
    ([leftLabel, leftCount], [rightLabel, rightCount]) =>
      rightCount - leftCount || leftLabel.localeCompare(rightLabel),
  );
}

export function lifecycleLabel(value: string): string {
  return value.replaceAll(/[-_]/g, " ").replace(/\b\w/g, (letter) =>
    letter.toUpperCase(),
  );
}

export function greetingFor(now = new Date()): string {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function weekdayLabel(now = new Date()): string {
  return new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(now);
}

export function primaryCapacity(edition: EditionContext): string {
  const genericCodes = new Set(["attendee", "staff", "volunteer"]);
  return (
    edition.capacities.find((capacity) => !genericCodes.has(capacity.code))
      ?.label_snapshot ??
    edition.capacities[0]?.label_snapshot ??
    "Participant"
  );
}
