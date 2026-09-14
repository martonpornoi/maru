import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/applications/static/applications/programme_calls.js`, "utf8"
);

function boot(pending = false, personal = false) {
  document.body.innerHTML = `<p data-call-dirty hidden></p>
    <form data-call-command data-call-pending="${pending}">
      <input name="expected_version" value="7" type="hidden">
      <input name="retry_key" value="same-retry" type="hidden">
      <input name="csrfmiddlewaretoken" value="csrf" type="hidden">
      <textarea name="reason">Original reason</textarea>
      ${personal ? `<select name="publication_choice"><option value="">Choose</option><option value="no">No</option><option value="yes">Yes</option></select><input type="checkbox" name="consent_acknowledged"><input name="public_name" value="">` : ""}
      <button>Save</button>
    </form>`;
  new Function("window", "document", source)(window, document);
  return document.querySelector<HTMLFormElement>("form")!;
}
function unload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}
function edit(form: HTMLFormElement, name: string, value: string) {
  const field = form.elements.namedItem(name) as HTMLInputElement;
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}
afterEach(() => { document.body.innerHTML = ""; });

describe("Programme call original-intent navigation guard", () => {
  it("does not block unchanged input or rotating CSRF transport", () => {
    const form = boot();
    expect(unload()).toBe(false);
    edit(form, "csrfmiddlewaretoken", "new-csrf");
    expect(unload()).toBe(false);
  });
  it("warns after edits without changing version or retry identity", () => {
    const form = boot();
    edit(form, "reason", "New retained reason");
    expect(unload()).toBe(true);
    expect(document.querySelector("[data-call-dirty]")).toBeVisible();
    expect(new FormData(form).get("expected_version")).toBe("7");
    expect(new FormData(form).get("retry_key")).toBe("same-retry");
    edit(form, "reason", "Original reason");
    expect(unload()).toBe(false);
  });
  it("treats a returned invalid or conflicting form as pending immediately", () => {
    boot(true);
    expect(unload()).toBe(true);
    expect(document.querySelector("[data-call-dirty]")).toBeVisible();
  });
  it("permits deliberate command submit and restores protection on pageshow", () => {
    const form = boot(true);
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    expect(unload()).toBe(false);
    window.dispatchEvent(new Event("pageshow"));
    expect(unload()).toBe(true);
  });
  it("ignores detached forms and safely handles read-only pages", () => {
    const form = boot(true);
    form.remove();
    expect(unload()).toBe(false);
    new Function("window", "document", source)(window, document);
    expect(unload()).toBe(false);
  });
  it("also protects personal proposal choices without selecting consent", () => {
    const form = boot(false, true);
    const consent = form.elements.namedItem("consent_acknowledged") as HTMLInputElement;
    expect(consent.checked).toBe(false);
    expect(unload()).toBe(false);
    edit(form, "publication_choice", "no");
    expect(unload()).toBe(true);
    expect(consent.checked).toBe(false);
    edit(form, "publication_choice", "");
    expect(unload()).toBe(false);
    consent.checked = true;
    consent.dispatchEvent(new Event("change", { bubbles: true }));
    expect(unload()).toBe(true);
  });
  it("retains a rejected personal profile and evidence without erasing values", () => {
    const form = boot(true, true);
    edit(form, "public_name", "Synthetic private proposal name");
    edit(form, "publication_choice", "no");
    expect(unload()).toBe(true);
    expect(new FormData(form).get("public_name")).toBe("Synthetic private proposal name");
    expect(new FormData(form).get("retry_key")).toBe("same-retry");
    expect(new FormData(form).get("expected_version")).toBe("7");
  });
});
