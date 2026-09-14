import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/programme/static/programme/hosts.js`, "utf8"
);
const guard = readFileSync(
  `${cwd()}/../../src/maru/programme/static/programme/workbench.js`, "utf8"
);

function boot(count = "0") {
  document.body.innerHTML = `<p data-programme-dirty hidden></p>
    <form data-programme-command>
      <input type="hidden" name="periods-TOTAL_FORMS" value="${count}">
      <input type="hidden" name="expected_item_version" value="7">
      <input type="hidden" name="idempotency_key" value="original-retry">
      <div data-host-periods></div>
      <template data-host-empty-period><fieldset data-host-period>
        <legend>Additional availability period</legend>
        <label for="id_periods-__prefix__-starts_at">Start</label>
        <input id="id_periods-__prefix__-starts_at" name="periods-__prefix__-starts_at" type="datetime-local">
      </fieldset></template>
      <button type="button" data-host-add-period data-host-limit="128">Add</button>
      <p data-host-period-status role="status"></p>
    </form>`;
  new Function("window", "document", guard)(window, document);
  new Function("document", source)(document);
  return document.querySelector<HTMLButtonElement>("button")!;
}
afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

describe("Explicit hosting availability rows", () => {
  it("adds labelled unique fields, focuses them and keeps command identity", () => {
    const button = boot();
    button.click();
    button.click();
    expect(document.querySelectorAll("[data-host-period]")).toHaveLength(2);
    expect(document.activeElement).toHaveAttribute("id", "id_periods-1-starts_at");
    expect(document.querySelector('label[for="id_periods-1-starts_at"]')).toBeVisible();
    expect(document.querySelector("[data-host-period-status]")).toHaveTextContent("Nothing is saved");
    const data = new FormData(document.querySelector("form")!);
    expect(data.get("periods-TOTAL_FORMS")).toBe("2");
    expect(data.get("expected_item_version")).toBe("7");
    expect(data.get("idempotency_key")).toBe("original-retry");
  });
  it("marks pending input without submitting or saving it", () => {
    const button = boot();
    const submit = vi.fn();
    document.querySelector("form")!.addEventListener("submit", submit);
    button.click();
    expect(submit).not.toHaveBeenCalled();
    expect(document.querySelector("[data-programme-dirty]")).toBeVisible();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
  it("stops at the fixed bound even when repeatedly clicked", () => {
    const button = boot("127");
    button.click();
    expect(button).toBeDisabled();
    button.click();
    expect(document.querySelectorAll("[data-host-period]")).toHaveLength(1);
    expect(document.querySelector('[name="periods-TOTAL_FORMS"]')).toHaveValue("128");
  });
  it.each(["bad", "-1", "129"])("does not allocate for malformed count %s", (count) => {
    const button = boot(count);
    expect(button).toBeDisabled();
    button.click();
    expect(document.querySelectorAll("[data-host-period]")).toHaveLength(0);
  });
  it("handles absent controls and empty templates without a partial row", () => {
    document.body.innerHTML = '<button data-host-add-period></button>';
    expect(() => new Function("document", source)(document)).not.toThrow();
    const button = boot();
    document.querySelector("template")!.innerHTML = "";
    button.click();
    expect(document.querySelector('[name="periods-TOTAL_FORMS"]')).toHaveValue("0");
  });
});
