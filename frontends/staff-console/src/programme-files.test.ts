import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/applications/static/applications/programme_files.js`, "utf8"
);

function boot(recovery = false) {
  document.body.innerHTML = `<div data-file-upload data-file-intent="original-proof" data-file-endpoint="/file/intake/" data-file-recovery="${recovery}">
    <input name="csrfmiddlewaretoken" value="csrf">
    ${recovery ? "" : '<input type="file" disabled><button data-file-send disabled>Upload</button>'}
    <button data-file-check disabled>Check</button><p role="status" tabindex="-1"></p><p data-file-dirty hidden></p></div>`;
  const fetcher = vi.fn();
  new Function("window", "document", "fetch", source)(window, document, fetcher);
  return {
    fetcher,
    input: document.querySelector<HTMLInputElement>('input[type="file"]'),
    send: document.querySelector<HTMLButtonElement>('[data-file-send]'),
    check: document.querySelector<HTMLButtonElement>('[data-file-check]')!,
    status: document.querySelector('[role="status"]')!,
  };
}
function choose(input: HTMLInputElement, size = 12) {
  const file = new File(["%PDF-1.7"], "private-name.pdf", { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
  return file;
}
function unload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
}
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
const result = (state = "saved", ok = true) => ({ ok, json: async () => ({ state, message: `${state} original outcome` }) });
afterEach(() => { document.body.innerHTML = ""; vi.restoreAllMocks(); });

describe("Supporting PDF original-intent controls", () => {
  it("selects locally, warns on departure and preserves only proof in history", () => {
    const view = boot();
    expect(unload()).toBe(false);
    expect(view.input).not.toBeDisabled();
    expect(view.send).toBeDisabled();
    choose(view.input!);
    expect(view.send).not.toBeDisabled();
    expect(unload()).toBe(true);
    expect(view.fetcher).not.toHaveBeenCalled();
    expect(window.location.search).toContain("intent=original-proof");
    expect(window.location.href).not.toContain("private-name");
  });
  it("sends exact raw bytes once with CSRF and original intent then confirms", async () => {
    const view = boot();
    const file = choose(view.input!);
    view.fetcher.mockResolvedValue(result());
    view.send!.click();
    expect(view.input).toBeDisabled();
    expect(view.send).toBeDisabled();
    expect(view.status).toHaveFocus();
    await settle();
    const [url, options] = view.fetcher.mock.calls[0];
    expect(url.pathname).toBe("/file/intake/");
    expect(options).toEqual({ method: "PUT", body: file, credentials: "same-origin", cache: "no-store", redirect: "error", headers: {
      "X-Maru-File-Intent": "original-proof", "Content-Type": "application/pdf", "X-CSRFToken": "csrf",
    } });
    expect(view.status).toHaveTextContent("saved original outcome");
    expect(unload()).toBe(false);
    view.send!.dispatchEvent(new Event("click"));
    expect(view.fetcher).toHaveBeenCalledTimes(1);
  });
  it("preserves uncertain file input and recovers body-free without resending", async () => {
    const view = boot();
    const file = choose(view.input!);
    view.fetcher.mockRejectedValueOnce(new Error("network"));
    view.send!.click();
    await settle();
    expect(unload()).toBe(true);
    expect(view.input!.files![0]).toBe(file);
    expect(view.send).toBeDisabled();
    expect(view.check).not.toBeDisabled();
    expect(view.status).toHaveTextContent("may still commit");
    view.fetcher.mockResolvedValueOnce(result("pending"));
    view.check.click();
    await settle();
    const options = view.fetcher.mock.calls[1][1];
    expect(options.method).toBe("GET");
    expect(options).not.toHaveProperty("body");
    expect(options.headers).toEqual({ "X-Maru-File-Intent": "original-proof" });
    expect(view.send).toBeDisabled();
    expect(unload()).toBe(true);
  });
  it.each([0, 10 * 1024 * 1024 + 1])("refuses invalid byte size %s before sending", async (size) => {
    const view = boot();
    choose(view.input!, size);
    view.send!.click();
    await settle();
    expect(view.fetcher).not.toHaveBeenCalled();
    expect(view.status).toHaveTextContent("No upload was sent");
    expect(view.input).not.toBeDisabled();
  });
  it.each(["unconfirmed", "pending"])("never unlocks attempted bytes after %s", async (state) => {
    const view = boot();
    choose(view.input!);
    view.fetcher.mockResolvedValue(result(state, false));
    view.send!.click();
    await settle();
    expect(view.send).toBeDisabled();
    expect(view.input).toBeDisabled();
    expect(unload()).toBe(true);
  });
  it("reload recovery never exposes a new upload control or sends automatically", async () => {
    const view = boot(true);
    expect(view.input).toBeNull();
    expect(view.send).toBeNull();
    expect(view.fetcher).not.toHaveBeenCalled();
    view.fetcher.mockResolvedValue(result());
    view.check.click();
    await settle();
    expect(view.fetcher.mock.calls[0][1].method).toBe("GET");
  });
  it("keeps pending state on an invalid response and never inserts HTML", async () => {
    const view = boot();
    choose(view.input!);
    view.fetcher.mockResolvedValue({ ok: true, json: async () => ({ state: "unconfirmed", message: '<script>unsafe()</script>' }) });
    view.send!.click();
    await settle();
    expect(view.status.querySelector("script")).toBeNull();
    expect(view.status).toHaveTextContent("<script>");
    expect(unload()).toBe(true);
  });
  it("does not enable uploading when original history cannot be retained", () => {
    vi.spyOn(window.history, "replaceState").mockImplementation(() => { throw new Error("history blocked"); });
    const view = boot();
    expect(view.send).toBeDisabled();
    expect(view.input).toBeDisabled();
    expect(view.status).toHaveTextContent("Uploading is unavailable");
    expect(view.fetcher).not.toHaveBeenCalled();
  });
});
