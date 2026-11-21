document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const desktopSidebarToggle = document.getElementById('desktopSidebarToggle');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const navItems = document.querySelectorAll('.sidebar-nav .nav-item[data-tab]');
    const tabContents = document.querySelectorAll('.tab-content');
    const pageTitle = document.getElementById('pageTitle');

    const setSidebarOpen = (open) => {
        if (!sidebar) return;
        sidebar.classList.toggle('open', open);
        document.body.classList.toggle('sidebar-open', open);
        if (sidebarToggle) sidebarToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    };

    // Keep icon-only navigation discoverable without changing role restrictions.
    document.querySelectorAll('.sidebar-nav .nav-item[data-tab], .sidebar-footer .nav-item').forEach(item => {
        const label = item.querySelector('span:not(.nav-count-badge)')?.textContent?.trim() || item.getAttribute('aria-label');
        if (label) { item.setAttribute('aria-label', label); item.title = label; }
    });

    const syncDesktopToggle = () => {
        if (!desktopSidebarToggle) return;
        const collapsed = document.body.classList.contains('sidebar-collapsed');
        desktopSidebarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        desktopSidebarToggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
        desktopSidebarToggle.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
        const icon = desktopSidebarToggle.querySelector('i');
        if (icon) icon.className = collapsed ? 'fa-solid fa-angles-right' : 'fa-solid fa-angles-left';
    };
    if (sidebarToggle) sidebarToggle.addEventListener('click', () => setSidebarOpen(!sidebar.classList.contains('open')));
    if (desktopSidebarToggle) desktopSidebarToggle.addEventListener('click', () => {
        if (window.innerWidth < 1024) return;
        const collapsed = document.body.classList.toggle('sidebar-collapsed');
        sessionStorage.setItem('nfhSidebarCollapsed', collapsed ? '1' : '0');
        syncDesktopToggle();
    });
    if (window.innerWidth >= 1024 && sessionStorage.getItem('nfhSidebarCollapsed') === '1') document.body.classList.add('sidebar-collapsed');
    syncDesktopToggle();
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', () => setSidebarOpen(false));

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && window.innerWidth < 1024 && sidebar?.classList.contains('open')) {
            setSidebarOpen(false);
            sidebarToggle?.focus();
        }
    });

    navItems.forEach((item, index) => {
        item.style.setProperty('--nav-order', index);
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const target = item.getAttribute('data-tab');
            navItems.forEach(i => i.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            item.classList.add('active');
            const tc = document.getElementById(target);
            if (tc) { tc.classList.add('active'); tc.scrollTop = 0; }
            if (pageTitle) pageTitle.textContent = item.querySelector('span').textContent;
            if (window.innerWidth < 1024) setSidebarOpen(false);
        });
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth >= 1024) setSidebarOpen(false);
        syncDesktopToggle();
    }, { passive: true });

    document.querySelectorAll('[data-activity-time]').forEach(el => {
        const raw = (el.dataset.activityTime || '').trim();
        const parsed = new Date(raw.replace(' ', 'T'));
        if (!Number.isNaN(parsed.getTime())) el.textContent = parsed.toLocaleString('en-US', {month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'}).replace(',', ' •');
    });

    const initialHash=(window.location.hash || '').replace('#','');
    if(initialHash){
        const initialNav=Array.from(navItems).find(item=>(item.getAttribute('href')||'')===`#${initialHash}`);
        if(initialNav) setTimeout(()=>initialNav.click(),0);
    }

    requestAnimationFrame(() => document.body.classList.add('navigation-ready'));

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.addEventListener('click', () => openModal('logoutModal'));
});

function openModal(id){ const m=document.getElementById(id); if(m) m.classList.add('show'); }
function closeModal(id){ const m=document.getElementById(id); if(m) m.classList.remove('show'); }
function escapeHtml(s){ if(!s) return ''; return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;"); }

// Professional in-system confirmation, toast, and inline validation utilities.
let activeConfirmResolve = null;
let activeConfirmTrigger = null;

function showToast(message, type='info', timeout=4200){
    const container=document.getElementById('toastContainer');
    if(!container || !message) return;
    const toast=document.createElement('div');
    toast.className=`system-toast toast-${type}`;
    const icon={success:'fa-circle-check',error:'fa-circle-xmark',warning:'fa-triangle-exclamation',info:'fa-circle-info'}[type] || 'fa-circle-info';
    toast.innerHTML=`<span class="toast-icon" aria-hidden="true"><i class="fa-solid ${icon}"></i></span><div class="toast-message"></div><button type="button" class="toast-close" aria-label="Dismiss notification">×</button>`;
    toast.querySelector('.toast-message').textContent=message;
    toast.querySelector('.toast-close').addEventListener('click',()=>dismissToast(toast));
    container.appendChild(toast);
    requestAnimationFrame(()=>toast.classList.add('show'));
    if(timeout) setTimeout(()=>dismissToast(toast),timeout);
}
function dismissToast(toast){
    if(!toast || toast.dataset.closing==='true') return;
    toast.dataset.closing='true'; toast.classList.remove('show');
    setTimeout(()=>toast.remove(),220);
}

function showConfirmModal({title='Confirm Action',message='',confirmText='Confirm',type='primary',context=[]}={}){
    const modal=document.getElementById('systemConfirmModal');
    if(!modal) return Promise.resolve(false);
    activeConfirmTrigger=document.activeElement;
    document.getElementById('systemConfirmTitle').textContent=title;
    document.getElementById('systemConfirmMessage').textContent=message;
    const contextWrap=document.getElementById('systemConfirmContext');
    contextWrap.innerHTML='';
    (context||[]).filter(item=>item && item.value!==undefined && item.value!=='').forEach(item=>{
        const row=document.createElement('div'); row.className='confirm-context-row';
        const label=document.createElement('span'); label.textContent=item.label;
        const value=document.createElement('strong'); value.textContent=String(item.value);
        row.append(label,value); contextWrap.appendChild(row);
    });
    contextWrap.hidden=!contextWrap.children.length;
    const confirmBtn=document.getElementById('systemConfirmButton');
    confirmBtn.textContent=confirmText;
    confirmBtn.className=`btn confirm-primary confirm-${type}`;
    modal.classList.add('show');
    confirmBtn.disabled=false;
    setTimeout(()=>confirmBtn.focus(),0);
    return new Promise(resolve=>{ activeConfirmResolve=resolve; });
}
function closeSystemConfirm(result=false){
    const modal=document.getElementById('systemConfirmModal');
    if(modal) modal.classList.remove('show');
    const resolver=activeConfirmResolve; activeConfirmResolve=null;
    if(resolver) resolver(Boolean(result));
    setTimeout(()=>activeConfirmTrigger?.focus?.(),0);
}
function confirmSystemAction(){ closeSystemConfirm(true); }

function clearInlineError(input){
    if(!input) return;
    input.classList.remove('field-invalid');
    const error=input.closest('.form-group')?.querySelector('.inline-validation-message');
    if(error) error.remove();
}
function showInlineError(input,message){
    if(!input){ showToast(message,'warning'); return; }
    clearInlineError(input); input.classList.add('field-invalid');
    const group=input.closest('.form-group') || input.parentElement;
    const error=document.createElement('div'); error.className='inline-validation-message'; error.setAttribute('role','alert'); error.textContent=message;
    group.appendChild(error); input.focus();
    input.addEventListener('input',()=>clearInlineError(input),{once:true});
}

function mirrorSubmitter(form, submitter){
    if (!form || !submitter || !submitter.name) return;
    let actionMirror=form.querySelector('input[data-submit-action-mirror="true"]');
    if(!actionMirror){ actionMirror=document.createElement('input'); actionMirror.type='hidden'; actionMirror.dataset.submitActionMirror='true'; form.appendChild(actionMirror); }
    actionMirror.name=submitter.name; actionMirror.value=submitter.value;
}
function lockWorkflowSubmit(form, submitter){
    if (!form || form.dataset.submitting === 'true') return false;
    mirrorSubmitter(form,submitter);
    form.dataset.submitting='true';
    form.querySelectorAll('button[type="submit"]').forEach(btn=>{btn.disabled=true;});
    if(submitter){ submitter.dataset.originalText=submitter.textContent; submitter.textContent='Processing…'; }
    return true;
}

async function submitPreviewAction(event, legacyMessage){
    event.preventDefault();
    const form=event.currentTarget, submitter=event.submitter;
    if(!submitter) return false;
    const action=(submitter.value || submitter.textContent || '').trim().toLowerCase();
    const reqId=document.getElementById('previewReqId')?.textContent || form.closest('tr')?.querySelector('code')?.textContent || '';
    let title='Confirm Action', message=legacyMessage || 'Confirm this action?', confirmText=submitter.textContent.trim(), type='primary';
    const feeName=form.querySelector('input[name="fee_name"]')?.value || '';
    if(feeName && action==='approve'){title='Approve Fee Change';message=`Are you sure you want to approve the proposed fee change for ${feeName}?`;confirmText='Yes, Approve Fee';}
    else if(feeName && action==='reject'){title='Reject Fee Change';message=`Are you sure you want to reject the proposed fee change for ${feeName}?`;confirmText='Yes, Reject Fee';type='danger';}
    else if(action==='approve'){title='Approve Document Request';message='Are you sure you want to approve this document request and continue it through the configured workflow?';confirmText='Yes, Approve Request';}
    else if((submitter.textContent||'').toLowerCase().includes('paid')){title='Confirm Face-to-Face Payment';message='Confirm that the Treasurer has received the cash payment and recorded the correct transaction details?';confirmText='Confirm Payment';}
    const ok=await showConfirmModal({title,message,confirmText,type,context:[{label:'Request ID',value:reqId}]});
    if(!ok) return false;
    if(!lockWorkflowSubmit(form,submitter)) return false;
    form.submit();
    return false;
}
// Automatically calculates the total amount due (Monthly Due x Missing Months)
function calculateAdjustment() {
    const monthlyDue = parseFloat(document.getElementById('adjMonthlyDue')?.value) || 0;
    const missingMonths = parseInt(document.getElementById('adjMissing')?.value, 10) || 0;
    const endMonthValue = document.getElementById('adjEndMonth')?.value || '';
    const proposedField = document.getElementById('adjProposed');
    const preview = document.getElementById('adjPeriodPreview');
    const previewText = document.getElementById('adjPeriodPreviewText');

    if (missingMonths > 0) proposedField.value = (monthlyDue * missingMonths).toFixed(2);
    else proposedField.value = '';

    if (!endMonthValue || missingMonths <= 0) {
        if (preview) preview.hidden = true;
        if (previewText) previewText.textContent = '—';
        return;
    }
    const [year,month] = endMonthValue.split('-').map(Number);
    const endDate = new Date(year, month-1, 1);
    const startDate = new Date(year, month-1-(missingMonths-1), 1);
    const fmt = d => d.toLocaleDateString(undefined,{month:'long',year:'numeric'});
    const period = missingMonths === 1 ? fmt(endDate) : `${fmt(startDate)} – ${fmt(endDate)}`;
    if (previewText) previewText.textContent = period;
    if (preview) preview.hidden = false;
    nfhUpdatePlanPreview();
}

function duesLookupNormalize(value){
    return String(value || '').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLowerCase().replace(/\s+/g,' ').trim();
}

function filterAdjustmentHomeowners(){
    const input=document.getElementById('adjHomeownerSearch');
    const hidden=document.getElementById('adjUserId');
    const results=document.getElementById('adjHomeownerResults');
    const noMatch=document.getElementById('adjHomeownerNoMatch');
    if(!input || !hidden || !results) return;

    if(hidden.value && input.value !== (input.dataset.selectedLabel || '')){
        hidden.value='';
        document.getElementById('adjSelectedHomeowner')?.setAttribute('hidden','');
    }

    const query=duesLookupNormalize(input.value);
    const options=Array.from(results.querySelectorAll('.homeowner-search-result'));
    if(!query){
        options.forEach(option=>option.hidden=true);
        if(noMatch) noMatch.hidden=true;
        results.hidden=true;
        return;
    }

    let shown=0;
    options.forEach(option=>{
        const match=duesLookupNormalize(option.dataset.search).includes(query);
        const visible=match && shown < 8;
        option.hidden=!visible;
        if(visible) shown+=1;
    });
    if(noMatch) noMatch.hidden=shown!==0;
    results.hidden=false;
}

function selectAdjustmentHomeowner(option){
    const input=document.getElementById('adjHomeownerSearch');
    const hidden=document.getElementById('adjUserId');
    const results=document.getElementById('adjHomeownerResults');
    const card=document.getElementById('adjSelectedHomeowner');
    if(!option || !input || !hidden) return;
    const name=option.dataset.name || 'Homeowner';
    const publicId=option.dataset.publicId || 'No Homeowner ID';
    const property=option.dataset.property || '';
    const outstanding=Number(option.dataset.outstanding || 0);
    const unpaidMonths=Number(option.dataset.unpaidMonths || 0);
    const label=`${name} — ${publicId}`;
    hidden.value=option.dataset.userId || '';
    input.value=label;
    input.dataset.selectedLabel=label;
    clearInlineError(input);
    if(results) results.hidden=true;
    const nameEl=document.getElementById('adjSelectedHomeownerName');
    const metaEl=document.getElementById('adjSelectedHomeownerMeta');
    if(nameEl) nameEl.textContent=name;
    if(metaEl) metaEl.textContent=`${publicId}${property ? ` · ${property}` : ''}`;
    const balanceEl=document.getElementById('adjSelectedHomeownerBalance');
    if(balanceEl) balanceEl.textContent=unpaidMonths>0 ? `Current outstanding: ${unpaidMonths} month${unpaidMonths===1?'':'s'} · ₱${outstanding.toFixed(2)}` : 'No currently outstanding monthly dues';
    if(card) card.hidden=false;
}

function clearAdjustmentHomeowner(){
    const input=document.getElementById('adjHomeownerSearch');
    const hidden=document.getElementById('adjUserId');
    const results=document.getElementById('adjHomeownerResults');
    if(input){ input.value=''; delete input.dataset.selectedLabel; input.focus(); clearInlineError(input); }
    if(hidden) hidden.value='';
    if(results) results.hidden=true;
    document.getElementById('adjSelectedHomeowner')?.setAttribute('hidden','');
    const balanceEl=document.getElementById('adjSelectedHomeownerBalance'); if(balanceEl) balanceEl.textContent='—';
}

function nfhUpdatePlanPreview(){
 const enabled=!!document.getElementById('nfhPlanEnabled')?.checked;
 const fields=document.getElementById('nfhPlanFields');if(fields)fields.hidden=!enabled;
 const schedule=document.getElementById('nfhPlanSchedule'),remarks=document.getElementById('nfhPlanRemarks');
 if(!schedule||!remarks)return;
 const outstanding=document.getElementById('nfhPlanOutstanding'),monthly=document.getElementById('nfhPlanInstallment'),installments=document.getElementById('nfhPlanInstallmentCount');
 schedule.dataset.valid='false';
 const body=document.getElementById('nfhPlanScheduleBody'),totalCell=document.getElementById('nfhPlanScheduleTotal');
 if(body)body.innerHTML='<tr><td colspan="3" class="nfh-plan-schedule-placeholder">Set the duration and first payment due date to preview installments.</td></tr>';
 if(totalCell)totalCell.textContent='₱0';remarks.value='';if(installments)installments.value='';if(monthly)monthly.value='—';
 const total=Number(document.getElementById('adjProposed')?.value||0),count=Number(document.getElementById('nfhPlanMonths')?.value||0),first=document.getElementById('nfhPlanFirstDue')?.value;
 if(outstanding)outstanding.value=Number.isInteger(total)&&total>=0?'₱'+total.toLocaleString('en-PH'):'—';
 if(!enabled||!Number.isInteger(total)||total<1||!Number.isInteger(count)||count<1||count>240||count>total||!/^\d{4}-\d{2}-\d{2}$/.test(first||''))return;
 const start=new Date(first+'T12:00:00');if(Number.isNaN(start.getTime()))return;
 const base=Math.floor(total/count),rem=total%count,firstAmount=base+(rem>0?1:0);
 if(monthly)monthly.value='₱'+firstAmount.toLocaleString('en-PH')+(rem?' (variable by ₱1)':'');
 if(installments)installments.value=String(count);
 const rows=Array.from({length:count},(_,i)=>{
   const due=new Date(start.getFullYear(),start.getMonth()+i,Math.min(start.getDate(),new Date(start.getFullYear(),start.getMonth()+i+1,0).getDate()));
   const mm=String(due.getMonth()+1).padStart(2,'0'),dd=String(due.getDate()).padStart(2,'0'),yyyy=due.getFullYear();
   return {number:i+1,date:`${mm}/${dd}/${yyyy}`,amount:base+(i<rem?1:0)};
 });
 if(body){body.replaceChildren();for(const row of rows){const tr=document.createElement('tr');for(const value of [String(row.number),row.date,'₱'+row.amount.toLocaleString('en-PH')]){const td=document.createElement('td');td.textContent=value;tr.appendChild(td);}tr.lastElementChild.classList.add('nfh-plan-schedule-amount');body.appendChild(tr);}}
 if(totalCell)totalCell.textContent='₱'+rows.reduce((sum,row)=>sum+row.amount,0).toLocaleString('en-PH');
 schedule.dataset.valid='true';
 remarks.value=`Payment plan for ${document.getElementById('adjMissing').value} missing months through ${document.getElementById('adjEndMonth').value}; total outstanding ₱${total.toLocaleString('en-PH')}; ${count} monthly installments (₱${firstAmount.toLocaleString('en-PH')}${rem?' initially; remainder distributed':''}); first due ${first}.`;
}
async function submitAdjustment(){
    const searchInput=document.getElementById('adjHomeownerSearch');
    const userId=document.getElementById('adjUserId')?.value || '';
    const monthsInput=document.getElementById('adjMissing');
    const endMonthInput=document.getElementById('adjEndMonth');
    const reasonInput=document.getElementById('adjReason');
    const missingMonths=monthsInput?.value || '';
    const endMonth=endMonthInput?.value || '';
    const proposed=document.getElementById('adjProposed')?.value || '';
    clearInlineError(searchInput); clearInlineError(monthsInput); clearInlineError(endMonthInput); clearInlineError(reasonInput);
    if(!userId){ showInlineError(searchInput,'Search for and select a homeowner by name or Homeowner ID.'); searchInput?.focus(); return; }
    if(!endMonth){ showInlineError(endMonthInput,'Select the latest month included in the missing-dues period.'); endMonthInput?.focus(); return; }
    if(!missingMonths || parseInt(missingMonths,10)<=0){ showInlineError(monthsInput,'Please enter a valid number of missing months.'); monthsInput?.focus(); return; }
    if((reasonInput?.value || '').trim().length < 3){ showInlineError(reasonInput,'Please provide a short reason for the missing dues entry.'); reasonInput?.focus(); return; }
    const planEnabled=document.getElementById('nfhPlanEnabled')?.checked;
    if(planEnabled&&document.getElementById('nfhPlanSchedule')?.dataset.valid!=='true'){showToast('Enter a valid whole-peso payment plan schedule.','error');return;}
    const homeowner=document.getElementById('adjSelectedHomeownerName')?.textContent || 'Selected homeowner';
    const homeownerMeta=document.getElementById('adjSelectedHomeownerMeta')?.textContent || '';
    const period=document.getElementById('adjPeriodPreviewText')?.textContent || '—';
    const ok=await showConfirmModal({
        title:'Apply Missing Monthly Dues',
        message:'Record these missing monthly dues and notify the homeowner?',
        confirmText:'Apply Missing Dues',
        type:'primary',
        context:[{label:'Homeowner',value:homeowner},{label:'Homeowner ID / Property',value:homeownerMeta},{label:'Missing Period',value:period},{label:'Missing Months',value:missingMonths},{label:'Total',value:proposed ? `₱${Number(proposed).toFixed(2)}` : ''}]
    });
    if(!ok) return;
    window.NFHLoading?.show('Applying missing monthly dues…');
    fetch('/api/treasurer/adjustment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        user_id:userId,monthly_due:document.getElementById('adjMonthlyDue').value,missing_months:missingMonths,end_month:endMonth,
        proposed_adjustment:proposed,reason:reasonInput?.value || '',payment_plan:planEnabled?{enabled:true,months:document.getElementById('nfhPlanMonths').value,first_due:document.getElementById('nfhPlanFirstDue').value}:null
    })})
    .then(async r=>{const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.message||'Unable to apply missing dues.'); return d;})
    .then(d=>{ if(d.status==='success'){showToast(d.message||'Missing dues recorded.','success');setTimeout(()=>location.reload(),700);} else showToast(d.message||'Unable to apply missing dues.','error'); })
    .catch(e=>showToast(e.message||'Unable to apply missing dues.','error'))
    .finally(()=>window.NFHLoading?.hide());
}

function initSystemFeedback(){
    (window.SERVER_FLASH_MESSAGES || []).forEach(item=>showToast(item.message,item.category==='success'?'success':item.category==='error'?'error':item.category==='warning'?'warning':'info'));
    document.getElementById('systemConfirmCancel')?.addEventListener('click',()=>closeSystemConfirm(false));
    document.getElementById('systemConfirmButton')?.addEventListener('click',confirmSystemAction);
    document.getElementById('systemConfirmModal')?.addEventListener('click',e=>{if(e.target===e.currentTarget) closeSystemConfirm(false);});
    document.addEventListener('keydown',e=>{if(e.key==='Escape' && document.getElementById('systemConfirmModal')?.classList.contains('show')){e.preventDefault();closeSystemConfirm(false);}});
    document.querySelectorAll('form[data-system-confirm]').forEach(form=>form.addEventListener('submit',async e=>{
        if(form.dataset.confirmed==='true') return;
        e.preventDefault();
        const submitter=e.submitter;
        const ok=await showConfirmModal({title:form.dataset.confirmTitle||'Confirm Action',message:form.dataset.systemConfirm,confirmText:form.dataset.confirmText||submitter?.textContent?.trim()||'Confirm',type:form.dataset.confirmType||'primary'});
        if(!ok) return;
        mirrorSubmitter(form,submitter);
        form.dataset.confirmed='true';
        form.submit();
    }));
}
document.addEventListener('DOMContentLoaded',()=>{
    initSystemFeedback();
    const endMonth=document.getElementById('adjEndMonth');
    if(endMonth && !endMonth.value){const d=new Date();endMonth.value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;endMonth.max=endMonth.value;calculateAdjustment();}
});

// Lightweight role-aware live metrics. Keeps the existing Flask/MySQL architecture.
async function refreshLiveMetrics(){
  try{
    const res=await fetch('/api/live-metrics',{headers:{'Accept':'application/json'},cache:'no-store'});
    if(!res.ok)return; const data=await res.json(); if(data.status!=='success')return;
    document.querySelectorAll('[data-metric]').forEach(el=>{
      const key=el.dataset.metric; if(!(key in data.metrics))return;
      const raw=data.metrics[key] ?? 0;
      const next=el.dataset.currency==='true' ? `₱${Number(raw||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}` : String(raw);
      if(el.classList.contains('nav-count-badge')) el.hidden=Number(raw||0) <= 0;
      if(el.textContent.trim()!==next){el.textContent=next;el.classList.remove('metric-updated');void el.offsetWidth;el.classList.add('metric-updated');}
    });
  }catch(e){console.debug('Live metrics unavailable',e);}
}
refreshLiveMetrics(); setInterval(refreshLiveMetrics,10000);

function closeAccountMenus(){
  document.querySelectorAll('.account-dropdown').forEach(menu=>menu.setAttribute('hidden',''));
  document.querySelectorAll('.account-menu-button').forEach(btn=>btn.setAttribute('aria-expanded','false'));
}
function toggleAccountMenu(btn){
  const menu=btn.parentElement.querySelector('.account-dropdown');
  if(!menu)return;
  const opening=menu.hasAttribute('hidden');
  closeAccountMenus();
  if(opening){menu.removeAttribute('hidden');btn.setAttribute('aria-expanded','true');}
}
function openAccountProfile(){closeAccountMenus();openModal('accountProfileModal')}
document.addEventListener('click',e=>{if(!e.target.closest('.account-menu-wrap'))closeAccountMenus();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const open=document.querySelector('.account-menu-button[aria-expanded=\"true\"]');closeAccountMenus();open?.focus();}});

document.addEventListener('click', (event) => {
  const jump=event.target.closest('[data-tab-jump]'); if(!jump)return;
  const target=jump.dataset.tabJump; const nav=document.querySelector(`.sidebar .nav-item[data-tab="${target}"]`);
  if(nav){nav.click(); window.scrollTo({top:0,behavior:'smooth'});}
});

function settleMonthlyDuesFromButton(button){
    if(!button) return;
    return settleMonthlyDues(
        button.dataset.duesUserId,
        button.dataset.duesHomeowner,
        button.dataset.duesHomeownerId,
        Number(button.dataset.duesMissing || 0),
        Number(button.dataset.duesTotal || 0),
        button.dataset.duesOldest || '',
        button.dataset.duesPeriods || ''
    );
}

let nfhCashState={userId:null,name:'',outstanding:0,busy:false,key:null,previous:null};
const nfhPeso=x=>'₱'+Number(x).toLocaleString('en-PH',{maximumFractionDigits:0});
function nfhCashClose(){if(nfhCashState.busy)return;const modal=document.getElementById('nfhCashModal');modal.hidden=true;document.body.classList.remove('nfh-cash-open');nfhCashState.previous?.focus();}
function nfhCashPreview(){const amount=Number(document.getElementById('nfhCashAmount').value);const valid=Number.isSafeInteger(amount)&&amount>0&&amount<=nfhCashState.outstanding;const error=document.getElementById('nfhCashError');error.hidden=valid||!document.getElementById('nfhCashAmount').value;error.textContent='Enter a whole-peso cash amount no greater than the outstanding balance.';document.getElementById('nfhCashPreview').textContent=valid?nfhPeso(amount):'—';document.getElementById('nfhCashRemaining').textContent=valid?nfhPeso(nfhCashState.outstanding-amount):'—';document.getElementById('nfhCashRemarks').value=valid?`Verified cash payment of ${nfhPeso(amount)} received for ${nfhCashState.name}. Remaining outstanding: ${nfhPeso(nfhCashState.outstanding-amount)}.`:'';return valid;}
async function settleMonthlyDues(userId, homeowner, homeownerId, missingMonths, total, oldestDue, periods){
 if(!userId)return;
 const modal=document.getElementById('nfhCashModal');nfhCashState.previous=document.activeElement;
 try{const r=await fetch('/api/treasurer/payment-overview/'+encodeURIComponent(userId),{credentials:'same-origin'});const d=await r.json();if(!r.ok)throw Error(d.error||'Verified payment information unavailable');nfhCashState={...nfhCashState,userId,name:homeowner,outstanding:Number(d.outstanding),busy:false,key:globalThis.crypto?.randomUUID?.()||('cash-'+Date.now()+'-'+Math.random().toString(36).slice(2))};
  if(!Number.isSafeInteger(nfhCashState.outstanding)||nfhCashState.outstanding<=0)throw Error('No whole-peso outstanding balance is available for payment');
  const put=(id,x)=>document.getElementById(id).textContent=x;
  put('nfhCashName',homeowner);put('nfhCashId',homeownerId||userId);put('nfhCashOutstanding',nfhPeso(d.outstanding));put('nfhCashMonths',d.unpaid_months);put('nfhCashCurrent',nfhPeso(d.current_regular));put('nfhCashSuggested',nfhPeso(d.combined_suggested));
  document.getElementById('nfhCashPlan').hidden=!d.plan;if(d.plan){put('nfhCashPlanStatus',d.plan.status);put('nfhCashInst',nfhPeso(d.plan.installment));put('nfhCashPlanBalance',nfhPeso(d.plan.remaining));put('nfhCashDue',d.plan.next_due||'—');put('nfhCashCount',d.plan.remaining_installments);}
  const now=new Date();document.getElementById('nfhCashDate').value=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');document.getElementById('nfhCashDate').max=document.getElementById('nfhCashDate').value;
  document.getElementById('nfhCashAmount').value=d.combined_suggested||'';document.getElementById('nfhCashAmount').max=d.outstanding;document.getElementById('nfhCashRef').value='';nfhCashPreview();modal.hidden=false;document.body.classList.add('nfh-cash-open');document.getElementById('nfhCashAmount').focus();
 }catch(e){showToast(e.message||'Unable to open payment modal.','error');}
}
document.addEventListener('DOMContentLoaded',()=>{const modal=document.getElementById('nfhCashModal');if(!modal)return;modal.querySelectorAll('[data-cash-close]').forEach(el=>el.addEventListener('click',nfhCashClose));document.getElementById('nfhCashAmount').addEventListener('input',nfhCashPreview);modal.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();nfhCashClose();}if(e.key==='Tab'){const nodes=[...modal.querySelectorAll('button,input,textarea')].filter(el=>!el.disabled&&el.offsetParent!==null);if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes[nodes.length-1].focus();}else if(!e.shiftKey&&document.activeElement===nodes[nodes.length-1]){e.preventDefault();nodes[0].focus();}}});document.getElementById('nfhCashForm').addEventListener('submit',async e=>{e.preventDefault();if(nfhCashState.busy||!nfhCashPreview())return;const button=document.getElementById('nfhCashConfirm');nfhCashState.busy=true;button.disabled=true;button.textContent='Recording…';try{const r=await fetch('/api/treasurer/settle-dues',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:nfhCashState.userId,amount:document.getElementById('nfhCashAmount').value,payment_date:document.getElementById('nfhCashDate').value,reference:document.getElementById('nfhCashRef').value,request_key:nfhCashState.key})});const d=await r.json();if(!r.ok)throw Error(d.message||'Could not record payment');showToast('Verified cash payment recorded.','success');nfhCashState.busy=false;nfhCashClose();window.location.reload();}catch(e){const error=document.getElementById('nfhCashError');error.hidden=false;error.textContent=e.message;}finally{nfhCashState.busy=false;button.disabled=false;button.textContent='Confirm Payment';}});});

window.filterAdjustmentHomeowners=filterAdjustmentHomeowners;
window.selectAdjustmentHomeowner=selectAdjustmentHomeowner;
window.clearAdjustmentHomeowner=clearAdjustmentHomeowner;
window.submitAdjustment=submitAdjustment;
window.settleMonthlyDues=settleMonthlyDues;
window.settleMonthlyDuesFromButton=settleMonthlyDuesFromButton;

function localIsoDate(){
    const d=new Date();
    const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), day=String(d.getDate()).padStart(2,'0');
    return `${y}-${m}-${day}`;
}
function openPaymentVerificationModal(reqId){
    const req=typeof ALL_REQUESTS!=='undefined' ? ALL_REQUESTS.find(r=>String(r.id)===String(reqId)) : null;
    const form=document.getElementById('paymentVerificationForm');
    if(!form || !req){ showToast('Unable to open payment and release for this request.','error'); return; }
    if(!['Ready for Payment & Release','Approved','Awaiting Payment Verification'].includes(req.status) || req.payment_status!=='Unpaid'){
        showToast('This request is not currently ready for face-to-face payment and release. Refresh the page to see its latest status.','warning'); return;
    }
    form.action='/officer/update_payment/'+encodeURIComponent(req.id);
    form.dataset.requestId=req.id; form.dataset.submitting='false';
    form.querySelectorAll('button[type="submit"]').forEach(btn=>{btn.disabled=false;if(btn.dataset.originalText){btn.textContent=btn.dataset.originalText;delete btn.dataset.originalText;}});
    const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value ?? '—';};
    set('paymentVerifyReqId',req.id); set('paymentVerifyHomeowner',req.homeowner||'—'); set('paymentVerifyType',req.request_type||'—');
    set('paymentVerifyAmount',`₱${Number(req.fee||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`);
    const orNo=document.getElementById('paymentVerifyOR'), date=document.getElementById('paymentVerifyDate'), released=document.getElementById('paymentDocumentReleased'), remarks=document.getElementById('paymentReleaseRemarks'), error=document.getElementById('paymentVerificationError');
    if(orNo)orNo.value=''; if(date)date.value=localIsoDate(); if(released)released.checked=true; if(remarks)remarks.value=''; if(error){error.hidden=true;error.textContent='';}
    const previewBtn=document.getElementById('paymentPreviewDocumentBtn'), downloadBtn=document.getElementById('paymentDownloadDocumentBtn');
    const syncDocumentLinks=()=>{
        const issueDate=date?.value || localIsoDate();
        const base=`/requests/${encodeURIComponent(req.id)}/document.pdf`;
        if(previewBtn)previewBtn.href=`${base}?issue_date=${encodeURIComponent(issueDate)}`;
        if(downloadBtn){downloadBtn.href=`${base}?download=1&issue_date=${encodeURIComponent(issueDate)}`;downloadBtn.setAttribute('download','');}
    };
    date?.addEventListener('change',syncDocumentLinks); syncDocumentLinks();
    const validity=document.getElementById('paymentStickerValidityFields'), from=document.getElementById('paymentStickerValidFrom'), until=document.getElementById('paymentStickerValidUntil');
    const isVehicle=req.request_type==='Vehicle Sticker Application'; if(validity)validity.hidden=!isVehicle;
    if(from&&until){from.required=isVehicle;until.required=isVehicle; if(isVehicle){const today=new Date();from.value=localIsoDate();until.value=`${today.getFullYear()}-12-31`;if(new Date(until.value)<today)until.value=`${today.getFullYear()+1}-12-31`;}else{from.value='';until.value='';}}
    const sync=()=>{const releasing=released?.checked!==false; if(validity)validity.hidden=!(isVehicle&&releasing); if(from)from.required=isVehicle&&releasing; if(until)until.required=isVehicle&&releasing;};
    released?.addEventListener('change',sync,{once:false}); sync(); openModal('paymentVerificationModal'); setTimeout(()=>date?.focus(),0);
}
async function submitPaymentVerification(event){
    event.preventDefault(); const form=event.currentTarget, submitter=event.submitter;
    const date=document.getElementById('paymentVerifyDate'), released=document.getElementById('paymentDocumentReleased'), orNo=document.getElementById('paymentVerifyOR'), error=document.getElementById('paymentVerificationError');
    if(!date?.value){if(error){error.textContent='Select the actual cash payment date.';error.hidden=false;}date?.focus();return false;}
    if(!(orNo?.value||'').trim()){if(error){error.textContent='Enter the physical Official Receipt Number before recording the cash payment.';error.hidden=false;}orNo?.focus();return false;}
    if(error){error.hidden=true;error.textContent='';}
    const reqId=form.dataset.requestId || document.getElementById('paymentVerifyReqId')?.textContent || '';
    const amount=document.getElementById('paymentVerifyAmount')?.textContent || '';
    const releaseNow=released?.checked!==false;
    const ok=await showConfirmModal({title:releaseNow?'Confirm Payment & Release':'Confirm Payment Only',message:releaseNow?'Confirm that the cash payment was received AND the prepared document was physically handed to the homeowner during this face-to-face transaction?':'Confirm that the cash payment was received, but the document was NOT yet released?',confirmText:releaseNow?'Yes, Complete Transaction':'Record Payment Only',type:'primary',context:[{label:'Request ID',value:reqId},{label:'Amount',value:amount},{label:'Payment',value:'Cash'},{label:'Document Released',value:releaseNow?'Yes':'No'},{label:'Official Receipt No.',value:(orNo?.value||'').trim()}]});
    if(!ok)return false; if(!lockWorkflowSubmit(form,submitter))return false; window.NFHLoading?.show(releaseNow?'Recording payment and release…':'Recording payment…'); form.submit(); return false;
}
document.addEventListener('click',event=>{const btn=event.target.closest('[data-payment-request-id]');if(btn)openPaymentVerificationModal(btn.dataset.paymentRequestId);});
window.openPaymentVerificationModal=openPaymentVerificationModal; window.submitPaymentVerification=submitPaymentVerification;


// Compact Ready for Release workflow. The queue stays inside the Officer Overview;
// the modal keeps the issuance action connected without creating another full-page view.
function openIssueModal(reqId, homeowner, requestType, paidRelease=false){
    const form=document.getElementById('issueRequestForm');
    if(!form || !reqId){ showToast('Unable to open the issuance form.','error'); return; }
    form.action=(paidRelease?'/officer/complete_release/':'/officer/issue_request/')+encodeURIComponent(reqId);
    form.dataset.confirmed='false';
    const idEl=document.getElementById('issueRequestId');
    const homeownerEl=document.getElementById('issueHomeowner');
    const typeEl=document.getElementById('issueRequestType');
    const remarks=document.getElementById('issueReleaseRemarks');
    const validity=document.getElementById('stickerValidityFields');
    const validFrom=document.getElementById('stickerValidFrom');
    const validUntil=document.getElementById('stickerValidUntil');
    if(idEl) idEl.textContent=reqId;
    if(homeownerEl) homeownerEl.textContent=homeowner || '—';
    if(typeEl) typeEl.textContent=requestType || '—';
    if(remarks) remarks.value='';
    const isVehicle=requestType==='Vehicle Sticker Application';
    if(validity) validity.hidden=!isVehicle;
    [validFrom,validUntil].forEach(input=>{ if(input){ input.required=isVehicle; if(!isVehicle) input.value=''; } });
    if(isVehicle && validFrom && validUntil){
        const today=new Date();
        const yyyy=today.getFullYear();
        validFrom.value=today.toISOString().slice(0,10);
        validUntil.value=`${yyyy}-12-31`;
        if(new Date(validUntil.value)<today){ validUntil.value=`${yyyy+1}-12-31`; }
    }
    openModal('issueRequestModal');
    setTimeout(()=>remarks?.focus(),0);
}

document.addEventListener('click',event=>{
    const paid=event.target.closest('[data-paid-release-id]');
    if(paid){openIssueModal(paid.dataset.paidReleaseId,paid.dataset.issueHomeowner,paid.dataset.issueType,true);return;}
    const btn=event.target.closest('[data-issue-request-id]');
    if(!btn) return;
    openIssueModal(btn.dataset.issueRequestId,btn.dataset.issueHomeowner,btn.dataset.issueType,false);
});


async function nfhUploadAccountImage(input, endpoint, kind){
  const file=input?.files?.[0]; if(!file)return;
  const data=new FormData(); data.append('file',file);
  window.NFHLoading?.show(`Updating ${kind}…`);
  try{
    const res=await fetch(endpoint,{method:'POST',body:data}); const payload=await res.json();
    if(!res.ok||payload.status!=='success'){showToast(payload.message||`Unable to update ${kind}.`,'error');return;}
    showToast(payload.message||`${kind} updated.`,'success');
    if(kind==='profile picture'){
      const url=payload.image_url;
      const preview=document.getElementById('accountPhotoPreview'); if(preview)preview.innerHTML=`<img src="${url}?v=${Date.now()}" alt="Current profile picture">`;
      ['headerProfileImage','dropdownProfileImage'].forEach(id=>{let img=document.getElementById(id);if(img){img.src=`${url}?v=${Date.now()}`;}else{const parent=id.startsWith('header')?document.querySelector('.account-avatar'):document.querySelector('.account-dropdown-avatar');if(parent)parent.innerHTML=`<img src="${url}?v=${Date.now()}" alt="" class="account-avatar-img" id="${id}">`;}});
    }else{
      const preview=document.getElementById('accountESignPreview'); if(preview)preview.innerHTML=`<img src="${payload.preview_url}?v=${Date.now()}" alt="Current e-signature">`;
      const remove=document.getElementById('removeESignBtn'); if(remove)remove.hidden=false;
    }
  }catch(err){showToast(`Connection error while updating ${kind}.`,'error');}
  finally{window.NFHLoading?.hide();input.value='';}
}
async function nfhRemoveESignature(){
  const ok=typeof showConfirmModal==='function'?await showConfirmModal({title:'Remove E-Signature',message:'Remove your current e-signature? Future documents that require your role will not show a signature until you upload a new one.',confirmText:'Remove',type:'danger'}):window.confirm('Remove current e-signature?');
  if(!ok)return;
  window.NFHLoading?.show('Removing e-signature…');
  try{const res=await fetch('/api/account/esign',{method:'DELETE'});const data=await res.json();if(!res.ok||data.status!=='success'){showToast(data.message||'Unable to remove e-signature.','error');return;}showToast(data.message,'success');const preview=document.getElementById('accountESignPreview');if(preview)preview.innerHTML='<span class="esign-empty"><i class="fa-solid fa-signature"></i> No e-signature uploaded</span>';document.getElementById('removeESignBtn').hidden=true;}catch(e){showToast('Connection error while removing e-signature.','error');}finally{window.NFHLoading?.hide();}
}
function initAccountMediaControls(){
  const profile=document.getElementById('officerProfilePhotoInput')||document.getElementById('adminProfilePhotoInput');
  const esign=document.getElementById('officerESignInput')||document.getElementById('adminESignInput');
  if(profile&&!profile.dataset.ready){profile.dataset.ready='1';profile.addEventListener('change',()=>nfhUploadAccountImage(profile,'/api/profile/photo','profile picture'));}
  if(esign&&!esign.dataset.ready){esign.dataset.ready='1';esign.addEventListener('change',()=>nfhUploadAccountImage(esign,'/api/account/esign','e-signature'));}
  const remove=document.getElementById('removeESignBtn');if(remove&&!remove.dataset.ready){remove.dataset.ready='1';remove.addEventListener('click',nfhRemoveESignature);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initAccountMediaControls);else initAccountMediaControls();

async function saveOfficerAdminPassword(event){
    event?.preventDefault();
    const current=document.getElementById('accountCurrentPassword')?.value||'';
    const next=document.getElementById('accountNewPassword')?.value||'';
    const confirm=document.getElementById('accountConfirmPassword')?.value||'';
    if(!current||!next||!confirm){showToast('Complete all password fields.','warning');return false;}
    if(next.length<8){showToast('New password must be at least 8 characters.','warning');return false;}
    if(next!==confirm){showToast('New password and confirmation do not match.','warning');return false;}
    window.NFHLoading?.show('Updating password…');
    try{
        const response=await fetch('/api/settings/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:current,new_password:next,confirm_password:confirm})});
        const result=await response.json();
        if(!response.ok||result.status!=='success'){showToast(result.message||'Unable to update password.','error');return false;}
        document.getElementById('accountSecurityForm')?.reset(); closeModal('accountSecurityModal'); showToast('Password changed successfully.','success');
    }catch(err){console.error(err);showToast('Unable to update password right now.','error');}finally{window.NFHLoading?.hide();}
    return false;
}


document.addEventListener('click', event => {
    const group=event.target.closest('.homeowner-lookup-group');
    if(!group){ const results=document.getElementById('adjHomeownerResults'); if(results) results.hidden=true; }
});


/* Treasurer Monthly Dues Adjustment / Advance Payment nested tabs. */
(function(){
 const $=id=>document.getElementById(id), state={users:[],rate:0,chosen:null,key:null,pending:false,searchToken:0};
 const peso=n=>'₱'+Number(n).toLocaleString('en-PH',{maximumFractionDigits:0});
 const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
 const today=()=>{let x=new Date();return [x.getFullYear(),String(x.getMonth()+1).padStart(2,'0'),String(x.getDate()).padStart(2,'0')].join('-')};
 function switchPane(advance){$('nfhAdjustmentPane').hidden=advance;$('nfhAdvancePane').hidden=!advance;
  for(const [id,selected] of [['nfhAdjustmentTab',!advance],['nfhAdvanceTab',advance]]){$(id).classList.toggle('active',selected);$(id).setAttribute('aria-selected',String(selected));}}
 function renderUsers(){const sort=$('nfhAdvanceSort')?.value||'name',direction=$('nfhAdvanceOrder')?.value==='desc'?-1:1;const rows=state.users.slice().sort((a,b)=>{if(sort==='outstanding')return direction*(Number(a.outstanding)-Number(b.outstanding));if(sort==='block')return direction*String(a.block||'').localeCompare(String(b.block||''),undefined,{numeric:true})||direction*String(a.lot||'').localeCompare(String(b.lot||''),undefined,{numeric:true});return direction*String(a.name||'').localeCompare(String(b.name||''));});
 $('nfhAdvanceHomeowners').innerHTML=rows.length?rows.map(u=>`<tr><td>${esc(u.name)}</td><td>${esc(u.block)} / ${esc(u.lot)}</td><td>${peso(u.outstanding)}</td><td>${Number(u.coverage)||0} months</td><td><button type="button" class="btn btn-sm btn-primary" data-advance-user="${u.id}">Advance Payment</button></td></tr>`).join(''):'<tr><td colspan="5">No matching active homeowners.</td></tr>';}
 function calculate(){if(!state.chosen)return false;
  const month=$('nfhAdvanceStart').value,count=Number($('nfhAdvanceMonths').value);
  if(!month||!Number.isInteger(count)||count<1||count>60){$('nfhAdvanceNotice').textContent='Choose a valid future starting month and 1–60 months.';return false;}
  const [year,m]=month.split('-').map(Number),end=new Date(year,m-1+count,0);
  $('nfhAdvanceEnd').value=`${end.getFullYear()}-${String(end.getMonth()+1).padStart(2,'0')}`;
  const rate=Number(state.rate),gross=rate*count;
  if(!Number.isSafeInteger(gross)||gross<=0){$('nfhAdvanceNotice').textContent='Configured monthly dues must be a positive whole-peso amount.';return false;}
  $('nfhAdvanceGross').value=String(gross);
  const previousPayable=$('nfhAdvanceCash').value;
  $('nfhAdvanceCash').value=String(gross);
  if(!$('nfhAdvanceReceived').value||$('nfhAdvanceReceived').value===previousPayable) $('nfhAdvanceReceived').value=String(gross);
  $('nfhAdvanceNotice').textContent=`Covers ${count} future billing month(s). No online payment will be processed.`;
  return true;
 }
 function selectUser(id){state.chosen=state.users.find(u=>u.id===id);if(!state.chosen)return;
  $('nfhAdvanceSelected').textContent=`${state.chosen.name} — Block ${state.chosen.block}, Lot ${state.chosen.lot}`;
  $('nfhAdvanceOutstanding').value=peso(state.chosen.outstanding);$('nfhAdvanceRate').value=peso(state.rate);
  $('nfhAdvanceFormPanel').hidden=false;state.key=null;$('nfhAdvanceRaffleDistributed').checked=false;loadPromo();calculate();$('nfhAdvanceFormPanel').scrollIntoView({behavior:'smooth',block:'start'});}
 async function loadPromo(){
  if(!state.chosen)return;
  const target=$('nfhAdvancePromoSummary');
  try{const r=await fetch('/api/treasurer/advance-promo/'+state.chosen.id,{credentials:'same-origin'});
    const d=await r.json();if(!r.ok)throw Error(d.error||'Promo records unavailable');
    target.textContent=(d.awards||[]).length?(d.awards||[]).map(a=>`Year ${a.coverage_year}: ${a.raffle_tickets} raffle tickets; ${a.remaining} of ${a.certificate_credits} free certificates left (${a.used} used); verified ${a.payment_date}; raffle deadline ${a.deadline}; ${a.status}`).join(' | '):'No verified full-year January–December promotional award recorded.';
  }catch(e){target.textContent=e.message;}
 }
 async function load(){const token=++state.searchToken;const q=$('nfhAdvanceSearch').value.trim();$('nfhAdvanceHomeowners').innerHTML='<tr><td colspan="5">Searching active homeowners…</td></tr>';try{const r=await fetch('/api/treasurer/advance-dues/homeowners?search='+encodeURIComponent(q),{credentials:'same-origin'});const d=await r.json();if(!r.ok)throw Error(d.error||'Advance records unavailable');if(token!==state.searchToken)return;state.users=d.homeowners||[];state.rate=Number(d.rate);
  renderUsers();
 }catch(e){if(token===state.searchToken)$('nfhAdvanceHomeowners').innerHTML=`<tr><td colspan="5">${esc(e.message)}</td></tr>`;}}
 document.addEventListener('DOMContentLoaded',()=>{
  if(!$('nfhAdvanceTab'))return;
  $('nfhAdjustmentTab').addEventListener('click',()=>switchPane(false));$('nfhAdvanceTab').addEventListener('click',()=>{switchPane(true);load()});
  let advanceSearchTimer;$('nfhAdvanceSearch').addEventListener('input',()=>{clearTimeout(advanceSearchTimer);advanceSearchTimer=setTimeout(load,240)});
  ['nfhAdvanceSort','nfhAdvanceOrder'].forEach(id=>$(id).addEventListener('change',renderUsers));$('nfhAdvanceReset').addEventListener('click',()=>{$('nfhAdvanceSearch').value='';$('nfhAdvanceSort').value='name';$('nfhAdvanceOrder').value='asc';load();});
  $('nfhAdvanceHomeowners').addEventListener('click',e=>{const b=e.target.closest('[data-advance-user]');if(b)selectUser(Number(b.dataset.advanceUser))});
  let d=new Date();d.setMonth(d.getMonth()+1,1);$('nfhAdvanceStart').value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;$('nfhAdvanceStart').min=$('nfhAdvanceStart').value;
  $('nfhAdvanceDate').value=today();$('nfhAdvanceDate').max=today();
  ['nfhAdvanceStart','nfhAdvanceMonths'].forEach(id=>$(id).addEventListener('change',calculate));
  $('nfhAdvanceForm').addEventListener('submit',async e=>{e.preventDefault();if(state.pending||!state.chosen||!calculate())return;
    if($('nfhAdvanceReceived').value!==$('nfhAdvanceCash').value){
       $('nfhAdvanceNotice').textContent='Cash received must equal the full advance dues amount.';return;}
    const yes=await showConfirmModal({title:'Record Verified Advance Payment',message:'Confirm that the Treasurer has actually received this payment in person.',confirmText:'Record Payment',type:'primary',context:[{label:'Homeowner',value:state.chosen.name},{label:'Gross',value:peso($('nfhAdvanceGross').value)},{label:'Cash Received',value:peso($('nfhAdvanceReceived').value)}]});
    if(!yes)return;
    if(!state.key)state.key=(crypto.randomUUID?.()||String(Date.now())+'-'+Math.random().toString(36).slice(2));
    state.pending=true;$('nfhAdvanceSubmit').disabled=true;$('nfhAdvanceNotice').textContent='Recording verified payment…';
    try{const r=await fetch('/api/treasurer/advance-dues',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.chosen.id,start_month:$('nfhAdvanceStart').value,months:Number($('nfhAdvanceMonths').value),cash_received:$('nfhAdvanceReceived').value,method:$('nfhAdvanceMethod').value,reference:$('nfhAdvanceReference').value,payment_date:$('nfhAdvanceDate').value,remarks:$('nfhAdvanceRemarks').value,raffle_distributed:$('nfhAdvanceRaffleDistributed').checked,request_key:state.key})});const d=await r.json();if(!r.ok)throw Error(d.error||'Payment was not saved.');$('nfhAdvanceNotice').textContent=`Payment recorded. Receipt transaction #${d.id}. Covered: ${d.covered?.join(', ')||'previously recorded'}.`;showToast('Advance payment recorded successfully.','success');state.key=null;$('nfhAdvanceRaffleDistributed').checked=false;await load();await loadPromo();
    }catch(err){$('nfhAdvanceNotice').textContent=err.message;showToast(err.message,'error')}finally{state.pending=false;$('nfhAdvanceSubmit').disabled=false;}
  });
 });
})();
