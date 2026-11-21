/* B12 officer tasks: viewing only. Source workflows perform all decisions. */
(() => {
  'use strict';
  const panel = document.getElementById('officer-tasks-tab');
  if (!panel) return;
  const $ = s => panel.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let page=1;
  let taskRows=[];
  const state= $('#ot-message');
  const view = $('#ot-rows');
  const size = $('#ot-size');
  function formatDate(s){return s ? esc(s) : '—';}
  async function load(){
    state.textContent='Loading assigned tasks…';
    const params=new URLSearchParams({page:String(page),size:size.value,q:$('#ot-search').value.trim(),status:$('#ot-status').value,type:$('#ot-type').value,priority:$('#ot-priority').value});
    try {
      const res=await fetch('/api/officer/my-tasks?'+params,{credentials:'same-origin',headers:{Accept:'application/json'}});
      if (!(res.headers.get('content-type')||'').includes('application/json')) throw new Error('Session or service unavailable. Sign in again.');
      const data=await res.json();
      if (!res.ok) throw new Error(data.error||'Unable to load tasks.');
      taskRows=data.tasks||[];
      page=data.page||1;
      const counts=data.counters||{};
      for(const [name,key] of [['pending','pending'],['progress','in_progress'],['high','high_priority'],['overdue','overdue'],['completed','completed']]){
        const el=panel.querySelector('[data-ot-counter="'+name+'"]'); if(el) el.textContent=counts[key]||0;
      }
      view.innerHTML=taskRows.map(t=>`<tr><td>${esc(t.id)}</td><td>${esc(t.task_type)}</td><td>${esc(t.source_type)} #${esc(t.source_id)}</td><td>${esc(t.assigned_role)}</td><td>${esc(t.priority)}</td><td>${formatDate(t.created_at)}</td><td>${formatDate(t.due_at)}</td><td>${esc(t.status)}</td><td><a class="btn btn-sm" href="${esc(t.source_link)}">Open Record</a></td></tr>`).join('') || '<tr><td colspan="9" style="text-align:center">No assigned tasks match these filters.</td></tr>';
      const start=data.total ? (page-1)*data.size+1 : 0;
      const end=Math.min(page*data.size,data.total);
      state.textContent=`Showing ${start}–${end} of ${data.total} tasks`;
      $('#ot-prev').disabled=page<=1;
      $('#ot-next').disabled=end>=data.total;
    } catch (e) {
      view.innerHTML='<tr><td colspan="9">Task records could not be loaded.</td></tr>';
      state.textContent=e.message;
      $('#ot-prev').disabled=true;$('#ot-next').disabled=true;
    }
  }
  let typing;
  $('#ot-search').addEventListener('input',()=>{clearTimeout(typing);typing=setTimeout(()=>{page=1;load()},300)});
  ['ot-status','ot-type','ot-priority','ot-size'].forEach(id=>$('#'+id).addEventListener('change',()=>{page=1;load()}));
  $('#ot-reset').addEventListener('click',()=>{$('#ot-search').value='';['ot-status','ot-type','ot-priority'].forEach(id=>$('#'+id).value='');size.value='10';page=1;load()});
  $('#ot-prev').addEventListener('click',()=>{page=Math.max(1,page-1);load()});
  $('#ot-next').addEventListener('click',()=>{page++;load()});
  $('#ot-refresh').addEventListener('click',load);
  let loaded=false;
  const nav=document.querySelector('.sidebar-nav [data-tab="officer-tasks-tab"]');
  if(nav)nav.addEventListener('click',()=>{loaded=true;load()});
  if(location.hash==='#officer-tasks'){loaded=true;load()}
  const workNav=document.querySelector('[data-tab="officer-workload-tab"]');
  const workRows=document.getElementById('ot-workload-rows');
  const workMessage=document.getElementById('ot-workload-message');
  async function loadWorkload(){
    if(!workRows)return;
    workMessage.textContent='Loading workload…';
    try {
      const response=await fetch('/api/officer/workload',{credentials:'same-origin',headers:{Accept:'application/json'}});
      if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('Session expired or server unavailable.');
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Workload unavailable.');
      workRows.innerHTML=(data.workload||[]).map(w=>`<tr><td>${esc(w.assigned_role)}</td><td>${esc(w.total)}</td><td>${esc(w.pending||0)}</td><td>${esc(w.in_progress||0)}</td><td>${esc(w.completed||0)}</td><td>${esc(w.overdue||0)}</td><td>${esc(w.escalated||0)}</td></tr>`).join('')||'<tr><td colspan="7">No workload records.</td></tr>';
      workMessage.textContent='Updated operational task counts.';
    } catch(e){workMessage.textContent=e.message;}
  }
  if(workNav)workNav.addEventListener('click',loadWorkload);
  const workRefresh=document.getElementById('ot-workload-refresh');
  if(workRefresh)workRefresh.addEventListener('click',loadWorkload);
  if(location.hash==='#officer-workload')loadWorkload();
  // Refresh when revisiting the tab; never simulate completion from queue.
})();
