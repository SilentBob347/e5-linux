// Execute the real LuCI view with DOM/RPC fixtures. Only synthetic identities.
const fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../luci-app-t551m/htdocs/luci-static/resources/view/mu300/nv.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(lang='zh',valid=true,busy=false,options={}){
 const state={modal:[],overlays:[],requests:[],timers:[],status:{ok:true,initialized:true,validated:valid,work_validated:valid,
  original_validated:valid,can_import:valid,can_export:valid,same:false,fixed_equal:false,comparison:{items:2,identity_items:1},
  imei:{original:{sim1:'123456789012345',sim2:'987654321098765'},working:{sim1:'111111111111111',sim2:'222222222222222'}}},
  backups:{ok:true,entries:[{id:'20261025-123456-012345abcdef',path:'/etc/e5-nv/backups/20261025-123456-012345abcdef',bytes:8192,complete:true,protected:false}],total_bytes:8192}};
 if(busy)Object.assign(state.status,{busy:true,can_import:false,can_export:false,job:{state:'running',phase:'backup'}});
 function E(tag,attrs={},children=[]){return {tag,...attrs,disabled:Object.hasOwn(attrs,'disabled'),children:Array.isArray(children)?children:[children],textContent:'',value:attrs.value||'',events:{},replaceChildren(...nodes){this.children=nodes;},addEventListener(event,fn){this.events[event]=fn;},focus(){},submit(){state.downloadForm=this;},remove(){state.overlays=state.overlays.filter(n=>n!==this);}};}
 const document={body:{style:{overflow:'auto'},appendChild(node){state.overlays.push(node);}},activeElement:{isConnected:true,focus(){state.focusRestored=true;}}};state.document=document;
 const rpc={getSessionID:()=> 'fixture-session',declare:spec=>(...args)=>{state.requests.push({method:spec.method,args});
  if(['status','backups'].includes(spec.method))assert.equal(spec.nobatch,true);
  if(options.defer===spec.method)return new Promise(resolve=>{state.resolve=resolve;});
  if(state.fail===spec.method)return Promise.resolve({ok:false,error:state.error||'nv_backup_space'});
  if(spec.method==='status')return Promise.resolve(state.status);
  if(spec.method==='backups')return Promise.resolve(state.backups);
  if(spec.method==='preview')return Promise.resolve({ok:true,token:'verified',conflict:true});
  if(spec.method==='compress_backup')return Promise.resolve({ok:true,job:{id:'compression',state:'queued',operation:'compress_backup'}});
  if(spec.method==='delete_backup'){state.backups={ok:true,entries:[],total_bytes:0};return Promise.resolve({ok:true});}
  return Promise.resolve({ok:true,job:{id:'test',state:'queued'}});
 }};
 const M={uiLanguage:()=>lang,injectCss(){state.themed=true;},localizeMenu(){state.localized=true;}};
 const ui={showModal(title,nodes){state.modal=nodes;state.title=title;},hideModal(){state.modal=[];}};
 const view=new Function('view','rpc','ui','M','E','setTimeout','clearTimeout','document','L',source)(
  {extend:x=>x},rpc,ui,M,E,(fn,ms)=>{const item={fn,ms};state.timers.push(item);return item;},item=>{if(item)item.cancelled=true;},document,{env:{cgi_base:"/cgi-bin"}});
 state.load=view.load;const root=view.render(options.initial===false?null:state.status),all=node=>!node||typeof node!=='object'?[]:[node,...node.children.flatMap(all)];
 state.root=root;state.nodes=()=>[...all(root),...state.modal.flatMap(all),...state.overlays.flatMap(all)];state.button=label=>state.nodes().find(n=>n.tag==='button'&&n.children.includes(label));
 state.text=()=>state.nodes().map(n=>n.textContent+' '+n.children.filter(x=>typeof x==='string').join(' ')).join(' ');
 state.confirm=async()=>{const input=state.nodes().find(n=>n.tag==='input'),button=state.nodes().filter(n=>n.tag==='button').at(-1);
  assert(button.disabled);input.value='YES';input.events.input();assert(button.disabled);input.value='yes';input.events.input();assert.equal(button.disabled,false);await button.click();await flush();};
 state.poll=async()=>{const timer=state.timers.filter(t=>!t.cancelled).at(-1);assert(timer);await timer.fn();await flush();};state.unload=()=>view.unload();return state;
}
(async()=>{
 for(const [lang,title,importLabel,exportLabel,show,hide] of [
  ['zh','基带NV设置','原机 NV → OpenWrt','OpenWrt NV → 原机','显示 IMEI','隐藏 IMEI'],
  ['en','Baseband NV settings','Original NV → OpenWrt','OpenWrt NV → original','Show IMEIs','Hide IMEIs'],
  ['tr','Temel bant NV ayarları','Orijinal NV → OpenWrt','OpenWrt NV → orijinal','IMEI göster','IMEI gizle']]){
  for(const [dir,label] of [['from-original',importLabel],['to-original',exportLabel]]){
   const s=fixture(lang);await flush();assert(s.themed&&s.localized);assert(s.text().includes(title));
   assert.equal(s.button(show).disabled,false);assert(!s.text().includes('123456789012345'));assert(!s.text().includes('111111111111111'));
   await s.button(show).click();assert(s.text().includes('123456789012345'));assert(s.text().includes('111111111111111'));
   await s.button(hide).click();assert(!s.text().includes('123456789012345'));
   await s.button(label).click();assert.equal(s.requests.filter(r=>r.method==='sync').length,0);
   assert(s.nodes().some(n=>n.tag==='input'));await s.confirm();
   assert.deepEqual(s.requests.find(r=>r.method==='sync').args,[dir,'verified','yes',true]);
   assert(s.button(importLabel).disabled);assert(s.button(exportLabel).disabled);
   assert.equal(s.overlays.length,1);assert.equal(s.document.body.style.overflow,'hidden');
   let prevented=false;s.overlays[0].events.keydown({key:'Escape',preventDefault(){prevented=true;}});assert(prevented);assert.equal(s.overlays.length,1);
   s.status={...s.status,busy:true,job:{state:'running',phase:'stop'}};await s.poll();
   assert(s.text().includes(lang==='zh'?'正在停止蜂窝服务…':lang==='tr'?'Hücresel hizmetler durduruluyor…':'Stopping cellular services…'));
   s.status={...s.status,busy:false,can_import:true,can_export:true,job:{state:'complete'},last_sync:{time:1,ok:true,reboot_required:true,direction:dir}};
   await s.poll();assert.equal(s.button(importLabel).disabled,false);assert.equal(s.button(exportLabel).disabled,false);
   assert.equal(s.overlays.length,0);assert.equal(s.document.body.style.overflow,'auto');assert(s.focusRestored);
   assert(s.text().includes(lang==='zh'?'同步完成，需要重启生效。':lang==='tr'?'Eşitleme tamamlandı. Etkinleştirmek için yeniden başlatın.':'Synchronization complete. Reboot to activate.'));
   s.unload();assert(s.timers.every(t=>t.cancelled));
  }
 }
 const invalid=fixture('en',false);assert(invalid.button('Original NV → OpenWrt').disabled);assert(invalid.button('OpenWrt NV → original').disabled);
 const running=fixture('en',true,true);await flush();assert(running.button('Delete backup').disabled);assert(running.timers.length);
 assert.equal(running.overlays.length,1);running.unload();assert.equal(running.overlays.length,0);const calls=running.requests.length;await running.timers.at(-1).fn();assert.equal(running.requests.length,calls);
 const deleting=fixture('en');await flush();await deleting.button('Delete backup').click();assert(!deleting.requests.some(r=>r.method==='delete_backup'));
 await deleting.confirm();assert.deepEqual(deleting.requests.find(r=>r.method==='delete_backup').args,['20261025-123456-012345abcdef','yes']);assert(deleting.text().includes('No backups'));
 const protectedBackup=fixture('en');protectedBackup.backups.entries[0].protected=true;await flush();assert(protectedBackup.button('In use by recovery').disabled);
 const failure=fixture('zh');failure.fail='preview';await failure.button('OpenWrt NV → 原机').click();assert(failure.text().includes('备份空间不足'));assert(!failure.text().includes('nv_backup_space'));assert(failure.modal.length);assert(!failure.overlays.length);
 const failedJob=fixture('en',true,true);failedJob.status={...failedJob.status,busy:false,job:{state:'failed',error:'nv_import_failed'}};await failedJob.poll();assert(!failedJob.overlays.length);assert(failedJob.text().includes('Operation did not complete'));
 const compressing=fixture('en');compressing.backups.entries[0].can_compress=true;await flush();await compressing.button('Compress backup').click();
 assert(!compressing.requests.some(r=>r.method==='compress_backup'));await compressing.confirm();
 assert.deepEqual(compressing.requests.find(r=>r.method==='compress_backup').args,['20261025-123456-012345abcdef','yes']);
 assert(compressing.text().includes('Compressing backup'));assert.equal(compressing.overlays.length,1);
 compressing.status={...compressing.status,busy:false,job:{state:'complete',operation:'compress_backup',result:{backup_compressed:true}}};await compressing.poll();
 assert(!compressing.overlays.length);assert(compressing.text().includes('Backup compressed; contents are unchanged.'));
 const manual=fixture('en');await flush();await manual.button('Back up now').click();
 assert.deepEqual(manual.requests.find(r=>r.method==='manual_backup').args,[]);assert(manual.overlays.length);assert(!manual.nodes().some(n=>n.tag==='input'));
 manual.status={...manual.status,busy:false,job:{id:'test',state:'complete',operation:'manual_backup',result:{manual_backup:true}}};await manual.poll();
 assert(manual.modal.length);assert(manual.title==='Operation complete');assert(!manual.overlays.length);
 const download=fixture('en');await flush();await download.button('Download').click();
 assert.deepEqual(download.requests.find(r=>r.method==='prepare_download').args,['20261025-123456-012345abcdef']);assert(download.overlays.length);
 const file={path:'/tmp/e5-nv-download/export-'+ 'a'.repeat(24)+'.tar.gz',filename:'e5-nv-backup-manual-20261025-123456-012345abcdef.tar.gz'};
 download.status={...download.status,busy:false,job:{id:'test',state:'complete',operation:'prepare_download',result:{download:file}}};await download.poll();
 assert(download.modal.length);assert(!download.overlays.length);assert.equal(download.downloadForm.action,'/cgi-bin/cgi-download');
 assert.deepEqual(download.downloadForm.children.map(n=>[n.name,n.value]),[['sessionid','fixture-session'],['path',file.path],['filename',file.filename]]);
 const form=download.downloadForm;await download.button('Refresh').click();assert.equal(download.downloadForm,form);
 const noticeIndex=download.root.children.findIndex(n=>n.class==='mud-nv-notice');assert(noticeIndex>0);assert.equal(download.root.children[noticeIndex+1].tag,'div');
 const manualFailure=fixture('en');await flush();manualFailure.fail='manual_backup';await manualFailure.button('Back up now').click();assert(manualFailure.modal.length);assert(!manualFailure.overlays.length);
 const failedExport=fixture('en');await flush();await failedExport.button('Download').click();failedExport.status={...failedExport.status,busy:false,job:{id:'test',state:'failed',operation:'prepare_download',error:'nv_backup_space'}};await failedExport.poll();assert(failedExport.modal.length);assert(!failedExport.downloadForm);
 const duplicate=fixture('en');const click=duplicate.button('Original NV → OpenWrt').click;await Promise.all([click(),click()]);assert.equal(duplicate.requests.filter(r=>r.method==='preview').length,1);
 const preparation=fixture('en',true,false,{defer:'preview'});const preparing=preparation.button('OpenWrt NV → original').click();
 assert(preparation.text().includes('Preparing synchronization…'));assert(!preparation.text().includes('Synchronizing baseband NV'));
 assert(!preparation.requests.some(r=>r.method==='sync'));preparation.resolve({ok:true,token:'prepare-only',conflict:false});await preparing;
 assert(!preparation.overlays.length);assert(preparation.modal.length);
 const slowStatus=fixture('en',true,false,{initial:false,defer:'status'});
 assert(slowStatus.text().includes('Baseband NV settings'));assert(slowStatus.text().includes('Loading…'));
 assert(!slowStatus.text().includes('Not initialized'));assert(!slowStatus.text().includes('Operation did not complete'));
 const started=slowStatus.requests.length;assert.equal(await slowStatus.load(),null);assert.equal(slowStatus.requests.length,started);
 await flush();assert(slowStatus.text().includes('20261025-123456-012345abcdef')); // backups do not wait for status
 assert(slowStatus.button('Original NV → OpenWrt').disabled);slowStatus.resolve(slowStatus.status);await flush();
 assert.equal(slowStatus.button('Original NV → OpenWrt').disabled,false);assert.equal(slowStatus.button('Refresh').disabled,false);
 const slowBackups=fixture('en',true,false,{initial:false,defer:'backups'});await flush();
 assert(slowBackups.text().includes('Initialized'));assert.equal(slowBackups.button('Original NV → OpenWrt').disabled,false);
 assert(slowBackups.text().includes('Loading…'));slowBackups.resolve(slowBackups.backups);await flush();assert(!slowBackups.text().includes('Loading…'));
 const leave=fixture('en',true,false,{initial:false,defer:'status'});await flush();const oldText=leave.text();leave.unload();leave.resolve(leave.status);await flush();assert.equal(leave.text(),oldText);
 console.log('PASS: three languages; both confirmed directions; four masked/revealed IMEIs; theme; async completion; duplicate protection; localized failures; backup deletion and recovery protection');
 console.log('PASS: immediate view load; independent delayed status/backups; loading placeholders; safe actions; late responses ignored on unload');
 console.log('PASS: global sync overlay; real phase updates; Escape blocked; completion/failure/unload cleanup; scroll and focus restoration');
})().catch(error=>{console.error(error);process.exitCode=1;});
