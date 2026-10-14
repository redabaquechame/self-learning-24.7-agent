const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('ui.html','utf8');
const source=html.slice(html.indexOf('async function loadApprovals(){'),html.indexOf('async function decideApproval('));
const card={style:{}},body={innerHTML:'',querySelectorAll:()=>[]};
const pending=[];
const context={S:{sel:'owned'},panelToken:'original-token',document:{getElementById:id=>id==='apCard'?card:body},
    esc:x=>String(x??''),api:()=>new Promise(resolve=>pending.push(resolve))};
vm.createContext(context);vm.runInContext('let approvalsLoadGeneration=0;'+source,context);
const record={id:'owned-source',server:'screen_tutor',tool:'share_source_for_explanation',source_can_decide:true,args:{scope:{source:{display_name:'Owned source'}}}};
(async()=>{
 if(process.argv[2]==='race'){
  const old=context.loadApprovals();const fresh=context.loadApprovals();
  pending[1]({pending:[{...record,source_approval_state:'RETIRED_OR_UNAVAILABLE'}],history:[]});await fresh;
  pending[0]({pending:[{...record,source_approval_state:'CURRENT_PENDING'}],history:[]});await old;
  assert(!body.innerHTML.includes('Approve sharing'),'older pending response restored actionable grant');
 }else if(['expert','token','dom'].includes(process.argv[2])){
  const load=context.loadApprovals();
  if(process.argv[2]==='expert')context.S.sel='other';
  if(process.argv[2]==='token')context.panelToken='replacement';
  if(process.argv[2]==='dom')context.document.getElementById=()=>({});
  pending.shift()({pending:[{...record,source_approval_state:'CURRENT_PENDING'}],history:[]});await load;
  assert.equal(body.innerHTML,'','changed context received stale approval actions');
 }else{
  const first=context.loadApprovals();pending.shift()({pending:[],history:[{...record,source_approval_state:'CURRENT_APPROVED'}]});await first;
  assert(body.innerHTML.includes('Withdraw sharing permission'));
  const retry=context.loadApprovals();pending.shift()({error:'network unavailable'});await retry;
  assert.equal(card.style.display,'block','failed refresh hid current permission card');
  assert(body.innerHTML.includes('network unavailable')&&body.innerHTML.includes('Refresh'),'failed refresh provided no explanation/retry');
  assert(!body.innerHTML.includes('Withdraw sharing permission'),'failed read leaves stale action enabled');
 }
 console.log('PASS actual approval loader '+process.argv[2]);
})().catch(error=>{console.error(error);process.exitCode=1});
