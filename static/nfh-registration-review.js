let nfhRegistrationState=null;
function nfhCloseRegistrationReview(){document.getElementById('nfh-registration-modal').style.display='none';nfhRegistrationState=null;}
async function nfhRegistrationReview(id,action){
 const modal=document.getElementById('nfh-registration-modal'),err=document.getElementById('nfh-reg-error');
 err.textContent='';modal.style.display='block';document.getElementById('nfh-reg-details').textContent='Loading latest registration details…';
 document.getElementById('nfh-reg-reason').value='';nfhRegistrationState=null;
 try{
  const r=await fetch(`/admin/homeowner-verification/${id}/review`,{credentials:'same-origin'}), data=await r.json();
  if(!r.ok)throw Error(data.message||'Cannot load registration');
  nfhRegistrationState={id,action};const u=data.homeowner;
  document.getElementById('nfh-reg-title').textContent=action==='verify'?'Final Homeowner Account Verification':'Reject Homeowner Registration';
  document.getElementById('nfh-reg-reason-wrap').style.display=action==='reject'?'block':'none';
  document.getElementById('nfh-reg-confirm').textContent=action==='verify'?'Confirm Verification':'Confirm Rejection';
  const fields=[['First Name',u.first_name],['Middle Name',u.middle_name],['Last Name',u.last_name],['Suffix',u.suffix],['Gender',u.gender],['Date of Birth',u.dob],['Civil Status',u.civil_status],['Block',u.block],['Lot',u.lot],['Complete Address',u.address_line],['Homeowner ID',u.homeowner_public_id],['Email Address',u.email],['Mobile Number',u.mobile],['Household',u.household],['Registration Date',u.created_at],['Registration Status',u.verification_status]];
  const div=document.getElementById('nfh-reg-details');div.replaceChildren();
  for(const [label,value] of fields){const item=document.createElement('div');item.style.padding='9px';item.style.background=['Block','Lot','Homeowner ID'].includes(label)?'#E2EBE2':'#F4F9F4';item.style.borderRadius='6px';const strong=document.createElement('strong');strong.textContent=label;const val=document.createElement('div');val.textContent=value??'—';item.append(strong,val);div.append(item);}
 }catch(e){err.textContent=e.message;}
}
async function nfhSubmitRegistrationReview(){
 const st=nfhRegistrationState;if(!st)return;
 const remarks=document.getElementById('nfh-reg-reason').value.trim(),err=document.getElementById('nfh-reg-error');
 if(st.action==='reject'&&(remarks.length<12||remarks.length>1000)){err.textContent='Provide meaningful remarks (12–1000 characters).';return;}
 const btn=document.getElementById('nfh-reg-confirm');btn.disabled=true;err.textContent='';
 try{const data=new URLSearchParams({action:st.action,final_confirmation:'yes',remarks});
 const csrf=document.querySelector('meta[name="csrf-token"]')?.content;
 const r=await fetch(`/admin/homeowner-verification/${st.id}`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded',...(csrf?{'X-CSRF-Token':csrf}:{})},body:data,credentials:'same-origin'});
 const result=await r.json();if(!r.ok)throw Error(result.message||'Request failed');nfhCloseRegistrationReview();window.location.reload();
 }catch(e){err.textContent=e.message;}finally{btn.disabled=false;}
}
