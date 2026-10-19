/* Native Admin consent: the MCP client cannot create the local approval artifact. */
'use strict';
(() => {
  const en = new URLSearchParams(location.search).get('lang') === 'en';
  document.documentElement.lang = en ? 'en' : 'de';
  const text = en ? {
    heading: 'Approve System Message',
    explanation: 'This approval covers only the displayed message and action. It does not repair the cause.',
    'preview-label': 'Preview ID from the MCP call', load: 'Inspect preview',
    approve: 'Approve exactly this action', back: 'Back to setup',
    approved: 'Approved. Return to the MCP client and execute before the preview expires.',
    failure: 'Preview expired, approval mismatched, or service unavailable. No action was dispatched.',
    acknowledge: 'Acknowledge this message',
    historize: 'Historize using Okay; retain the message in history without setting confirmed_at.',
  } : {
    heading: 'Systemmeldung freigeben',
    explanation: 'Diese Freigabe gilt nur für die angezeigte Meldung und Aktion. Sie repariert keine Ursache.',
    'preview-label': 'Vorschau-ID aus dem MCP-Aufruf', load: 'Vorschau prüfen',
    approve: 'Genau diese Aktion freigeben', back: 'Zur Einrichtung',
    approved: 'Freigegeben. Im MCP-Client vor Ablauf der Vorschau ausführen.',
    failure: 'Vorschau abgelaufen, Freigabe unpassend oder Dienst nicht verfügbar. Keine Aktion wurde ausgeführt.',
    acknowledge: 'Diese Meldung bestätigen',
    historize: 'Mit Okay historisieren; im Verlauf behalten, ohne confirmed_at zu setzen.',
  };
  for (const id of ['heading', 'explanation', 'preview-label', 'load', 'approve', 'back']) {
    document.getElementById(id).textContent = text[id];
  }
  const input = document.getElementById('preview-id');
  const approve = document.getElementById('approve');
  const status = document.getElementById('status');
  let displayed = null;
  const reset = () => { displayed = null; approve.disabled = true; };
  input.addEventListener('input', reset);
  async function call(action, fields) {
    const response = await fetch('index.cgi', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      body: new URLSearchParams({action, ajax: '1', ...fields}),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error('Rejected');
    return result.data;
  }
  document.getElementById('preview-form').addEventListener('submit', async (event) => {
    event.preventDefault(); reset(); status.textContent = '';
    const id = input.value;
    try {
      const result = await call('inspect_message_confirmation', {preview_id: id});
      if (input.value !== id) return;
      displayed = result;
      document.getElementById('preview').textContent = [
        result.title, result.description, result.entry_uuid, text[result.effect],
      ].join('\n\n');
      approve.disabled = false;
    } catch (_) { status.textContent = text.failure; }
  });
  approve.addEventListener('click', async () => {
    const current = displayed; reset();
    if (!current) return;
    try {
      await call('approve_message_confirmation', {
        preview_id: current.preview_id, challenge: current.challenge,
      });
      status.textContent = text.approved;
    } catch (_) { status.textContent = text.failure; }
  });
})();
