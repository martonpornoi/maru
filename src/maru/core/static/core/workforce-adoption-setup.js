"use strict";

(() => {
  const form = document.querySelector("[data-workforce-foundation-form]");
  if (!(form instanceof HTMLFormElement)) return;

  const choices = form.querySelectorAll('input[name="mode"]');
  const groups = form.querySelectorAll("[data-foundation-field]");
  const status = form.querySelector("[data-foundation-mode-status]");
  const messages = {
    new_foundation:
      "Enter the new organization and convention names. Reuse fields are hidden.",
    existing_organization:
      "Choose the existing organization and enter the new convention name.",
    existing_series:
      "Choose the existing convention series. New foundation names are hidden.",
  };

  function selectedMode() {
    const selected = form.querySelector('input[name="mode"]:checked');
    return selected instanceof HTMLInputElement ? selected.value : "";
  }

  function updateDisclosure() {
    const mode = selectedMode();
    for (const group of groups) {
      if (!(group instanceof HTMLElement)) continue;
      const modes = (group.dataset.foundationField ?? "").split(" ");
      const visible = modes.includes(mode);
      group.hidden = !visible;
      for (const control of group.querySelectorAll("input, select, textarea")) {
        if (
          control instanceof HTMLInputElement ||
          control instanceof HTMLSelectElement ||
          control instanceof HTMLTextAreaElement
        ) {
          control.disabled = !visible;
        }
      }
    }
    if (status instanceof HTMLElement) {
      status.textContent = messages[mode] ?? "Choose one foundation option.";
    }
  }

  for (const choice of choices) {
    choice.addEventListener("change", updateDisclosure);
  }
  updateDisclosure();
})();
