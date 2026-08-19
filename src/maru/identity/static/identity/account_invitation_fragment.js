(() => {
  "use strict";

  const field = document.querySelector("[data-invitation-code]");
  if (!(field instanceof HTMLInputElement)) {
    return;
  }
  const match = /^#code=([A-Za-z0-9_-]{43})$/.exec(window.location.hash);
  if (match === null) {
    return;
  }
  field.value = match[1];
  window.history.replaceState(null, "", window.location.pathname);
})();
