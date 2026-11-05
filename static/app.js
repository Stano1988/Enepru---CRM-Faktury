const toggle = document.querySelector('.menu-toggle');
if (toggle) {
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    document.querySelector('aside').classList.toggle('menu-open', open);
  });
}

// Choosing an existing client fills the invoice; server checks the same access again.
const clientSelect = document.querySelector('[data-invoice-client]');
if (clientSelect) {
  let pendingClient = null;
  clientSelect.addEventListener('change', async () => {
    const id = clientSelect.value;
    if (!id) return;
    pendingClient = id;
    try {
      const response = await fetch(`/clients/${encodeURIComponent(id)}/invoice-defaults/`, {credentials: 'same-origin'});
      if (!response.ok) return;
      const data = await response.json();
      if (pendingClient !== id) return;
      for (const key of ['name', 'address', 'company_id', 'tax_id', 'email']) {
        const field = document.getElementById(`id_recipient_${key}`);
        if (field) field.value = data[key] || '';
      }
      const issue = document.getElementById('id_issue_date');
      const due = document.getElementById('id_due_date');
      if (issue?.value && due) {
        const date = new Date(`${issue.value}T12:00:00Z`);
        date.setUTCDate(date.getUTCDate() + data.payment_days);
        due.value = date.toISOString().slice(0,10);
      }
      const notes = document.getElementById('invoice-client-notes');
      if (notes) { notes.textContent = data.notes; notes.hidden = !data.notes; }
    } catch (_) { /* Keep manual entry available if the connection is interrupted. */ }
  });
}
