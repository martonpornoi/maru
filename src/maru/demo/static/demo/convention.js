"use strict";

const status = document.getElementById("copy-status");
document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const input = document.getElementById(button.dataset.copy);
    try {
      // Read the actual value even when the password field is masked.
      await navigator.clipboard.writeText(input.value);
      status.textContent = "Copied. Paste it into the normal sign-in form.";
    } catch {
      if (input.type === "password") {
        document.querySelector(`[data-reveal="${input.id}"]`).focus();
        status.textContent = 'Clipboard access was unavailable. Choose "Show this practice password", then select the revealed password and copy it using your keyboard.';
      } else {
        input.focus();
        input.select();
        status.textContent = "Clipboard access was unavailable. The field is selected; copy it using your keyboard.";
      }
    }
  });
});
document.querySelectorAll("[data-reveal]").forEach((checkbox) => {
  checkbox.addEventListener("change", () => {
    document.getElementById(checkbox.dataset.reveal).type = checkbox.checked ? "text" : "password";
  });
});
document.querySelector("[data-clear-clipboard]").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText("");
    status.textContent = "Clipboard cleared.";
  } catch {
    status.textContent = "Clipboard access was unavailable. Copy something else to replace the practice data.";
  }
});
