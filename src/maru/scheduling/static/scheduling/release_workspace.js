(() => {
  "use strict";
  const states = [];
  document.querySelectorAll("[data-release-command]").forEach((form) => {
    if (!(form instanceof window.HTMLFormElement) || form.dataset.releaseReady) return;
    form.dataset.releaseReady = "true";
    const value = () => JSON.stringify(Array.from(new window.FormData(form)).filter(
      ([name]) => name !== "csrfmiddlewaretoken",
    ));
    const initial = value();
    const pending = form.dataset.releasePending === "true";
    const state = { form, submitting: false, dirty: () => pending || value() !== initial };
    const refresh = () => {
      state.submitting = false;
      const status = form.querySelector("[data-release-dirty]");
      if (status instanceof window.HTMLElement) status.hidden = !state.dirty();
    };
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      // Submitting one form must not silently discard another form's rationale.
      if (states.some((other) => other !== state && other.form.isConnected && other.dirty())
          && !window.confirm("Another release action has unsaved input. Discard that input and submit this action?")) {
        event.preventDefault();
        return;
      }
      if (!event.defaultPrevented) states.forEach((entry) => { entry.submitting = true; });
    });
    window.addEventListener("pageshow", refresh);
    states.push(state);
    refresh();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!states.some((state) => state.form.isConnected && !state.submitting && state.dirty())) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
