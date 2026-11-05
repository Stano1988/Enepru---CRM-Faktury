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

const reply = document.querySelector('[data-offer-reply]');
if (reply) {
  const price = reply.querySelector('#id_price');
  const due = reply.querySelector('#id_due_date');
  const body = reply.querySelector('#id_body');
  const update = () => {
    const amount = Number(price.value.replace(',', '.'));
    if (price.value && Number.isFinite(amount)) body.value = body.value.replace(/Cena celkem je [^\n]+ Kč\./, `Cena celkem je ${amount.toFixed(2).replace('.', ',')} Kč.`);
    if (due.value) {
      const [y,m,d] = due.value.split('-');
      body.value = body.value.replace(/Předpokládaný termín vyhotovení je [^\n]+ po dodání/, `Předpokládaný termín vyhotovení je ${d}.${m}.${y} po dodání`);
    }
  };
  price.addEventListener('input',update);due.addEventListener('change',update);
}

// Highlight the current section and reveal its parent, without changing the menu order.
const menu = document.querySelector('#main-menu');
if (menu) {
  const current = location.pathname;
  const candidates = [...menu.querySelectorAll('a')].filter(a => {
    const url = new URL(a.href);
    if (url.pathname === '/') return current === '/' || current.startsWith('/jobs/');
    return current.startsWith(url.pathname) && (!url.search || url.search === location.search);
  }).sort((a,b) => b.getAttribute('href').length-a.getAttribute('href').length);
  if (candidates[0]) { candidates[0].setAttribute('aria-current','page'); const group=candidates[0].closest('details'); if(group) group.open=true; }
}
// Anchors into optional sections open them before scrolling.
document.querySelectorAll('.tabs a[href^="#"]').forEach(link => link.addEventListener('click',()=>{
  const section=document.getElementById(link.hash.slice(1));if(section?.tagName==='DETAILS') section.open=true;
}));
