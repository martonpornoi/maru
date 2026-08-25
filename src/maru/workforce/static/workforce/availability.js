(() => {
  "use strict";

  const form = document.querySelector("[data-availability-form]");
  if (!(form instanceof HTMLFormElement)) {
    return;
  }

  const rows = form.querySelector("[data-availability-rows]");
  const template = form.querySelector("[data-availability-empty-form]");
  const total = form.querySelector("#id_windows-TOTAL_FORMS");
  const addButton = form.querySelector("[data-add-period]");
  if (
    !(rows instanceof HTMLElement) ||
    !(template instanceof HTMLTemplateElement) ||
    !(total instanceof HTMLInputElement) ||
    !(addButton instanceof HTMLButtonElement)
  ) {
    return;
  }

  const refreshNumbers = () => {
    rows.querySelectorAll("[data-period-number]").forEach((label, index) => {
      label.textContent = String(index + 1);
    });
  };

  const toggleRemoval = (button) => {
    const row = button.closest("[data-availability-row]");
    if (!(row instanceof HTMLFieldSetElement)) {
      return;
    }
    const checkbox = row.querySelector('input[name$="-DELETE"]');
    if (!(checkbox instanceof HTMLInputElement)) {
      return;
    }
    checkbox.checked = !checkbox.checked;
    row.classList.toggle("workforce-availability-period--removed", checkbox.checked);
    row.querySelectorAll("input, select").forEach((control) => {
      if (control !== checkbox) {
        control.disabled = checkbox.checked;
      }
    });
    button.textContent = checkbox.checked ? "Undo removal" : "Remove this period";
  };

  form.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const removeButton = target.closest("[data-remove-period]");
    if (removeButton instanceof HTMLButtonElement) {
      toggleRemoval(removeButton);
    }
  });

  addButton.addEventListener("click", () => {
    const nextIndex = Number.parseInt(total.value, 10);
    const maximum = Number.parseInt(
      form.querySelector("#id_windows-MAX_NUM_FORMS")?.value || "64",
      10,
    );
    if (!Number.isSafeInteger(nextIndex) || nextIndex >= maximum) {
      addButton.disabled = true;
      return;
    }
    const html = template.innerHTML.replaceAll("__prefix__", String(nextIndex));
    rows.insertAdjacentHTML("beforeend", html);
    total.value = String(nextIndex + 1);
    refreshNumbers();
    const added = rows.lastElementChild;
    added?.querySelector("input, select")?.focus();
    if (nextIndex + 1 >= maximum) {
      addButton.disabled = true;
    }
  });

  refreshNumbers();
})();
