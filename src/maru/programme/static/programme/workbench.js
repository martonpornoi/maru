(() => {
  "use strict";
  const form = document.querySelector("[data-programme-command]");
  if (!(form instanceof window.HTMLFormElement) || form.dataset.programmeReady) return;
  form.dataset.programmeReady = "true";
  const value = () => JSON.stringify(Array.from(new window.FormData(form)).filter(
    ([name]) => name !== "csrfmiddlewaretoken",
  ));
  const initial = value();
  const pending = form.dataset.programmePending === "true";
  let submitting = false;
  const dirty = () => pending || value() !== initial;
  const refresh = () => {
    submitting = false;
    const status = document.querySelector("[data-programme-dirty]");
    if (status instanceof window.HTMLElement) status.hidden = !dirty();
  };
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  form.addEventListener("submit", (event) => {
    if (!event.defaultPrevented) submitting = true;
  });
  window.addEventListener("beforeunload", (event) => {
    if (!form.isConnected || submitting || !dirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("pageshow", refresh);
  refresh();
})();
