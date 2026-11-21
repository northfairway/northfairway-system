/* Dedicated read-only Promo Codes management, shared by Treasurer and Administrator. */
document.addEventListener('DOMContentLoaded', () => {
  const container = document.querySelector('#promo-codes-tab [data-nfh-promo-table]');
  if (!container) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const display = value => value == null || value === '' ? '—' : esc(value);
  let records = [], page = 1, requestSequence = 0;
  const pageSize = 15;
  container.innerHTML = `
    <div class="record-filter-panel" style="display:flex;gap:12px;flex-wrap:wrap;padding:12px;align-items:flex-end">
      <label>Search promo code, homeowner, or ID<input class="form-input" type="search" data-promo-search placeholder="Find records" autocomplete="off"></label>
      <label>Status<select class="form-input" data-promo-status><option value="">All statuses</option><option>Active</option><option>Used</option><option>Expired</option><option>Inactive</option></select></label>
      <label>Coverage year<input class="form-input" type="number" min="2000" max="2200" data-promo-year placeholder="All years"></label>
      <button class="btn btn-primary" type="button" data-promo-refresh>Search</button>
      <button class="btn btn-secondary" type="button" data-promo-reset>Reset</button>
    </div>
    <div class="nfh-promo-summary" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:14px 0" aria-label="Promo code summary">
      <div class="content-card" style="padding:15px"><strong>Total</strong><p data-promo-count="Total">0</p></div>
      <div class="content-card" style="padding:15px"><strong>Active</strong><p data-promo-count="Active">0</p></div>
      <div class="content-card" style="padding:15px"><strong>Used</strong><p data-promo-count="Used">0</p></div>
      <div class="content-card" style="padding:15px"><strong>Expired</strong><p data-promo-count="Expired">0</p></div>
      <div class="content-card" style="padding:15px"><strong>Inactive</strong><p data-promo-count="Inactive">0</p></div>
    </div>
    <div class="table-responsive"><table class="data-table" data-no-record-filters="1"><thead><tr>
      <th>Promo Code</th><th>Homeowner Name</th><th>Coverage Year</th><th>Expiration Date</th><th>Status</th><th>Date Redeemed</th><th>Request ID</th><th>Action</th>
    </tr></thead><tbody data-promo-body><tr><td colspan="8">Select Promo Codes to load records.</td></tr></tbody></table></div>
    <div style="display:flex;gap:12px;align-items:center;justify-content:flex-end;margin-top:14px">
      <button class="btn btn-secondary" type="button" data-promo-prev>Previous</button>
      <span data-promo-page aria-live="polite"></span>
      <button class="btn btn-secondary" type="button" data-promo-next>Next</button>
    </div>
    <dialog data-promo-details aria-label="Promo code details" style="border:0;border-radius:12px;max-width:min(720px,95vw);width:100%;padding:24px;box-shadow:0 20px 80px #0004">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><h3>Promo Code Details</h3><button class="btn btn-secondary" type="button" data-promo-close>Close</button></div>
      <dl data-promo-detail-values style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:16px"></dl>
    </dialog>
    <p data-promo-error role="status" aria-live="polite"></p>`;
  const get = selector => container.querySelector(selector);
  const statusFilter = () => get('[data-promo-status]').value;
  const visible = () => statusFilter() ? records.filter(r => r.status === statusFilter()) : records;
  function render() {
    const totals = {Total: records.length, Active:0, Used:0, Expired:0, Inactive:0};
    records.forEach(r => { if (r.status in totals && r.status !== 'Total') totals[r.status]++; });
    Object.keys(totals).forEach(key => {get(`[data-promo-count="${key}"]`).textContent = totals[key].toLocaleString();});
    const filtered = visible(); const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.min(page, pages);
    const rows = filtered.slice((page-1)*pageSize, page*pageSize);
    get('[data-promo-body]').innerHTML = rows.length ? rows.map(r => `<tr>
      <td>${display(r.code)}</td><td>${display(r.homeowner_name)}</td><td>${display(r.coverage_year)}</td>
      <td>${display(r.expires_at)}</td><td>${display(r.status)}</td><td>${display(r.redeemed_at)}</td>
      <td>${display(r.redeemed_request_id)}</td><td><button type="button" class="btn btn-secondary" data-promo-detail="${esc(r.id)}">View Details</button></td>
    </tr>`).join('') : '<tr><td colspan="8">No matching promo codes.</td></tr>';
    get('[data-promo-page]').textContent = `${filtered.length.toLocaleString()} records · Page ${page} of ${pages}`;
    get('[data-promo-prev]').disabled = page <= 1;
    get('[data-promo-next]').disabled = page >= pages;
  }
  async function load() {
    const sequence = ++requestSequence;
    const search = get('[data-promo-search]').value.trim();
    const year = get('[data-promo-year]').value.trim();
    if (year && (!/^\d{4}$/.test(year) || +year < 2000 || +year > 2200)) {get('[data-promo-error]').textContent='Enter a valid coverage year (2000–2200).';return;}
    const params = new URLSearchParams({search, year});
    get('[data-promo-error]').textContent = 'Loading promo codes…';
    try {
      const response = await fetch('/api/promo-codes?' + params, {
        credentials:'same-origin', headers:{Accept:'application/json'}, redirect:'follow'
      });
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.toLowerCase().includes('application/json')) {
        throw new Error(response.redirected || response.status === 401 || response.status === 403
          ? 'Your session may have expired. Please sign in again.'
          : 'The server returned a page instead of promo-code data. Confirm the Batch 3 database migration and check the server error log.');
      }
      const payload = await response.json();
      if (!response.ok || payload.status === 'error') throw new Error(payload.error || payload.message || 'Unable to load promo codes.');
      if (!Array.isArray(payload.codes)) throw new Error('Invalid promo-code response from the server.');
      if (sequence !== requestSequence) return;
      records = payload.codes || []; page = 1; get('[data-promo-error]').textContent='';
      get('[data-promo-details]').close(); render();
    } catch (error) {if(sequence === requestSequence) get('[data-promo-error]').textContent = error.message || 'Unable to load promo codes.';}
  }
  get('[data-promo-refresh]').addEventListener('click', load);
  get('[data-promo-search]').addEventListener('keydown', e => {if(e.key === 'Enter'){e.preventDefault();load();}});
  get('[data-promo-year]').addEventListener('change', load);
  get('[data-promo-status]').addEventListener('change', () => {page=1;render();});
  get('[data-promo-reset]').addEventListener('click', () => {get('[data-promo-search]').value='';get('[data-promo-year]').value='';get('[data-promo-status]').value='';load();});
  get('[data-promo-prev]').addEventListener('click', () => {if(page>1){page--;render();}});
  get('[data-promo-next]').addEventListener('click', () => {if(page*pageSize<visible().length){page++;render();}});
  get('[data-promo-close]').addEventListener('click', () => {get('[data-promo-details]').close();});
  get('[data-promo-body]').addEventListener('click', event => {
    const button = event.target.closest('[data-promo-detail]'); if(!button)return;
    const record = records.find(item => String(item.id) === button.dataset.promoDetail); if(!record)return;
    const items = [
      ['Promo Code',record.code],['Homeowner',record.homeowner_name],['Homeowner ID',record.user_id],
      ['Coverage Year',record.coverage_year],['Date Generated',record.created_at],['Expiration Date',record.expires_at],
      ['Current Status',record.status],['Advance Payment ID',record.payment_id],['Advance Payment Date',record.payment_date],
      ['Date Redeemed',record.redeemed_at],['Applied Request ID',record.redeemed_request_id],
      ['Request Status',record.request_status],['Original Request Fee',record.original_request_fee],['Date Revoked',record.revoked_at]
    ];
    get('[data-promo-detail-values]').innerHTML = items.map(([name,value])=>`<div><dt style="font-weight:600">${esc(name)}</dt><dd style="margin:4px 0 0">${display(value)}</dd></div>`).join('');
    get('[data-promo-details]').showModal();
  });
  let loaded = false;
  document.querySelectorAll('.sidebar-nav [data-tab="promo-codes-tab"]').forEach(link => link.addEventListener('click', () => {loaded=true;load();}));
  if (container.closest('.tab-content')?.classList.contains('active')) {loaded=true;load();}
  // Hash-based deep links are activated by the existing sidebar controller.
  if (!loaded && location.hash === '#promo-codes') {loaded=true;load();}
});
