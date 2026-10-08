import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/core/static/core/navigation.js`,
  "utf8"
);

function boot() {
  document.body.innerHTML = `
    <a href="#nav-advanced-records" data-navigation-specialist-gateway>Open advanced records</a>
    <nav id="nav-sidebar">
      <input id="nav-filter"><p id="maru-navigation-search-status" hidden></p>
      <p data-navigation-empty hidden>No available page</p>
      <details data-navigation-group="people" data-navigation-group-kind="task">
        <summary>People & teams <span data-navigation-group-count>2</span></summary>
        <ul>
          <li data-navigation-item data-navigation-search="team workspace workforce staff" data-navigation-kind="destination"><a href="/team/">Team workspace</a></li>
          <li data-navigation-item data-navigation-search="people attendees" data-navigation-kind="destination"><a href="/people/">People</a></li>
        </ul>
      </details>
      <details data-navigation-group="settings" data-navigation-group-kind="task" data-navigation-current="true" open>
        <summary>Settings <span data-navigation-group-count>1</span></summary>
        <ul><li data-navigation-item data-navigation-search="accounts users café" data-navigation-kind="destination"><a href="/accounts/" aria-current="page">User accounts</a></li></ul>
      </details>
      <details data-navigation-group="actions" data-navigation-group-kind="task" data-navigation-search-only="true">
        <summary>Actions</summary>
        <ul><li data-navigation-item data-navigation-search="invite user staff" data-navigation-kind="action"><a href="/invite/">Invite account</a></li></ul>
      </details>
      <details id="nav-advanced-records" data-navigation-group="advanced-records" data-navigation-group-kind="advanced">
        <summary>Advanced records <span data-navigation-group-count>1</span></summary>
        <ul><li data-navigation-item data-navigation-search="user staff account technical" data-navigation-kind="specialist"><a href="/record/">Account record</a></li></ul>
      </details>
    </nav>`;
  new Function(source)();
}

function group(name: string) {
  return document.querySelector<HTMLDetailsElement>(`[data-navigation-group="${name}"]`)!;
}

function search(value: string) {
  const input = document.getElementById("nav-filter") as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event("input"));
  return input;
}

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("shared task navigation", () => {
  it("keeps the current group open and optional actions out of the default menu", () => {
    boot();
    expect(group("settings").open).toBe(true);
    expect(group("people").open).toBe(false);
    expect(group("actions").hidden).toBe(true);
    expect(group("advanced-records").open).toBe(false);
  });

  it("finds task synonyms across closed groups and leaves advanced matches collapsed", () => {
    boot();
    search("staff");
    expect(group("people").open).toBe(true);
    expect(group("people").querySelector("[data-navigation-group-count]")?.textContent).toBe("1");
    expect(group("actions").hidden).toBe(false);
    expect(group("actions").open).toBe(true);
    expect(group("settings").hidden).toBe(true);
    expect(group("advanced-records").hidden).toBe(false);
    expect(group("advanced-records").open).toBe(false);
    expect(document.getElementById("maru-navigation-search-status")?.textContent).toBe("2 pages · 1 in Advanced records");
  });

  it("clears search with Escape and restores the person's earlier open groups", () => {
    boot();
    group("people").open = true;
    const input = search("users cafe");
    expect(group("settings").hidden).toBe(false);
    expect(group("people").hidden).toBe(true);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }));
    expect(input.value).toBe("");
    expect(group("people").hidden).toBe(false);
    expect(group("people").open).toBe(true);
    expect(group("settings").open).toBe(true);
    expect(group("advanced-records").open).toBe(false);
    expect(group("actions").hidden).toBe(true);
    expect(document.getElementById("nav-sidebar")).not.toHaveClass("maru-navigation-searching");
  });

  it("shows the empty state without inventing any destination", () => {
    boot();
    search("foreign hidden tenant");
    expect(document.querySelector<HTMLElement>("[data-navigation-empty]")?.hidden).toBe(false);
    expect(document.querySelectorAll("[data-navigation-item]:not([hidden])")).toHaveLength(0);
    expect(document.querySelectorAll("[data-navigation-item]")).toHaveLength(5);
  });

  it("opens advanced records from the home gateway and focuses its disclosure", () => {
    boot();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 0;
    });
    group("advanced-records").scrollIntoView = vi.fn();
    search("no match");
    document.querySelector<HTMLAnchorElement>("[data-navigation-specialist-gateway]")!.click();
    expect(group("advanced-records").open).toBe(true);
    expect(group("advanced-records").hidden).toBe(false);
    expect(document.activeElement).toBe(group("advanced-records").querySelector("summary"));
    expect((document.getElementById("nav-filter") as HTMLInputElement).value).toBe("");
  });
});
