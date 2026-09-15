import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/scheduling/static/scheduling/release_workspace.js`, "utf8"
);

function boot(pending = false, count = 1) {
  document.body.innerHTML = Array.from({ length: count }, (_, index) => `
    <form data-release-command data-release-pending="${pending}">
      <p data-release-dirty hidden></p>
      <input name="expected_release_version" value="7" type="hidden">
      <input name="retry_key" value="original-${index}" type="hidden">
      <input name="csrfmiddlewaretoken" value="csrf" type="hidden">
      <textarea name="reason">Original reason</textarea><button>Save</button>
    </form>`).join("");
  new Function("window", "document", source)(window, document);
  return Array.from(document.querySelectorAll<HTMLFormElement>("form"));
}
function unload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}
function edit(form: HTMLFormElement, value: string, name = "reason") {
  const field = form.elements.namedItem(name) as HTMLInputElement;
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}
afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

describe("Release exact-intent navigation guard", () => {
  it("ignores unchanged forms and rotating CSRF without modifying original intent", () => {
    const [form] = boot();
    expect(unload()).toBe(false);
    edit(form, "rotated", "csrfmiddlewaretoken");
    expect(unload()).toBe(false);
    edit(form, "Explicit reason");
    expect(unload()).toBe(true);
    expect(form.querySelector("[data-release-dirty]")).toBeVisible();
    expect(new FormData(form).get("expected_release_version")).toBe("7");
    expect(new FormData(form).get("retry_key")).toBe("original-0");
  });
  it("protects pending returned input immediately and restores on pageshow", () => {
    const [form] = boot(true);
    expect(unload()).toBe(true);
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    expect(unload()).toBe(false);
    window.dispatchEvent(new Event("pageshow"));
    expect(unload()).toBe(true);
  });
  it("does not discard another action's reason when the user cancels confirmation", () => {
    const [warning, approval] = boot(false, 2);
    edit(warning, "My unsaved warning reason");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const event = new Event("submit", { cancelable: true });
    approval.dispatchEvent(event);
    expect(confirm).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
    expect(new FormData(warning).get("reason")).toBe("My unsaved warning reason");
    expect(unload()).toBe(true);
  });
  it("permits deliberate discard and one explicit submit without a second unload prompt", () => {
    const [warning, approval] = boot(false, 2);
    edit(warning, "Unsaved warning reason");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const event = new Event("submit", { cancelable: true });
    approval.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(unload()).toBe(false);
    window.dispatchEvent(new Event("pageshow"));
    expect(unload()).toBe(true);
  });
  it("does not duplicate handlers, ignores detached forms and accepts read-only pages", () => {
    const [form] = boot(true);
    new Function("window", "document", source)(window, document);
    form.remove();
    expect(unload()).toBe(false);
    new Function("window", "document", source)(window, document);
    expect(unload()).toBe(false);
  });
});
