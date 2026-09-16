/* One explicit original upload intent; never resend or rebase it automatically. */
(() => {
  const root = document.querySelector('[data-file-upload]');
  if (!root) return;
  const input = root.querySelector('input[type="file"]');
  const send = root.querySelector('[data-file-send]');
  const check = root.querySelector('[data-file-check]');
  const status = root.querySelector('[role="status"]');
  const dirty = root.querySelector('[data-file-dirty]');
  const token = root.dataset.fileIntent;
  const endpoint = new URL(root.dataset.fileEndpoint, window.location.href);
  if (endpoint.origin !== window.location.origin || !token) return;
  let attempted = root.dataset.fileRecovery === 'true';
  let pending = false;
  let busy = false;
  let saved = false;
  // Keep the original proof in this page's history, never file bytes or filenames.
  try {
    const retained = new URL(window.location.href);
    retained.searchParams.set('intent', token);
    window.history.replaceState(null, '', retained);
  } catch {
    status.textContent = 'The original intent could not be retained in page history. Uploading is unavailable; return to the proposal.';
    return;
  }
  const refresh = () => {
    if (input) input.disabled = attempted || busy || saved;
    if (send) send.disabled = attempted || busy || saved || !input?.files?.length;
    check.disabled = busy;
    dirty.hidden = !pending;
  };
  input?.addEventListener('change', () => {
    pending = Boolean(input.files?.length);
    status.textContent = pending ? 'PDF selected locally, not uploaded.' : 'No file selected or uploaded.';
    refresh();
  });
  const act = async (upload) => {
    if (busy || (upload && (attempted || saved))) return;
    const file = input?.files?.[0];
    if (upload && (!file || input.files.length !== 1 || file.size < 1 || file.size > 10 * 1024 * 1024)) {
      status.textContent = 'Choose one non-empty PDF of at most 10 MiB. No upload was sent.';
      return;
    }
    if (upload) { attempted = true; pending = true; }
    busy = true;
    status.textContent = upload ? 'Uploading and scanning. Keep this page to recover the original outcome.' : 'Checking the original upload result without sending file bytes.';
    refresh();
    // Keep keyboard focus at the feedback when the invoking control is disabled.
    status.focus();
    try {
      const headers = { 'X-Maru-File-Intent': token };
      if (upload) {
        headers['Content-Type'] = 'application/pdf';
        headers['X-CSRFToken'] = root.querySelector('[name="csrfmiddlewaretoken"]').value;
      }
      const response = await fetch(endpoint, {
        method: upload ? 'PUT' : 'GET', headers, credentials: 'same-origin',
        cache: 'no-store', redirect: 'error', ...(upload ? { body: file } : {}),
      });
      const result = await response.json();
      if (!['saved', 'pending', 'unconfirmed'].includes(result.state) || typeof result.message !== 'string' || result.message.length > 2000) throw new Error('Invalid result');
      status.textContent = result.message;
      if (response.ok && result.state === 'saved') {
        saved = true; pending = false;
        if (input) input.value = '';
      }
    } catch {
      status.textContent = 'The outcome is unconfirmed. Keep the original intent and check the previous upload result. Do not resend automatically; an earlier request may still commit.';
    } finally {
      busy = false;
      refresh();
    }
  };
  send?.addEventListener('click', () => { void act(true); });
  check.addEventListener('click', () => { void act(false); });
  window.addEventListener('beforeunload', (event) => {
    if (!root.isConnected || !pending) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('pageshow', refresh);
  refresh();
})();
