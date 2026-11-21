/* Shared safety guard: prevents repeat in-flight submissions in this browser tab.
   Authoritative uniqueness must additionally be enforced by the application/database. */
(()=>{
  'use strict';
  const nativeFetch=window.fetch.bind(window), pending=new Set();
  const guarded=[/\/api\/treasurer\/import\/(preview|commit)(?:\?|$)/,
    /\/api\/treasurer\/historical-unpaid\/pay(?:\?|$)/,
    /\/api\/treasurer\/(?:advance-dues|settle-dues|adjustment)(?:\?|$)/,
    /\/api\/admin\/(?:import|.*(?:verify|reject))/, 
    /\/api\/.*(?:approve|reject|approval|verification|payment|release)(?:[/?]|$)/];
  function eligible(url,options){const method=String(options?.method||'GET').toUpperCase();
    return method==='POST' && guarded.some(re=>re.test(url));}
  window.fetch=function(resource,options){
    const url=String(typeof resource==='string'?resource:resource?.url||'');
    if(!eligible(url,options))return nativeFetch(resource,options);
    const key=url+'|'+(typeof options?.body==='string'?options.body:'upload-or-form');
    if(pending.has(key))return Promise.reject(new Error('This action is already processing.'));
    pending.add(key);
    const title=/import/.test(url)?'Importing or validating records…':/payment|pay|dues|adjustment/.test(url)?'Saving payment information…':'Processing request…';
    window.NFHLoading?.show(title,'Please wait until the current action finishes.');
    return nativeFetch(resource,options).finally(()=>{
      pending.delete(key);
      if(!pending.size)window.NFHLoading?.hide();
    });
  };
  document.addEventListener('click',e=>{
    const link=e.target.closest('a[href*="/pdf"]');
    if(!link||link.getAttribute('aria-disabled')==='true')return;
    window.NFHLoading?.show('Generating report…','Preparing your PDF document.');
    window.setTimeout(()=>window.NFHLoading?.hide(),1800);
  },true);
})();
