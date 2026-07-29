function normalizedValue(input) {
  const form = input.form;
  if (!form) return "";
  const source = form.elements.namedItem(`question__${input.dataset.conditionKey}`);
  if (!source) return "";
  if (source instanceof RadioNodeList) return source.value;
  if (source instanceof HTMLInputElement && source.type === "checkbox") {
    return source.checked ? "true" : "false";
  }
  return source.value;
}

function updateConditions() {
  const conditionalInputs = document.querySelectorAll("[data-condition-key]:not([data-condition-key=''])");
  const wrappers = new Set();
  conditionalInputs.forEach((input) => {
    const wrapper = input.closest(".form-field");
    if (!wrapper || wrappers.has(wrapper)) return;
    wrappers.add(wrapper);
    const visible = normalizedValue(input) === input.dataset.conditionValue;
    wrapper.hidden = !visible;
    wrapper.querySelectorAll("input, select, textarea").forEach((control) => {
      control.disabled = !visible;
    });
  });
}

function updateOtherPronouns() {
  const select = document.querySelector("[name='pronoun_code']");
  const wrapper = document.querySelector("[data-other-pronouns]");
  if (!select || !wrapper) return;
  const visible = select.value === "other";
  wrapper.hidden = !visible;
  wrapper.querySelectorAll("input").forEach((input) => {
    input.disabled = !visible;
  });
}

function updateFursuitEditor() {
  const toggle = document.querySelector("[data-fursuit-toggle]");
  const editor = document.querySelector("[data-fursuit-editor]");
  if (!toggle || !editor) return;
  editor.hidden = !toggle.checked;
  editor
    .querySelectorAll("[data-fursuit-row] input, [data-fursuit-row] select, [data-fursuit-row] textarea, [data-add-fursuit]")
    .forEach((control) => {
      control.disabled = !toggle.checked;
    });
}

function updateDirectoryCountry() {
  const toggle = document.querySelector("[data-directory-toggle]");
  const wrapper = document.querySelector("[data-directory-country]");
  if (!toggle || !wrapper) return;
  wrapper.hidden = !toggle.checked;
  wrapper.querySelectorAll("input, select").forEach((control) => {
    control.disabled = !toggle.checked;
  });
}

function renumberFursuits() {
  document.querySelectorAll("[data-fursuit-row]").forEach((row, index) => {
    const number = row.querySelector("[data-fursuit-number]");
    if (number) number.textContent = String(index + 1);
  });
}

function addFursuit() {
  const template = document.querySelector("[data-empty-fursuit]");
  const list = document.querySelector("[data-fursuit-list]");
  const total = document.querySelector("[name='fursuits-TOTAL_FORMS']");
  if (!template || !list || !total) return;
  const index = Number.parseInt(total.value, 10);
  if (!Number.isFinite(index) || index >= 10) return;
  const wrapper = document.createElement("div");
  wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(index));
  while (wrapper.firstElementChild) list.append(wrapper.firstElementChild);
  total.value = String(index + 1);
  renumberFursuits();
}

function updateLanguageSelection() {
  const select = document.querySelector("[data-language-select]");
  const count = document.querySelector("[data-language-count]");
  if (!select) return;
  const selected = [...select.options].filter((option) => option.selected).length;
  if (count) count.textContent = `${selected} of 5 selected`;
  [...select.options].forEach((option) => {
    option.disabled = selected >= 5 && !option.selected;
  });
}

function filterLanguages(event) {
  const select = document.querySelector("[data-language-select]");
  if (!select) return;
  const query = event.target.value.trim().toLocaleLowerCase();
  [...select.options].forEach((option) => {
    option.hidden = Boolean(query) && !option.text.toLocaleLowerCase().includes(query);
  });
}

function updateCharacterCount(event) {
  const input = event.target.closest("[data-character-count]");
  if (!input) return;
  const field = input.closest(".form-field");
  if (!field) return;
  let counter = field.querySelector("[data-live-character-count]");
  if (!counter) {
    counter = document.createElement("small");
    counter.dataset.liveCharacterCount = "";
    field.append(counter);
  }
  counter.textContent = `${input.value.length} of ${input.maxLength} characters`;
}

function initializeProfileForm() {
  updateConditions();
  updateOtherPronouns();
  updateFursuitEditor();
  updateDirectoryCountry();
  updateLanguageSelection();
  renumberFursuits();
  document.querySelectorAll("[data-character-count]").forEach((input) => {
    updateCharacterCount({ target: input });
  });
}

document.addEventListener("change", (event) => {
  updateConditions();
  updateOtherPronouns();
  updateFursuitEditor();
  updateDirectoryCountry();
  if (event.target.matches("[data-language-select]")) updateLanguageSelection();
});
document.addEventListener("input", (event) => {
  if (event.target.matches("[data-language-filter]")) filterLanguages(event);
  if (event.target.matches("[data-character-count]")) updateCharacterCount(event);
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-add-fursuit]")) addFursuit();
});
document.addEventListener("DOMContentLoaded", initializeProfileForm);
