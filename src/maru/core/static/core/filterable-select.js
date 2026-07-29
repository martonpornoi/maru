(() => {
  "use strict";

  function searchable(select) {
    if (select.dataset.filterReady === "true") return;
    select.dataset.filterReady = "true";

    const input = document.createElement("input");
    input.type = "search";
    input.className = "vTextField";
    input.placeholder =
      select.dataset.filterPlaceholder || "Start typing to filter options";
    input.setAttribute("aria-label", input.placeholder);
    input.autocomplete = "off";
    input.style.marginBottom = "0.5rem";
    input.style.display = "block";
    input.style.width = "min(42rem, 100%)";
    select.parentNode.insertBefore(input, select);

    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase();
      for (const option of select.options) {
        const visible =
          !query ||
          option.textContent.toLocaleLowerCase().includes(query) ||
          option.value.toLocaleLowerCase().includes(query);
        option.hidden = !visible && !option.selected;
      }
      for (const group of select.querySelectorAll("optgroup")) {
        group.hidden = !Array.from(group.children).some(
          (option) => !option.hidden,
        );
      }
    });
  }

  function initialize(root = document) {
    root
      .querySelectorAll("select[data-filterable-select]")
      .forEach(searchable);
  }

  document.addEventListener("DOMContentLoaded", () => initialize());
  document.addEventListener("formset:added", (event) => initialize(event.target));
})();
