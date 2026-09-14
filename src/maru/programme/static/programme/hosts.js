/** Add explicit bounded availability rows; submission remains the owner command. */
for (const button of document.querySelectorAll("[data-host-add-period]")) {
  const form = button.closest("form");
  const container = form?.querySelector("[data-host-periods]");
  const template = form?.querySelector("template[data-host-empty-period]");
  const count = form?.querySelector('[name="periods-TOTAL_FORMS"]');
  const status = form?.querySelector("[data-host-period-status]");
  const limit = Number(button.dataset.hostLimit);
  if (!form || !container || !template || !count || !status || limit !== 128) continue;
  const refresh = () => {
    button.disabled = !/^\d+$/.test(count.value) || Number(count.value) >= limit;
    if (button.disabled) status.textContent = "The 128-period limit has been reached.";
  };
  refresh();
  button.addEventListener("click", () => {
    refresh();
    if (button.disabled) return;
    const index = Number(count.value);
    const fragment = document.createElement("template");
    fragment.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index));
    const row = fragment.content.firstElementChild;
    if (!row) return;
    const legend = row.querySelector("legend");
    if (legend) legend.textContent = `Availability period ${index + 1}`;
    container.append(row);
    count.value = String(index + 1);
    row.querySelector("input:not([type=hidden]), select")?.focus();
    status.textContent = "Availability period added. Nothing is saved until you submit.";
    form.dispatchEvent(new Event("change", { bubbles: true }));
    refresh();
  });
}
