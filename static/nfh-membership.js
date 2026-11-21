/* HOA membership reconciliation — dedicated UI; no modifications to SOA transactions. */
(()=>{
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content||'';
  async function json(url,opts={}){
    const res=await fetch(url,{credentials:'same-origin',...opts,headers:{'X-CSRF-Token':csrf(),...(opts.headers||{})}});
    const v=await res.json();if(!res.ok)throw Error(v.message||'Request failed.');return v;
  }
  const form=$('nfhMembershipForm'),out=$('nfhMembershipOutput');
  if(form&&out){
    form.addEventListener('submit',async e=>{
      e.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';const btn=form.querySelector('button');btn.disabled=true;out.textContent='Validating the file against the current homeowner registry…';
      try{
        const data=await json('/treasurer/membership/preview',{method:'POST',body:new FormData(form)});
        const cs=data.counts||{};
        let html='<h3>Validation Preview</h3><p>'+Number(cs['Ready to Update']||0)+' existing-account changes · '+Number(cs['Valid — Pending Account Match']||0)+' new pending matches · '+Number(cs.Unchanged||0)+' unchanged · '+Number(cs.Duplicate||0)+' duplicates · '+Number(cs['Requires Review']||0)+' require review · '+Number(cs.Invalid||0)+' invalid</p>';
        html+='<div class="table-responsive"><table class="data-table"><thead><tr><th>Row</th><th>Homeowner ID</th><th>Imported Name</th><th>Registered Name</th><th>Address</th><th>Current HOA Status</th><th>Proposed</th><th>Validation Result</th><th>Remarks</th></tr></thead><tbody>';
        for(const r of data.results||[])html+='<tr>'+[r.row,r.homeowner_id,r.name,r.registered_name,r.address,r.current,r.proposed,r.validation_result,r.message].map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>';
        html+='</tbody></table></div>';
        if(!(cs.Invalid||0)&&!(cs.Duplicate||0)&&(cs['Ready to Update']||cs['Valid — Pending Account Match']||cs['Requires Review']))html+='<button class="btn btn-primary" type="button" id="nfhMembershipSubmit">Submit for Admin Approval</button>';
        if(cs.Invalid||cs.Duplicate)html+='<p>Correct invalid or duplicate rows and revalidate before submitting. No changes have been applied.</p>';
        if(cs['Requires Review'])html+='<p>Rows marked Requires Review will be retained for authorized verification; they cannot update a homeowner status automatically.</p>';
        out.innerHTML=html;
        $('nfhMembershipSubmit')?.addEventListener('click',async()=>{
          if(!confirm('Submit these validated membership classifications for Administrator approval?'))return;
          const b=$('nfhMembershipSubmit');b.disabled=true;try{
            const v=await json('/treasurer/membership/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:data.token})});
            out.textContent=v.message+' Batch #'+v.batch_id+' · '+v.submitted+' existing-account changes · '+v.pending+' pending accounts · '+v.review+' review cases.';loadRecords();
          }catch(err){out.textContent=err.message;b.disabled=false;}
        });
      }catch(err){out.textContent=err.message;}finally{delete form.dataset.busy;btn.disabled=false;}
    });
  }

  const records=$('nfhMembershipRecords');
  async function loadRecords(){
    if(!records)return;
    records.textContent='Loading reconciliation records…';
    try{
      const params=new URLSearchParams({status:$('nfhMembershipFilter')?.value||'All',q:$('nfhMembershipSearch')?.value||''});
      const result=await json('/treasurer/membership/records?'+params);
      let html='<div class="table-responsive"><table class="data-table"><thead><tr><th>Homeowner ID</th><th>Name</th><th>Address</th><th>Imported Status</th><th>Reconciliation Status</th><th>Matched Account</th></tr></thead><tbody>';
      for(const r of result.records)html+='<tr>'+[r.imported_homeowner_id,r.imported_name,r.imported_address,r.imported_status,r.reconciliation_status,r.matched_homeowner_id||'—'].map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>';
      html+='</tbody></table></div>';
      records.innerHTML=result.records.length?html:'No reconciliation records found.';
    }catch(e){records.textContent=e.message;}
  }
  $('nfhMembershipRecordsRefresh')?.addEventListener('click',loadRecords);
  $('nfhMembershipFilter')?.addEventListener('change',loadRecords);
  $('nfhMembershipSearch')?.addEventListener('change',loadRecords);
  if(records)loadRecords();
  // Admin modal: reuse the original IDs, endpoints, and existing reconciliation renderers.
  const membershipModal=$('nfhMembershipModal');
  const membershipOpen=$('nfhMembershipModalOpen');
  let focusBeforeMembership=null;
  function membershipView(view){
    if(!membershipModal)return;
    membershipModal.querySelectorAll('[data-membership-panel]').forEach(p=>{p.hidden=p.dataset.membershipPanel!==view;});
    membershipModal.querySelectorAll('[data-membership-view]').forEach(b=>{
      const active=b.dataset.membershipView===view;
      b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;
      b.classList.toggle('btn-primary',active);b.classList.toggle('btn-secondary',!active);
    });
  }
  function closeMembership(){
    if(!membershipModal||!membershipModal.classList.contains('show'))return;
    membershipModal.classList.remove('show');membershipModal.setAttribute('aria-hidden','true');
    document.body.style.overflow=membershipModal.dataset.previousOverflow||'';
    (focusBeforeMembership?.isConnected?focusBeforeMembership:membershipOpen)?.focus();
  }
  membershipOpen?.addEventListener('click',()=>{
    if(!membershipModal)return;
    focusBeforeMembership=document.activeElement;
    membershipModal.dataset.previousOverflow=document.body.style.overflow;
    membershipModal.classList.add('show');membershipModal.setAttribute('aria-hidden','false');
    document.body.style.overflow='hidden';
    membershipView('approvals');
    $('nfhMembershipModalClose')?.focus();
    refresh();loadAdminRecords();
  });
  $('nfhMembershipModalClose')?.addEventListener('click',closeMembership);
  membershipModal?.addEventListener('click',e=>{if(e.target===membershipModal)closeMembership();});
  membershipModal?.querySelectorAll('[data-membership-view]').forEach(b=>b.addEventListener('click',()=>{membershipView(b.dataset.membershipView);b.focus();}));
  membershipModal?.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMembership();return;}
    if(e.key!=='Tab')return;
    const choices=[...membershipModal.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href]')]
      .filter(el=>el.getClientRects().length && el.tabIndex>=0);
    if(!choices.length)return;
    if(e.shiftKey&&document.activeElement===choices[0]){e.preventDefault();choices[choices.length-1].focus();}
    else if(!e.shiftKey&&document.activeElement===choices[choices.length-1]){e.preventDefault();choices[0].focus();}
  });
  const adminRecords=$('nfhMembershipAdminRecords');
  async function loadAdminRecords(){
    if(!adminRecords)return;
    try{
      const result=await json('/treasurer/membership/records?status=All');
      const pending=result.records.filter(r=>r.reconciliation_status!=='Reconciled');
      adminRecords.replaceChildren();
      if(!pending.length){adminRecords.textContent='No pending account matches.';return;}
      for(const r of pending){
        const div=document.createElement('div');div.className='content-card';div.style.marginTop='12px';
        div.innerHTML='<strong>'+esc(r.imported_homeowner_id)+'</strong> · '+esc(r.imported_name)+' · '+esc(r.imported_address)+' · '+esc(r.imported_status)+' · '+esc(r.reconciliation_status)+'<div><input class="form-input" type="number" min="1" placeholder="Verified homeowner account numeric ID"><label><input type="checkbox"> Identity verified (required for conflicting name/address)</label><button type="button" class="btn btn-secondary">Manually Match</button><p role="status"></p></div>';
        const input=div.querySelector('input[type=number]'),check=div.querySelector('input[type=checkbox]'),button=div.querySelector('button'),msg=div.querySelector('p');
        button.addEventListener('click',async()=>{
          if(!input.value||!confirm('Match this record with verified account #'+input.value+'? The IDs must match.'))return;
          button.disabled=true;
          try{const out=await json('/admin/membership/match/'+r.id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({homeowner_account_id:input.value,identity_reviewed:check.checked,confirm:true})});msg.textContent=out.message;await loadAdminRecords();}
          catch(e){msg.textContent=e.message;}finally{button.disabled=false;}
        });adminRecords.append(div);
      }
    }catch(e){adminRecords.textContent=e.message;}
  }
  $('nfhMembershipAdminRefresh')?.addEventListener('click',loadAdminRecords);
  if(adminRecords&&!membershipModal)loadAdminRecords();

  const pending=$('nfhMembershipPending');
  async function refresh(){
    if(!pending)return;pending.textContent='Loading pending reconciliation batches…';
    try{
      const result=await json('/admin/membership/pending');
      if(!result.batches?.length){pending.textContent='No pending membership reconciliation requests.';return;}
      pending.replaceChildren();
      for(const b of result.batches){
        const wrap=document.createElement('div');wrap.className='content-card';wrap.style.marginTop='12px';
        let html='<h3>Batch #'+esc(b.id)+' · '+esc(b.source_filename)+'</h3><p>Submitted by '+esc(b.submitted_by)+' · '+esc(b.changed_rows)+' changes · '+esc(b.unchanged_rows)+' unchanged</p>';
        html+='<div class="table-responsive"><table class="data-table"><thead><tr><th>Homeowner ID</th><th>Name</th><th>Address</th><th>Previous</th><th>Proposed</th></tr></thead><tbody>';
        for(const c of b.changes)html+='<tr>'+[c.homeowner_public_id,c.name_snapshot,c.address_snapshot,c.previous_status,c.proposed_status].map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>';
        html+='</tbody></table></div><button type="button" class="btn btn-primary" data-action="approve">Approve Membership Changes</button> <button type="button" class="btn btn-secondary" data-action="reject">Reject</button><p class="nfh-membership-feedback" role="status"></p>';
        wrap.innerHTML=html;pending.append(wrap);
        wrap.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',async()=>{
          const action=button.dataset.action;if(!confirm(action==='approve'?'Approve all membership status changes in batch #'+b.id+'?':'Reject this reconciliation batch?'))return;
          wrap.querySelectorAll('[data-action]').forEach(v=>v.disabled=true);
          try{const v=await json('/admin/membership/decide/'+encodeURIComponent(b.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});wrap.querySelector('.nfh-membership-feedback').textContent=v.message;await refresh();}
          catch(e){wrap.querySelector('.nfh-membership-feedback').textContent=e.message;wrap.querySelectorAll('[data-action]').forEach(v=>v.disabled=false);}
        }));
      }
    }catch(e){pending.textContent=e.message+' (Apply the new consolidated database tables before using this feature.)';}
  }
  $('nfhMembershipRefresh')?.addEventListener('click',refresh);
  if(pending&&!membershipModal)refresh();
})();
