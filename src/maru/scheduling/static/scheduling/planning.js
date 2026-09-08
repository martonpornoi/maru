(() => {
  "use strict";

  const root = document.querySelector("[data-planning-workspace]");
  if (!(root instanceof window.HTMLElement) || root.dataset.planningReady) return;
  root.dataset.planningReady = "true";
  const events = new window.AbortController();
  const on = (target, type, handler) => {
    target.addEventListener(type, handler, { signal: events.signal });
  };
  const status = root.querySelector("[data-planning-status]");
  const announce = (message) => {
    if (!(status instanceof window.HTMLElement)) return;
    status.textContent = message;
    status.hidden = false;
  };
  const command = root.querySelector("[data-planning-command]");
  const isCommand = command instanceof window.HTMLFormElement;
  const initial = isCommand ? formValue(command) : "";
  const wasPending = isCommand && command.dataset.planningPending === "true";
  let leaving = false;
  const dirty = () => isCommand && (wasPending || formValue(command) !== initial);
  const dirtyNotice = root.querySelector("[data-planning-dirty]");
  const refreshDirty = () => {
    leaving = false;
    if (dirtyNotice instanceof window.HTMLElement) dirtyNotice.hidden = !dirty();
  };
  const confirmLeave = () => !dirty() || window.confirm(
    "Discard unsaved timetable input and change the view? " +
    "Preview has not saved it. Cancel to keep this exact pending form.",
  );

  function formValue(form) {
    return JSON.stringify(Array.from(new window.FormData(form)).filter(
      ([name]) => name !== "csrfmiddlewaretoken",
    ));
  }

  if (isCommand) {
    on(command, "input", refreshDirty);
    on(command, "change", refreshDirty);
  }
  on(document, "submit", (event) => {
    if (!root.isConnected || event.defaultPrevented) return;
    if (event.target !== command && !confirmLeave()) {
      event.preventDefault();
      return;
    }
    // Native validation precedes submit. Keep all values/key intact even here.
    // New input and pageshow restore the guard if navigation did not complete.
    leaving = true;
  });
  on(document, "click", (event) => {
    if (!root.isConnected || event.defaultPrevented || event.button !== 0 ||
        event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
        !(event.target instanceof window.Element)) return;
    const link = event.target.closest("a[href]");
    if (!(link instanceof window.HTMLAnchorElement) || link.target === "_blank" ||
        link.hasAttribute("download")) return;
    const url = new URL(link.href, window.location.href);
    if (url.hash && url.origin === window.location.origin &&
        url.pathname === window.location.pathname &&
        url.search === window.location.search) return;
    if (!confirmLeave()) event.preventDefault();
    else leaving = true;
  });
  on(window, "beforeunload", (event) => {
    if (!root.isConnected || leaving || !dirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  on(window, "pageshow", refreshDirty);
  refreshDirty();

  // Dragging is just the native, CSRF-protected selection POST. It cannot
  // transport command fields, reuse another target's versions, or save.
  const destination = root.querySelector("[data-planning-destination]");
  if (destination instanceof window.HTMLFormElement) {
    const occurrence = destination.elements.namedItem("ui_occurrence_id");
    const day = destination.elements.namedItem("ui_day_id");
    const room = destination.elements.namedItem("ui_space_id");
    if ([occurrence, day, room].every((field) => field instanceof window.HTMLSelectElement)) {
      initializeDrag(destination, occurrence, day, room);
    }
  }

  function initializeDrag(form, occurrence, day, room) {
    const offered = (field, value) => Boolean(value) && Array.from(field.options).some(
      (option) => option.value === value && !option.disabled,
    );
    const targets = Array.from(root.querySelectorAll(
      "[data-planning-lane], [data-planning-drop-selected]",
    ));
    let dragged = null;
    const clearDrag = () => {
      dragged = null;
      targets.forEach((target) => target.classList.remove("planning-drop-ready"));
      root.querySelectorAll(".planning-drag-active").forEach(
        (card) => card.classList.remove("planning-drag-active"),
      );
    };
    root.querySelectorAll("[data-planning-entry], [data-planning-placement]").forEach((card) => {
      if (!offered(occurrence, card.dataset.occurrence)) return;
      card.draggable = true;
      card.dataset.planningDragReady = "true";
      on(card, "dragstart", (event) => {
        if (!event.dataTransfer) return;
        dragged = card.dataset.occurrence;
        // Private identifiers and labels never enter external drag payloads.
        event.dataTransfer.setData("text/plain", "Maru placement selection");
        event.dataTransfer.effectAllowed = "move";
        card.classList.add("planning-drag-active");
        targets.forEach((target) => target.classList.add("planning-drop-ready"));
        announce("Drop into a day/room lane or the chosen destination to open a form. Nothing will be saved.");
      });
      on(card, "dragend", clearDrag);
    });
    targets.forEach((target) => {
      if (target.hasAttribute("data-planning-drop-selected")) target.hidden = false;
      on(target, "dragover", (event) => {
        if (!dragged) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      });
      on(target, "drop", (event) => {
        if (!dragged) return; // Never trust an external drag payload.
        event.preventDefault();
        const selected = dragged;
        const selectedDay = target.dataset.day || day.value;
        const selectedRoom = target.dataset.space || room.value;
        clearDrag();
        if (!offered(occurrence, selected) || !offered(day, selectedDay) ||
            !offered(room, selectedRoom)) {
          announce("Choose an active service day and room in the destination controls first. No input was changed.");
          return;
        }
        occurrence.value = selected;
        day.value = selectedDay;
        room.value = selectedRoom;
        form.requestSubmit();
      });
    });
    on(document, "keydown", (event) => {
      if (event.key === "Escape" && dragged) {
        clearDrag();
        announce("Placement drag cancelled. No input was changed.");
      }
    });
  }

  const timeControls = root.querySelector("[data-planning-time-controls]");
  if (isCommand && timeControls instanceof window.HTMLElement) {
    initializeTimes(timeControls, command);
  }

  // Offset-free, impossible or sub-minute input remains untouched. Only the
  // server interprets offset-free local minutes and rejects DST gaps/folds.
  function exactMinute(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::00)?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
    if (!match || Number(match[1]) < 1) return null;
    const stamp = Date.parse(value);
    if (!Number.isFinite(stamp)) return null;
    const offset = match[6] === "Z" ? 0 :
      (match[6][0] === "-" ? -1 : 1) *
      (Number(match[6].slice(1, 3)) * 60 + Number(match[6].slice(4, 6)));
    const wall = new Date(stamp + offset * 60000).toISOString().slice(0, 16);
    return wall === value.slice(0, 16) ? stamp : null;
  }

  function initializeTimes(panel, form) {
    const start = exactMinute(panel.dataset.start || "");
    const end = exactMinute(panel.dataset.end || "");
    const step = Number(panel.dataset.step);
    if (start === null || end === null || end <= start ||
        !panel.dataset.zone || !Number.isInteger(step) || step < 1 ||
        step > 60 || 60 % step !== 0) return;
    let formatter;
    try {
      formatter = new Intl.DateTimeFormat("en-GB-u-nu-latn", {
        timeZone: panel.dataset.zone,
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
      });
    } catch {
      announce("Time shortcuts are unavailable. Use the exact time fields; no values were changed.");
      return;
    }
    const maximum = Math.floor((end - start) / (step * 60000)) * step;
    const formatMinute = (stamp) => {
      const parts = Object.fromEntries(formatter.formatToParts(stamp).map(
        (part) => [part.type, part.value],
      ));
      const wall = `${parts.year.padStart(4, "0")}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
      const wallStamp = exactMinute(wall + "Z");
      if (parts.second !== "00" || wallStamp === null) return null;
      const offset = (wallStamp - stamp) / 60000;
      if (!Number.isInteger(offset) || Math.abs(offset) >= 24 * 60) return null;
      const absolute = Math.abs(offset);
      return wall + (offset < 0 ? "-" : "+") +
        String(Math.floor(absolute / 60)).padStart(2, "0") + ":" +
        String(absolute % 60).padStart(2, "0");
    };
    const names = new Set([
      "setup_starts_at", "effective_starts_at", "effective_ends_at", "teardown_ends_at",
    ]);
    panel.querySelectorAll("[data-planning-time]").forEach((range) => {
      if (!(range instanceof window.HTMLInputElement) || !names.has(range.dataset.planningTime)) return;
      const field = form.elements.namedItem(range.dataset.planningTime);
      const output = panel.querySelector(`output[for="${range.id}"]`);
      if (!(field instanceof window.HTMLInputElement) ||
          !(output instanceof window.HTMLOutputElement)) return;
      range.min = "0";
      range.max = String(maximum);
      range.step = String(step);
      const synchronize = () => {
        const stamp = exactMinute(field.value);
        const onGrid = stamp !== null && stamp >= start && stamp <= end &&
          (stamp - start) % (step * 60000) === 0;
        range.value = onGrid ? String((stamp - start) / 60000) : "0";
        const text = onGrid ? field.value : field.value
          ? "Entered value retained; use the exact field or deliberately choose a new grid minute."
          : "Not set. Choose a grid minute or enter an exact time above.";
        output.value = text;
        range.setAttribute("aria-valuetext", text);
      };
      on(field, "input", synchronize);
      on(field, "change", synchronize);
      on(range, "input", () => {
        const minutes = Number(range.value);
        if (!Number.isInteger(minutes) || minutes < 0 || minutes > maximum || minutes % step) return;
        const formatted = formatMinute(start + minutes * 60000);
        if (formatted === null) {
          announce("This minute cannot be represented by the shortcut. Use the exact field; no input was changed.");
          return;
        }
        field.value = formatted;
        field.dispatchEvent(new window.Event("input", { bubbles: true }));
        announce("Room time filled, not saved. Required host intervals are unchanged. Review all times, then Preview or Save explicitly.");
      });
      synchronize();
    });
    panel.hidden = false;
  }

  const focusTarget = root.querySelector("[data-maru-focus-on-load]");
  if (focusTarget instanceof window.HTMLElement) focusTarget.focus();
  return () => events.abort();
})();
