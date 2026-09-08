import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Load the actual Django asset without widening Vite's served filesystem.
// The application TS project deliberately has browser, not Node, globals.
const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/scheduling/static/scheduling/planning.js`,
  "utf8"
);

const times = [
  "setup_starts_at", "effective_starts_at", "effective_ends_at", "teardown_ends_at"
];
let cleanup: (() => void) | undefined;

function markup(pending = false) {
  return `<div data-planning-workspace>
    <p data-planning-status hidden role="status"></p><p data-planning-dirty hidden></p>
    <h2 id="selected" tabindex="-1" data-maru-focus-on-load>Selected occurrence</h2>
    <a href="/another-edition/" id="leave">Other edition</a>
    <a href="#selected" id="anchor">Selected item</a>
    <form data-planning-navigation id="filters"><input name="ui_candidate_id" value="draft-b"><button>Change view</button></form>
    <form data-planning-destination data-planning-navigation id="destination">
      <input name="action" value="select" type="hidden"><input name="ui_mode" value="placement" type="hidden">
      <input name="ui_candidate_id" value="draft-a" type="hidden"><input name="csrfmiddlewaretoken" value="synthetic" type="hidden">
      <select name="ui_occurrence_id" required><option value="">Choose</option><option value="occ-a" selected>First</option><option value="occ-b">Second</option></select>
      <select name="ui_day_id" required><option value="">Choose</option><option value="day-a" selected>Friday</option><option value="day-b">Saturday</option></select>
      <select name="ui_space_id" required><option value="">Choose</option><option value="room-a" selected>Hall</option><option value="room-b">Studio</option></select>
      <button>Open form</button><p data-planning-drop-selected hidden>Drop here</p>
    </form>
    <article data-planning-entry data-occurrence="occ-b">Synthetic private title</article>
    <article data-planning-entry data-occurrence="retired">Retired</article>
    <section data-planning-lane data-day="day-b" data-space="room-b">Saturday Studio</section>
    <form id="command" data-planning-command data-planning-pending="${pending}">
      <input type="hidden" name="retry_key" value="exact-retry"><input type="hidden" name="expected_version" value="7">
      <input type="hidden" name="csrfmiddlewaretoken" value="synthetic">
      <textarea name="reason">Existing reason</textarea>
      <input name="host_example_starts_at" value="2030-08-02T10:15+02:00">
      ${times.map((name, index) => `<input name="${name}" value="2030-08-02T10:${String(index * 15).padStart(2, "0")}+02:00">`).join("")}
      <fieldset data-planning-time-controls data-zone="Europe/Budapest" data-start="2030-08-02T08:00:00+02:00" data-end="2030-08-02T20:00:00+02:00" data-step="5" hidden>
        ${times.map((name, index) => `<label for="range-${index}">${name}</label><input id="range-${index}" type="range" data-planning-time="${name}"><output for="range-${index}"></output>`).join("")}
      </fieldset>
      <button name="action" value="preview_placement">Preview</button><button name="action" value="save_placement">Save</button>
    </form>
  </div>`;
}

function boot(html = markup()) {
  document.body.innerHTML = html;
  cleanup = new Function("window", "document", "return " + source)(window, document);
}

function input(name: string) {
  return document.querySelector<HTMLInputElement>(`#command [name="${name}"]`)!;
}

function submit(id: string) {
  const event = new SubmitEvent("submit", { bubbles: true, cancelable: true });
  document.getElementById(id)!.dispatchEvent(event);
  return event;
}

function unload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

function edit(name: string, value: string) {
  input(name).value = value;
  input(name).dispatchEvent(new Event("input", { bubbles: true }));
}

function dragEvent(element: Element, type: string, dataTransfer?: object) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
  element.dispatchEvent(event);
  return event;
}

function destinationSubmission() {
  const form = document.querySelector<HTMLFormElement>("#destination")!;
  const request = vi.spyOn(form, "requestSubmit").mockImplementation(() => {
    form.dispatchEvent(new SubmitEvent("submit", { bubbles: true, cancelable: true }));
  });
  return { form, request };
}

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
});

afterEach(() => {
  cleanup?.();
  cleanup = undefined;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("page-local pending intent", () => {
  it("does not warn for fresh unchanged controls and restores selected focus", () => {
    boot();
    expect(unload().defaultPrevented).toBe(false);
    expect(document.activeElement?.id).toBe("selected");
    expect(document.querySelector("[data-planning-dirty]")).not.toBeVisible();
    expect(submit("filters").defaultPrevented).toBe(false);
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it("cancels a view change and retains the exact input, retry and version", () => {
    boot();
    edit("reason", "Unsaved private reason");
    expect(submit("filters").defaultPrevented).toBe(true);
    expect(input("reason").value).toBe("Unsaved private reason");
    expect(input("retry_key").value).toBe("exact-retry");
    expect(input("expected_version").value).toBe("7");
    expect(unload().defaultPrevented).toBe(true);
    expect(document.querySelector("[data-planning-dirty]")).toBeVisible();
  });

  it("warns for a returned preview or failed form even before more typing", () => {
    boot(markup(true));
    expect(unload().defaultPrevented).toBe(true);
    expect(submit("filters").defaultPrevented).toBe(true);
  });

  it("does not prompt over explicit command submission or rewrite its key", () => {
    boot(markup(true));
    expect(submit("command").defaultPrevented).toBe(false);
    expect(window.confirm).not.toHaveBeenCalled();
    expect(unload().defaultPrevented).toBe(false);
    expect(input("retry_key").value).toBe("exact-retry");
    window.dispatchEvent(new Event("pageshow"));
    expect(unload().defaultPrevented).toBe(true);
  });

  it("restores protection after editing when a submission did not navigate", () => {
    boot(markup(true));
    submit("command");
    edit("reason", "Still editing");
    expect(unload().defaultPrevented).toBe(true);
  });

  it("allows deliberate discard without a second unload confirmation", () => {
    boot(markup(true));
    vi.mocked(window.confirm).mockReturnValue(true);
    expect(submit("filters").defaultPrevented).toBe(false);
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(unload().defaultPrevented).toBe(false);
  });

  it("guards edition links but not same-page error/selection anchors", () => {
    boot(markup(true));
    const leave = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("leave")!.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true);
    vi.mocked(window.confirm).mockClear();
    document.getElementById("anchor")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it("does not count a CSRF refresh as a changed intent", () => {
    boot();
    edit("csrfmiddlewaretoken", "refreshed");
    expect(unload().defaultPrevented).toBe(false);
  });

  it("stops guarding when the workspace is removed", () => {
    boot(markup(true));
    document.body.innerHTML = "";
    expect(unload().defaultPrevented).toBe(false);
  });
});

describe("pointer and native destination parity", () => {
  it("opens only a native selection POST for the exact occurrence/day/room", () => {
    boot();
    const { form, request } = destinationSubmission();
    const payload = { setData: vi.fn() };
    const card = document.querySelector("[data-occurrence='occ-b']")!;
    const lane = document.querySelector("[data-planning-lane]")!;
    dragEvent(card, "dragstart", payload);
    expect(dragEvent(lane, "dragover", payload).defaultPrevented).toBe(true);
    dragEvent(lane, "drop", payload);
    expect(request).toHaveBeenCalledOnce();
    expect(Object.fromEntries(new FormData(form))).toEqual({
      action: "select", ui_mode: "placement", ui_candidate_id: "draft-a",
      ui_occurrence_id: "occ-b", ui_day_id: "day-b", ui_space_id: "room-b",
      csrfmiddlewaretoken: "synthetic"
    });
    expect(payload.setData).toHaveBeenCalledWith("text/plain", "Maru placement selection");
    expect(input("retry_key").value).toBe("exact-retry");
    expect(input("expected_version").value).toBe("7");
    expect(input(times[0]).value).toBe("2030-08-02T10:00+02:00");
  });

  it("uses the same chosen destination for an empty board", () => {
    boot();
    const { form, request } = destinationSubmission();
    dragEvent(document.querySelector("[data-occurrence='occ-b']")!, "dragstart", { setData: vi.fn() });
    dragEvent(document.querySelector("[data-planning-drop-selected]")!, "drop");
    expect(request).toHaveBeenCalledOnce();
    expect(new FormData(form).get("ui_day_id")).toBe("day-a");
    expect(new FormData(form).get("ui_space_id")).toBe("room-a");
  });

  it("never accepts an external payload or makes a retired item draggable", () => {
    boot();
    const { request } = destinationSubmission();
    dragEvent(document.querySelector("[data-planning-lane]")!, "drop", { getData: () => "occ-b" });
    expect(request).not.toHaveBeenCalled();
    expect(document.querySelector<HTMLElement>("[data-occurrence='retired']")!.draggable).toBe(false);
  });

  it("rejects a destination outside the native choices without changing fields", () => {
    boot();
    const { form, request } = destinationSubmission();
    const before = Array.from(new FormData(form));
    const lane = document.querySelector<HTMLElement>("[data-planning-lane]")!;
    lane.dataset.day = "foreign-day";
    dragEvent(document.querySelector("[data-occurrence='occ-b']")!, "dragstart", { setData: vi.fn() });
    dragEvent(lane, "drop");
    expect(request).not.toHaveBeenCalled();
    expect(Array.from(new FormData(form))).toEqual(before);
  });

  it("cancels a drag with Escape", () => {
    boot();
    const { request } = destinationSubmission();
    dragEvent(document.querySelector("[data-occurrence='occ-b']")!, "dragstart", { setData: vi.fn() });
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    dragEvent(document.querySelector("[data-planning-lane]")!, "drop");
    expect(request).not.toHaveBeenCalled();
    expect(document.querySelector(".planning-drag-active")).toBeNull();
  });

  it("runs the unsaved-input guard before a pointer selection can navigate", () => {
    boot(markup(true));
    const { form } = destinationSubmission();
    const observed: boolean[] = [];
    document.addEventListener("submit", (event) => observed.push(event.defaultPrevented), { once: true });
    dragEvent(document.querySelector("[data-occurrence='occ-b']")!, "dragstart", { setData: vi.fn() });
    dragEvent(document.querySelector("[data-planning-lane]")!, "drop");
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(observed).toEqual([true]);
    expect(new FormData(form).get("action")).toBe("select");
    expect(input("reason").value).toBe("Existing reason");
  });
});

describe("exact day-grid time prefill", () => {
  it("does not alter any original value on initialization", () => {
    boot();
    expect(document.querySelector("[data-planning-time-controls]")).toBeVisible();
    expect(input(times[0]).value).toBe("2030-08-02T10:00+02:00");
    expect(document.querySelector<HTMLInputElement>("#range-0")!.value).toBe("120");
    expect(unload().defaultPrevented).toBe(false);
  });

  it.each(times)("prefills only %s, never other phases, host times, reason or versions", (name) => {
    boot();
    const form = document.querySelector<HTMLFormElement>("#command")!;
    const before = Object.fromEntries(new FormData(form));
    const range = document.querySelector<HTMLInputElement>(`[data-planning-time='${name}']`)!;
    range.value = "180";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(Object.fromEntries(new FormData(form))).toEqual({ ...before, [name]: "2030-08-02T11:00+02:00" });
    expect(range.getAttribute("aria-valuetext")).toBe("2030-08-02T11:00+02:00");
    expect(unload().defaultPrevented).toBe(true);
    expect(document.querySelector("[data-planning-status]")).toHaveTextContent("Required host intervals are unchanged");
  });

  it.each(["", "2030-08-02T10:00", "2030-02-30T10:00+02:00", "2030-08-02T10:03+02:00", "2030-08-01T10:00+02:00"])(
    "does not normalize, round, fill or clamp %s", (value) => {
      boot();
      edit(times[0], value);
      expect(input(times[0]).value).toBe(value);
      expect(document.querySelector<HTMLOutputElement>("output[for='range-0']")!.value).toMatch(/Not set|retained/);
    }
  );

  it("disambiguates both sides of the repeated Budapest hour", () => {
    boot(markup().replace("2030-08-02T08:00:00+02:00", "2030-10-27T00:00:00+02:00")
      .replace("2030-08-02T20:00:00+02:00", "2030-10-27T06:00:00+01:00"));
    const range = document.querySelector<HTMLInputElement>("#range-0")!;
    range.value = "150";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(input(times[0]).value).toBe("2030-10-27T02:30+02:00");
    range.value = "210";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(input(times[0]).value).toBe("2030-10-27T02:30+01:00");
  });

  it("skips the nonexistent spring-forward hour without guessing a local minute", () => {
    boot(markup().replace("2030-08-02T08:00:00+02:00", "2030-03-31T00:00:00+01:00")
      .replace("2030-08-02T20:00:00+02:00", "2030-03-31T06:00:00+02:00"));
    const range = document.querySelector<HTMLInputElement>("#range-0")!;
    range.value = "150";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(input(times[0]).value).toBe("2030-03-31T03:30+02:00");
  });

  it("retains the next calendar date across an overnight service day", () => {
    boot(markup().replace("2030-08-02T08:00:00+02:00", "2030-08-02T20:00:00+02:00")
      .replace('data-end="2030-08-02T20:00:00+02:00"', 'data-end="2030-08-03T03:00:00+02:00"'));
    const range = document.querySelector<HTMLInputElement>("#range-0")!;
    range.value = "270";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(input(times[0]).value).toBe("2030-08-03T00:30+02:00");
  });

  it.each(["", "Not/AZone"])("keeps shortcuts closed for an unavailable trusted zone: %s", (zone) => {
    boot(markup().replace('data-zone="Europe/Budapest"', `data-zone="${zone}"`));
    expect(document.querySelector("[data-planning-time-controls]")).not.toBeVisible();
    expect(input(times[0]).value).toBe("2030-08-02T10:00+02:00");
  });

  it("does not perform network requests or persist private state", () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const fetcher = vi.spyOn(globalThis, "fetch");
    boot();
    edit("reason", "Private unsaved rationale");
    const range = document.querySelector<HTMLInputElement>("#range-0")!;
    range.value = "180";
    range.dispatchEvent(new Event("input", { bubbles: true }));
    expect(storage).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });
});
