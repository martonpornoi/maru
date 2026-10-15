import { afterEach, describe, expect, it, vi } from "vitest";

const { readFileSync } = await vi.importActual<{
  readFileSync(path: string, encoding: "utf8"): string;
}>("node:fs");
const { cwd } = await vi.importActual<{ cwd(): string }>("node:process");
const source = readFileSync(
  `${cwd()}/../../src/maru/demo/static/demo/convention.js`,
  "utf8"
);

function boot(writeText?: (value: string) => Promise<void>) {
  vi.stubGlobal("navigator", { clipboard: writeText ? { writeText } : undefined });
  document.body.innerHTML = `
    <p id="copy-status" role="status"></p>
    <input id="practice-email" value="author@example.invalid" readonly>
    <button data-copy="practice-email">Copy email</button>
    <input id="practice-password" type="password" value="synthetic-example" readonly>
    <button data-copy="practice-password">Copy password</button>
    <label><input type="checkbox" data-reveal="practice-password">Show this practice password</label>
    <button data-clear-clipboard>Clear copied practice data</button>`;
  new Function(source)();
  return {
    password: document.getElementById("practice-password") as HTMLInputElement,
    email: document.getElementById("practice-email") as HTMLInputElement,
    reveal: document.querySelector<HTMLInputElement>("[data-reveal]")!,
    status: document.getElementById("copy-status")!
  };
}

async function click(selector: string) {
  document.querySelector<HTMLButtonElement>(selector)!.click();
  await Promise.resolve();
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("disposable practice clipboard", () => {
  it("copies the actual password while keeping it masked", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const page = boot(write);
    await click('[data-copy="practice-password"]');
    expect(write).toHaveBeenCalledWith("synthetic-example");
    expect(page.password.type).toBe("password");
    expect(page.reveal.checked).toBe(false);
    expect(page.status.textContent).toMatch(/^Copied\./);
  });

  it.each(["denied", "unavailable"])("keeps a password masked when clipboard access is %s", async (failure) => {
    const write = vi.fn().mockRejectedValue(new Error("Permission denied"));
    const page = boot(failure === "denied" ? write : undefined);
    const select = vi.spyOn(page.password, "select");
    await click('[data-copy="practice-password"]');
    expect(page.password.type).toBe("password");
    expect(page.reveal.checked).toBe(false);
    expect(select).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(page.reveal);
    expect(page.status.textContent).toContain('Choose "Show this practice password"');
    expect(page.status.textContent).toContain("select the revealed password");
    expect(page.status.textContent).not.toContain("synthetic-example");
    expect(page.status.textContent).not.toMatch(/^Copied\./);
  });

  it.each(["email", "password"])("selects the visible %s for manual copying after denial", async (kind) => {
    const page = boot(vi.fn().mockRejectedValue(new Error("Permission denied")));
    if (kind === "password") {
      page.reveal.checked = true;
      page.reveal.dispatchEvent(new Event("change"));
    }
    const input = kind === "email" ? page.email : page.password;
    await click(`[data-copy="practice-${kind}"]`);
    expect(input.type).toBe("text");
    expect(document.activeElement).toBe(input);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(input.value.length);
    expect(page.status.textContent).toContain("The field is selected");
    expect(page.status.textContent).not.toMatch(/^Copied\./);
  });

  it("requires another deliberate reveal after hiding the password again", async () => {
    const page = boot(vi.fn().mockRejectedValue(new Error("Permission denied")));
    page.reveal.checked = true;
    page.reveal.dispatchEvent(new Event("change"));
    page.reveal.checked = false;
    page.reveal.dispatchEvent(new Event("change"));
    await click('[data-copy="practice-password"]');
    expect(page.password.type).toBe("password");
    expect(document.activeElement).toBe(page.reveal);
    expect(page.status.textContent).toContain('Choose "Show this practice password"');
  });

  it("clears copied practice data only after the clipboard write succeeds", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const page = boot(write);
    await click("[data-clear-clipboard]");
    expect(write).toHaveBeenCalledWith("");
    expect(page.status.textContent).toBe("Clipboard cleared.");
  });

  it("gives honest recovery guidance when clearing is denied", async () => {
    const page = boot(vi.fn().mockRejectedValue(new Error("Permission denied")));
    await click("[data-clear-clipboard]");
    expect(page.status.textContent).toContain("Copy something else");
    expect(page.status.textContent).not.toBe("Clipboard cleared.");
  });
});
