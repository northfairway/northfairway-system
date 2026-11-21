(()=>{'use strict';
const form=document.querySelector('#renterEnrollment'), feedback=document.querySelector('#feedback');
const message=(text)=>{if(feedback)feedback.textContent=text; const admin=document.querySelector('#claimStatus');if(admin)admin.textContent=text;};
async function api(url,data){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json().catch(()=>({message:'Invalid server response.'}));if(!r.ok)throw Error(v.message||'Request failed');return v;}
if(form){
const fields=()=>Object.fromEntries(new FormData(form).entries());
document.querySelector('#sendCode').addEventListener('click',async()=>{try{const v=await api('/api/send-registration-code',{email:fields().email});message(v.message);}catch(e){message(e.message);}});
document.querySelector('#verifyCode').addEventListener('click',async()=>{try{const v=await api('/api/verify-registration-code',{email:fields().email,code:fields().code});message(v.message);}catch(e){message(e.message);}});
form.addEventListener('submit',async e=>{e.preventDefault();const d=fields();try{if(d.password!==d.password_confirm)throw Error('Passwords do not match.');const v=await api('/api/enrollment/renter',d);message(v.message);form.reset();}catch(e){message(e.message);}});
}
const additional=document.querySelector('#extraPropertyClaim');
if(additional){
const list=document.querySelector('#myClaims');
async function reloadClaims(){try{const r=await fetch('/api/enrollment/my-claims');const d=await r.json();if(!r.ok)throw Error(d.message);list.replaceChildren();for(const c of d.claims){const p=document.createElement('p');p.textContent=`Block ${c.block}, Lot ${c.lot} — ${c.status}`;list.appendChild(p);}}catch(e){message(e.message);}}
additional.addEventListener('submit',async e=>{e.preventDefault();try{const v=await api('/api/enrollment/my-claims',Object.fromEntries(new FormData(additional).entries()));message(v.message);additional.reset();reloadClaims();}catch(err){message(err.message);}});reloadClaims();
}
const rows=document.querySelector('#claimRows');
if(rows){
const td=(tr,v)=>{const el=document.createElement('td');el.textContent=String(v??'');tr.appendChild(el);return el;};
const load=async()=>{try{const r=await fetch('/api/admin/property-claims');const v=await r.json();if(!r.ok)throw Error(v.message);rows.replaceChildren();for(const c of v.claims){const tr=document.createElement('tr');[c.id,`${c.first_name} ${c.last_name}`,c.claim_type,`${c.block} / ${c.lot}`,c.evidence_note,c.status,c.conflicting_owners].forEach(x=>td(tr,x));const action=td(tr,'');if(['Pending','Disputed'].includes(c.status)){const btn=document.createElement('button');btn.textContent='Review';btn.onclick=async()=>{const decision=prompt('Type: verify, reject, or dispute');if(!decision)return;const note=prompt('Enter HOA evidence and decision note (minimum 8 characters)');if(!note)return;try{const result=await api('/api/admin/property-claims/'+c.id+'/review',{decision,note});message(result.message);load();}catch(e){message(e.message);}};action.appendChild(btn);}rows.appendChild(tr);}if(!v.claims.length){const tr=document.createElement('tr');td(tr,'No property claims.').colSpan=8;rows.appendChild(tr);}}catch(e){message(e.message);}};
document.querySelector('#refresh').addEventListener('click',load);load();
const registry=document.querySelector('#registryForm');registry?.addEventListener('submit',async e=>{e.preventDefault();try{const v=await api('/api/admin/property-registry',Object.fromEntries(new FormData(registry).entries()));message(v.message);registry.reset();}catch(err){message(err.message);}});
}
})();
