(() => {
  'use strict';
  const role = window.NFH_MANAGE_ROLE;
  const message = document.getElementById('message');
  const list = document.getElementById('agreementsList');
  const make = (tag, value) => {
    const element = document.createElement(tag);
    element.textContent = value;
    return element;
  };
  async function api(url, body) {
    const settings = body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    };
    const response = await fetch(url, settings);
    const data = await response.json();
    if (!response.ok) throw Error(data.message || 'Unable to complete request.');
    return data;
  }
  function status(error) { message.textContent = error.message || String(error); }
  async function ownerRecords() {
    const properties = (await api('/api/renter/properties')).properties || [];
    const select = document.getElementById('propertySelect');
    select.replaceChildren();
    const empty = make('option', 'Choose your verified property'); empty.value = '';
    select.appendChild(empty);
    for (const property of properties) {
      const option = make('option', `${property.property_code} — Block ${property.block}, Lot ${property.lot}`);
      option.value = property.id; select.appendChild(option);
      const card = make('div', `${property.property_code} — Block ${property.block}, Lot ${property.lot}`);
      card.className = 'record';
      const expand = make('button', 'View Property Dues');
      expand.type = 'button';
      expand.onclick = async () => {
        try {
          const result = await api(`/api/property-ledger/properties/${property.id}/dues`);
          const ledger = make('div', 'Property-based ledger (not yet production-authoritative):');
          for (const due of result.dues || []) {
            ledger.appendChild(make('p', `${due.billing_period}: ₱${due.amount_due} — ${due.payer_type} — Outstanding ₱${due.outstanding_balance}`));
          }
          if (!(result.dues || []).length) ledger.appendChild(make('p', 'No property-ledger dues recorded.'));
          card.appendChild(ledger); expand.remove();
        } catch (err) { status(err); }
      };
      card.appendChild(expand); list.appendChild(card);
    }
    if (!properties.length) list.appendChild(make('p','No verified properties are linked to this account.'));
    const agreements = (await api('/api/homeowner/renter-agreements')).agreements || [];
    const services = (await api('/api/renter/eligible-services')).services || [];
    for (const agreement of agreements) {
      const card = make('div', `Agreement #${agreement.id}: ${agreement.property_code} — ${agreement.full_name} — ${agreement.payer_type} Pays — ${agreement.verification_status}; Renter acknowledged: ${Boolean(agreement.renter_acknowledged_at)}`);
      card.className = 'record';
      if (agreement.verification_status === 'Pending' && !agreement.homeowner_acknowledged_at) {
        const button = make('button','Acknowledge Agreement');
        button.onclick = async () => {
          try { await api(`/api/renter/agreements/${agreement.id}/acknowledge`,{}); await refresh(); }
          catch (err) {status(err);}
        };
        card.appendChild(button);
      }
      if (agreement.verification_status === 'Verified') {
        const authorized = (await api(`/api/renter/agreements/${agreement.id}/services`)).services || [];
        const authorizedIds = new Set(authorized.map(service => Number(service.service_id)));
        const select = make('select','');
        select.setAttribute('aria-label', `Authorized service for agreement ${agreement.id}`);
        services.forEach(service => {
          const option = make('option',service.service_name);
          option.value = service.id;
          select.appendChild(option);
        });
        const summary = make('p', `Standing authorizations: ${authorized.map(service=>service.service_name).join(', ') || 'None'}`);
        const grant = make('button','Grant Authorization');
        const revoke = make('button','Revoke Authorization');
        const change = async enabled => {
          try {
            if (!select.value) throw Error('Select a service first.');
            await api(`/api/renter/agreements/${agreement.id}/services`, {service_id: Number(select.value), enabled});
            await refresh();
          } catch (err) {status(err);}
        };
        grant.onclick = () => change(true); revoke.onclick = () => change(false);
        card.append(summary,select,grant,revoke);
      }
      list.appendChild(card);
    }
  }
  async function adminRecords() {
    const agreements = (await api('/api/admin/renter-agreements')).agreements || [];
    if (!agreements.length) list.appendChild(make('p','No rental agreements found.'));
    for (const agreement of agreements) {
      const card = make('div', `Agreement #${agreement.id}: ${agreement.property_code} — ${agreement.full_name} (${agreement.email}) — ${agreement.payer_type} Pays — ${agreement.verification_status}; Homeowner acknowledged: ${Boolean(agreement.homeowner_acknowledged_at)}; Renter acknowledged: ${Boolean(agreement.renter_acknowledged_at)}`);
      card.className = 'record';
      if (agreement.verification_status === 'Pending') {
        for (const action of ['approve','reject']) {
          const button = make('button',action === 'approve' ? 'Verify Occupancy' : 'Reject');
          button.onclick = async () => {
            try {await api(`/api/admin/renter-agreements/${agreement.id}/verify`,{action}); await refresh();}
            catch (err) {status(err);}
          };
          card.appendChild(button);
        }
      }
      if (agreement.verification_status === 'Verified') {
        const button = make('button','Terminate Occupancy');
        button.onclick = async () => {
          if (!confirm('Terminate verified occupancy and revoke standing authorizations?')) return;
          try {await api(`/api/admin/renter-agreements/${agreement.id}/terminate`,{}); await refresh();}
          catch (err) {status(err);}
        };
        card.appendChild(button);
      }
      list.appendChild(card);
    }
  }
  async function refresh() {
    list.replaceChildren();
    try {if (role === 'Admin') await adminRecords(); else await ownerRecords();}
    catch (error) {status(error);}
  }
  const form = document.getElementById('inviteForm');
  if (form) form.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      message.textContent = (await api('/api/renter/invitations',Object.fromEntries(new FormData(form).entries()))).message;
      form.reset(); await refresh();
    } catch (error) {status(error);}
  });
  refresh();
})();
