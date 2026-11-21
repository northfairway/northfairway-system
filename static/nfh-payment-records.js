(()=>{'use strict';
const root=document.getElementById('payments-tab');if(!root)return;
const get=id=>document.getElementById(id), search=get('prSearch'),category=get('prCategory'),sort=get('prSort'),state=get('prState');
const pages={ready:1,awaiting:1,completed:1};let timer,sequence=0;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>'₱'+Number(v||0).toLocaleString('en-PH',{minimumFractionDigits:2,maximumFractionDigits:2});
const empty=(n,msg)=>`<tr><td colspan="${n}" class="text-center">${msg}</td></tr>`;
const link=(id,download=false)=>`/requests/${encodeURIComponent(id)}/document.pdf${download?'?download=1':''}`;
const renderRow=(kind,r)=>{
 const id=esc(r.id),name=esc(r.homeowner),svc=esc(r.service),o=esc(r.or_number),ref=esc(r.system_reference),dt=esc(r.payment_date);
 if(kind==='ready')return `<tr><td><code>${id}</code></td><td>${name}</td><td>${svc}</td><td><strong>${money(r.fee)}</strong></td><td><span class="status-pill status-ready-for-payment-release">Ready for Payment &amp; Release</span></td><td><div class="review-actions"><a class="btn btn-sm btn-secondary" href="/request/${encodeURIComponent(r.id)}/review">Review</a><a class="btn btn-sm btn-secondary" href="${link(r.id)}" target="_blank" rel="noopener">Preview Document</a><button type="button" class="btn btn-sm btn-success" data-payment-request-id="${id}">Process Payment &amp; Release</button></div></td></tr>`;
 if(kind==='awaiting')return `<tr><td><code>${id}</code></td><td>${name}</td><td>${svc}</td><td>${ref||'—'}</td><td>${dt||'—'}${o?`<br><small>OR/Ref: ${o}</small>`:''}</td><td><div class="review-actions"><a class="btn btn-sm btn-secondary" href="${link(r.id,true)}" download data-document-download>Download PDF</a><button type="button" class="btn btn-sm btn-primary" data-paid-release-id="${id}" data-issue-homeowner="${name}" data-issue-type="${svc}">Confirm Release</button></div></td></tr>`;
 return `<tr><td><code>${id}</code></td><td>${name}</td><td>${svc}</td><td>${money(r.fee)}</td><td>${ref||'—'}</td><td>${dt||'—'}${o?`<br><small>OR/Ref: ${o}</small>`:''}<br><span class="status-pill ${r.document_released?'status-completed':'status-pending'}">${r.document_released?'Released':'Paid – Awaiting Release'}</span></td><td><a class="btn btn-sm btn-secondary" href="${link(r.id,true)}" download data-document-download>Download PDF</a></td></tr>`;
};
async function load(){const token=++sequence;state.textContent='Loading matching database records…';
 const selected=category.value;root.querySelectorAll('[data-pr-section]').forEach(e=>e.hidden=selected!=='all'&&e.dataset.prSection!==selected);
 const jobs=['ready','awaiting','completed'].filter(k=>selected==='all'||selected===k);
 try{const results=await Promise.all(jobs.map(async k=>{
  const params=new URLSearchParams({search:search.value,category:k,sort:sort.value,page:String(pages[k]),limit:'15'});
  const resp=await fetch(`/api/treasurer/payment-release/records?${params}`,{credentials:'same-origin'});const data=await resp.json();if(!resp.ok||data.status!=='success')throw Error(data.message||'Unable to load records');return [k,data.sections[k]];
 }));if(token!==sequence)return;
 for(const [k,info] of results){const card=root.querySelector(`[data-pr-section="${k}"]`),body=card?.querySelector('tbody'),footer=root.querySelector(`[data-pr-pager="${k}"]`);if(!body||!footer)continue;
  const cols={ready:6,awaiting:6,completed:7}[k];body.innerHTML=info.records.length?info.records.map(r=>renderRow(k,r)).join(''):empty(cols,'No matching records found.');pages[k]=info.page;
  footer.replaceChildren();const count=document.createElement('span');count.textContent=`${info.total} records · Page ${info.page} of ${info.pages}`;footer.append(count);
  for(const [title,target,disabled] of [['Previous',info.page-1,info.page<=1],['Next',info.page+1,info.page>=info.pages]]){const b=document.createElement('button');b.type='button';b.className='btn btn-sm btn-secondary';b.textContent=title;b.disabled=disabled;b.addEventListener('click',()=>{pages[k]=target;load()});footer.append(b)}
 }state.textContent='Results are filtered across the database.';
 }catch(e){if(token===sequence)state.textContent=`Could not load payment records: ${e.message}`;}
}
function change(){Object.keys(pages).forEach(k=>pages[k]=1);clearTimeout(timer);timer=setTimeout(load,260)}
search.addEventListener('input',change);category.addEventListener('change',change);sort.addEventListener('change',change);
get('prReset').addEventListener('click',()=>{search.value='';category.value='all';sort.value='desc';change()});
root.addEventListener('click',e=>{if(e.target.closest('[data-payment-request-id],[data-paid-release-id]')){setTimeout(load,1500)}});
load();window.NFHPaymentRecords={refresh:load};
})();
