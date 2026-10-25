'use strict';
'require view';
'require rpc';
'require ui';
'require mu300.common as M';

const words={
 title:['基带NV设置','Baseband NV settings','Temel bant NV ayarları'],
 loading:['正在读取…','Loading…','Yükleniyor…'],
 manualBackup:['手动备份','Back up now','Şimdi yedekle'],makingBackup:['正在生成 NV 备份','Creating NV backup','NV yedeği oluşturuluyor'],manualDone:['备份已完成，可在备份列表中下载。','Backup complete. Download it from the backup list.','Yedek tamamlandı. Yedek listesinden indirin.'],manualKind:['手动备份','Manual backup','Elle yedekleme'],download:['下载','Download','İndir'],preparingDownload:['正在准备下载','Preparing download','İndirme hazırlanıyor'],exporting:['正在打包并校验备份…','Packaging and verifying backup…','Yedek paketleniyor ve doğrulanıyor…'],downloadStarted:['备份下载已开始。','Backup download started.','Yedek indirmesi başladı.'],operationDone:['操作完成','Operation complete','İşlem tamamlandı'],operationFailed:['操作失败','Operation failed','İşlem başarısız'],close:['关闭','Close','Kapat'],deleted:['备份已删除。','Backup deleted.','Yedek silindi.'],
 skipped:['以下文件的更改尚无法验证，本次不写回：','Changes in these files cannot yet be verified; they will not be written:','Bu dosyalardaki değişiklikler henüz doğrulanamıyor; yazılmayacak:'],partialDone:['可验证文件已处理；未验证文件保持不变。','Verified files processed; unverified files remain unchanged.','Doğrulanan dosyalar işlendi; doğrulanamayanlar değişmedi.'],writeScope:['本次写回文件','Files to write back','Geri yazılacak dosyalar'],'write-calibration':['正在写入并回读校准文件…','Writing and verifying calibration files…','Kalibrasyon dosyaları yazılıyor ve doğrulanıyor…'],
 compressed:['无损压缩','Lossless gzip','Kayıpsız gzip'],rawSize:['原始大小','Original size','Orijinal boyut'],compress:['压缩备份','Compress backup','Yedeği sıkıştır'],compressing:['正在压缩备份','Compressing backup','Yedek sıkıştırılıyor'],compressDone:['备份压缩完成，内容未改变。','Backup compressed; contents are unchanged.','Yedek sıkıştırıldı; içerik değişmedi.'],compressNote:['仅无损压缩此备份并移除重复副本；校验解压后的完整内容，不修改当前工作 NV 或原机分区。','Losslessly compress this backup and remove duplicate copies after verifying all decompressed bytes. Live working NV and original partitions are unchanged.','Bu yedeği kayıpsız sıkıştırır, açılan veriyi doğrular ve yinelenen kopyaları kaldırır. Etkin çalışma NV ve orijinal bölümler değişmez.'],detailUnavailable:['内部条目暂无法解析，完整文件仍可校验和同步。','Item details are unavailable; full files can still be verified and synchronized.','Öğe ayrıntıları kullanılamıyor; tam dosyalar doğrulanıp eşitlenebilir.'],
 syncing:['正在同步基带 NV','Synchronizing baseband NV','Temel bant NV eşitleniyor'],
 keepPower:['请保持供电，完成前请勿关闭页面。','Keep power connected and leave this page open until completion.','Gücü bağlı tutun ve işlem bitene kadar bu sayfayı açık bırakın.'],
 intro:['对比两边身份和校验状态，确认方向后同步。系统更新会自动保留工作 NV。','Compare identities and validation before choosing a direction. System updates preserve working NV automatically.','Yön seçmeden önce kimlik ve doğrulamayı karşılaştırın. Sistem güncellemeleri çalışma NV verisini korur.'],
 original:['原机 NV','Original NV','Orijinal NV'],working:['OpenWrt 工作 NV','OpenWrt working NV','OpenWrt çalışma NV'],
 import:['原机 NV → OpenWrt','Original NV → OpenWrt','Orijinal NV → OpenWrt'],export:['OpenWrt NV → 原机','OpenWrt NV → original','OpenWrt NV → orijinal'],
 originalNote:['原机分区，只读保护','Original partitions, write protected','Orijinal bölümler, yazma korumalı'],
 workingNote:['基带使用的隔离工作副本','Isolated copies used by the modem','Modemin kullandığı yalıtılmış kopyalar'],
 initialized:['已初始化','Initialized','Başlatıldı'],uninitialized:['未初始化','Not initialized','Başlatılmadı'],
 valid:['校验通过','Validated','Doğrulandı'],invalid:['校验不可用','Validation unavailable','Doğrulama kullanılamıyor'],
 unavailable:['未读取到','Not available','Kullanılamıyor'],show:['显示 IMEI','Show IMEIs','IMEI göster'],hide:['隐藏 IMEI','Hide IMEIs','IMEI gizle'],
 identity:['显示当前基带固件槽的 IMEI；完整写回将包含工作 NV 中的 IMEI、身份签名及校准数据。','IMEIs shown are from the current modem firmware slot. Full writeback includes working NV identities, signatures and calibration.','Gösterilen IMEI geçerli modem donanım yazılımı yuvasına aittir. Tam geri yazma çalışma NV kimliklerini, imzalarını ve kalibrasyonu içerir.'],
 differences:['差异概览','Differences','Farklar'],same:['固定 NV 文件一致','Fixed NV files match','Sabit NV dosyaları aynı'],different:['固定 NV 文件不同','Fixed NV files differ','Sabit NV dosyaları farklı'],
 items:['当前槽业务项差异','Business changes in current slot','Geçerli yuvadaki iş öğesi farkları'],identities:['身份条目差异','Identity differences','Kimlik farkları'],
 compareNote:['文件不同不代表校准损坏：运行时数据、代次、填充和主备配对均可能变化。','Different files do not imply damaged calibration: runtime data, generations, padding and redundant copies may differ.','Dosya farkları bozuk kalibrasyon anlamına gelmez: çalışma verisi, nesil, dolgu ve yedek kopyalar değişebilir.'],
 importNote:['从 Android 使用的原机 NV 重新导入，覆盖完整工作副本，包括其 IMEI；原机分区不变。','Import the original NV used by Android, replacing the complete working copies including their IMEIs. Original partitions stay unchanged.','Android orijinal NV verisini, IMEI dahil çalışma kopyalarının yerine aktarır. Orijinal bölümler değişmez.'],
 exportNote:['完整写回固定及运行时 NV；delta/calinv 经本机来源或兼容格式验证后也可写回。包含各自 IMEI、身份签名、校准、文件头及尾部。无法验证的文件会列出并跳过，确认后才执行。','Fully write back fixed and runtime NV. Delta/calinv are included when verified against this device’s original provenance or a compatible format. Identities, calibration, headers and tails are included. Unverified files are listed and skipped before confirmation.','Sabit ve çalışma NV tamamen geri yazılır. Delta/calinv bu cihazın orijinal kaynağı veya uyumlu biçimle doğrulandığında dahil edilir. Kimlik, kalibrasyon, başlık ve son veriler dahil edilir. Doğrulanamayan dosyalar onaydan önce listelenir ve atlanır.'],
 warning:['同步会停止蜂窝服务，自动备份并校验，完成后需重启。请保持供电。','Synchronization stops cellular services, creates verified backups and requires a reboot afterwards. Keep power connected.','Eşitleme hücresel hizmetleri durdurur, doğrulanmış yedekler oluşturur ve yeniden başlatma gerektirir. Gücü bağlı tutun.'],
 conflict:['两边都有修改；请确认上述覆盖方向。','Both sides changed. Confirm the replacement direction above.','İki taraf da değişti. Yukarıdaki değiştirme yönünü onaylayın.'],
 typeYes:['输入 yes 确认操作','Type yes to confirm','Onaylamak için yes yazın'],
 sync:['执行同步','Synchronize','Eşitle'],cancel:['取消','Cancel','İptal'],refresh:['刷新','Refresh','Yenile'],
 last:['上次同步','Last synchronization','Son eşitleme'],noHistory:['暂无记录','No history','Kayıt yok'],reboot:['同步完成，需要重启生效。','Synchronization complete. Reboot to activate.','Eşitleme tamamlandı. Etkinleştirmek için yeniden başlatın.'],activated:['同步已生效','Synchronization activated','Eşitleme etkinleştirildi'],unchanged:['NV 文件已完全一致，未写入，也无需重启。','NV files already match exactly. Nothing was written; no reboot is needed.','NV dosyaları tamamen aynı. Yazma yapılmadı; yeniden başlatma gerekmiyor.'],
 backups:['备份管理','Backups','Yedekler'],backupNote:['备份会占用存储，可手动删除不再需要的备份；删除不会修改当前 NV。','Backups use storage. Delete unneeded backups manually; deletion does not change current NV.','Yedekler alan kaplar. Gereksiz yedekleri elle silin; silme mevcut NV verisini değiştirmez.'],
 noBackups:['暂无备份','No backups','Yedek yok'],remove:['删除备份','Delete backup','Yedeği sil'],deleteNote:['删除后无法通过该备份恢复。请输入 yes 确认。','This backup will no longer be available for recovery. Type yes to confirm.','Bu yedek artık kurtarma için kullanılamaz. Onaylamak için yes yazın.'],
 protected:['事务正在使用','In use by recovery','Kurtarma kullanıyor'],complete:['已完成','Complete','Tamamlandı'],incomplete:['未完成备份','Incomplete backup','Eksik yedek'],update:['系统更新保留','Update preservation','Güncelleme koruması'],importBackup:['原机导入备份','Import backup','İçe aktarma yedeği'],exportBackup:['固定 NV 写回备份','Fixed NV writeback backup','Sabit NV geri yazma yedeği'],
 preparing:['正在准备同步…','Preparing synchronization…','Eşitleme hazırlanıyor…'],checking:['正在验证同步条件…','Validating synchronization…','Eşitleme doğrulanıyor…'],stop:['正在停止蜂窝服务…','Stopping cellular services…','Hücresel hizmetler durduruluyor…'],backup:['正在备份并校验…','Backing up and verifying…','Yedekleniyor ve doğrulanıyor…'],stage:['正在准备工作副本…','Preparing working copies…','Çalışma kopyaları hazırlanıyor…'],commit:['正在切换工作副本…','Activating working copies…','Çalışma kopyaları etkinleştiriliyor…'],
 'write-backup':['正在写入备份 NV 并回读…','Writing redundant NV and verifying readback…','Yedek NV yazılıyor ve geri okuma doğrulanıyor…'],'write-primary':['正在写入主 NV 并回读…','Writing primary NV and verifying readback…','Birincil NV yazılıyor ve geri okuma doğrulanıyor…'],queued:['正在等待维护任务…','Waiting for maintenance…','Bakım bekleniyor…'],
 readError:['无法读取状态，请刷新重试。','Could not read status. Refresh to retry.','Durum okunamadı. Yenileyerek tekrar deneyin.'],failed:['操作未完成，备份和错误记录已保留。','Operation did not complete. Backups and error records are retained.','İşlem tamamlanmadı. Yedekler ve hata kayıtları korundu.'],busy:['有其他维护任务，请稍后重试。','Another maintenance task is active. Retry later.','Başka bir bakım etkin. Daha sonra deneyin.'],
 expired:['数据已变化或确认已过期，请重新确认。','Data changed or confirmation expired. Confirm again.','Veri değişti veya onay süresi doldu. Yeniden onaylayın.'],space:['备份空间不足，未开始写入。','Insufficient backup space. Writing has not started.','Yedek alanı yetersiz. Yazma başlamadı.'],recovery:['有未完成的 NV 恢复事务，请重启后检查。','An NV recovery transaction is pending. Reboot and check again.','Bekleyen NV kurtarma işlemi var. Yeniden başlatıp denetleyin.'],
 layout:['无法确认机型、固件槽位或主备布局，已禁用该方向。','Model, firmware slot or redundant layout could not be verified. This direction is disabled.','Model, donanım yazılımı yuvası veya yedek düzeni doğrulanamadı. Bu yön devre dışı.'],format:['NV 格式不兼容或校验失败，未开始写入。','NV format is incompatible or validation failed. Writing has not started.','NV biçimi uyumsuz veya doğrulama başarısız. Yazma başlamadı.'],missing:['工作副本或来源记录不可用，请先检查状态。','Working copies or provenance are unavailable. Check their status first.','Çalışma kopyaları veya kaynak kaydı kullanılamıyor. Önce durumunu denetleyin.'],opaque:['原机 delta/calinv 来源已变化，无法验证，已禁用导入。','Original delta/calinv changed and cannot be verified. Import is disabled.','Orijinal delta/calinv değişti ve doğrulanamıyor. İçe aktarma kapalı.'],
 backupMissing:['备份不存在，可能已被删除。','Backup not found; it may have been deleted.','Yedek bulunamadı; silinmiş olabilir.'],interrupted:['维护进程已中断，请检查备份和上次同步状态。','Maintenance was interrupted. Check backups and the last synchronization.','Bakım kesildi. Yedekleri ve son eşitlemeyi denetleyin.'],recovered:['已恢复同步前的数据；上次同步未提交。','Pre-synchronization data was restored; the last synchronization was not committed.','Eşitleme öncesi veri geri yüklendi; son eşitleme uygulanmadı.'],confirmation:['请输入小写 yes。','Enter lowercase yes.','Küçük harflerle yes yazın.']
};
function t(key){const lang=M.uiLanguage();return words[key][lang==='zh'?0:lang==='tr'?2:1];}
const call=(method,params=[])=>rpc.declare({object:'e5-nv',method,params,expect:{},nobatch:true});
const status=call('status'),list=call('backups'),preview=call('preview',['direction']);
const sync=call('sync',['direction','token','confirmation','conflict_ack']),remove=call('delete_backup',['id','confirmation']),compress=call('compress_backup',['id','confirmation']),manualBackup=call('manual_backup'),prepareDownload=call('prepare_download',['id']);
function errorText(code){
 if(code==='nv_interrupted_recovered')return t('recovered');
 if(code==='nv_conflict')return t('conflict');
 const keys={nv_busy:'busy',nv_writer_busy:'busy',nv_preview_expired:'expired',nv_confirmation_required:'confirmation',nv_backup_space:'space',nv_recovery_pending:'recovery',nv_writeback_recovery_required:'recovery',nv_writeback_recovery_failed:'recovery',nv_writeback_recovery_mismatch:'recovery',nv_worker_interrupted:'interrupted',nv_opaque_source_changed:'opaque',nv_backup_missing:'backupMissing',nv_profile_unknown:'layout',nv_slot_unknown:'layout',nv_device_unknown:'layout',nv_layout_unknown:'layout',nv_original_not_protected:'layout',nv_pair_identity_mismatch:'layout',nv_origin_unavailable:'missing',nv_work_unavailable:'missing',nv_state_unavailable:'missing'};
 return t(keys[code]||(/^(nv_invalid_|nv_layout_|nv_checksum_|nv_header_|nv_generation_|nv_identity_)/.test(code||'')?'format':'failed'));
}
function checked(value){if(!value||!value.ok){const e=new Error(errorText(value?.error));e.code=value?.error;throw e;}return value;}
function failure(e){return e?.code?errorText(e.code):t('readError');}
const progressTitle=job=>({manual_backup:'makingBackup',prepare_download:'preparingDownload',compress_backup:'compressing'}[job?.operation]||'syncing');
const direction=dir=>t(dir==='to-original'?'export':'import'),bytes=n=>(Number(n||0)/1048576).toFixed(1)+' MiB';
return view.extend({
 // NV hashing may take seconds. Never make LuCI's view loader wait for it.
 load:()=>Promise.resolve(null),
 render:function(initial){
  M.injectCss();if(M.localizeMenu)M.localizeMenu();
  let cached=initial||{},busy=!!cached.busy,action=false,revealed=false,alive=true,timer=null,backups={entries:[]};
  let statusReady=!!initial,statusLoading=!initial,backupLoading=true,backupError='',statusRequest=null,backupRequest=null,pendingJob=null;
  let progressOverlay=null,progressText=null,previousFocus=null,previousOverflow='',progressError='',progressHeading=null;
  const box=E('div'),backupBox=E('div'),notice=E('div',{class:'mud-nv-notice',role:'status','aria-live':'polite'});
  const say=text=>{if(alive)notice.textContent=text;};
  const showProgress=(phase='queued',heading='syncing')=>{
   if(!alive)return;
   if(!progressOverlay){
    progressText=E('p',{class:'mud-nv-progress-stage',role:'status','aria-live':'polite'});progressHeading=E('h3');
    progressOverlay=E('div',{class:'mud-nv-progress',role:'dialog','aria-modal':'true','aria-label':t(heading),tabindex:'-1'},[
     E('style',{},'.mud-nv-progress{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);overscroll-behavior:contain}.mud-nv-progress-card{box-sizing:border-box;width:min(440px,100%);padding:32px 28px;text-align:center;border:1px solid var(--hairline,#8884);border-radius:18px;background:var(--surface,#fff);color:var(--text,#222);box-shadow:0 20px 70px rgba(0,0,0,.25)}.mud-nv-progress-spinner{display:inline-block;width:42px;height:42px;border:4px solid var(--hairline,#8884);border-top-color:var(--brand,#0086bf);border-radius:50%;animation:mud-nv-progress-spin .8s linear infinite}.mud-nv-progress h3{font-size:1.15rem;margin:22px 0 12px}.mud-nv-progress-stage{font-size:1rem;font-weight:600;line-height:1.6;margin:0 0 14px}.mud-nv-progress-hint{font-size:.85rem;line-height:1.7;margin:0;color:var(--text-muted,#777)}@keyframes mud-nv-progress-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.mud-nv-progress-spinner{animation:none}}'),
     E('section',{class:'mud-nv-progress-card'},[E('span',{class:'mud-nv-progress-spinner','aria-hidden':'true'}),progressHeading,progressText,E('p',{class:'mud-nv-progress-hint'},t('keepPower'))])]);
    progressOverlay.addEventListener('keydown',event=>{if(event.key==='Escape'||event.key==='Tab')event.preventDefault();});
    previousFocus=document.activeElement;previousOverflow=document.body.style.overflow;
    document.body.style.overflow='hidden';document.body.appendChild(progressOverlay);progressOverlay.focus();
   }
   progressHeading.textContent=t(heading);progressText.textContent=progressError||t(words[phase]?phase:'queued');
  };
  const hideProgress=()=>{
   if(!progressOverlay)return;
   progressOverlay.remove();progressOverlay=null;progressText=null;progressError='';document.body.style.overflow=previousOverflow;
   if(previousFocus?.isConnected)previousFocus.focus();previousFocus=null;
  };
  const button=(key,click,disabled=false)=>{
   // LuCI E() stringifies false attributes: disabled="false" still disables
   // an HTML button. Set the DOM property after construction instead.
   const node=E('button',{type:'button',class:'mud-btn',click},t(key));
   node.disabled=!!disabled;return node;
  };
  const showResult=(text,failed=false)=>{
   say(text);if(!alive)return;
   ui.showModal(t(failed?'operationFailed':'operationDone'),[E('p',{},text),E('div',{class:'mud-nv-actions'},[button('close',ui.hideModal)])]);
  };
  const downloadFile=data=>{
   if(!/^\/tmp\/e5-nv-download\/export-[0-9a-f]{24}\.tar\.gz$/.test(data?.path||'')||!/^[a-z0-9._-]+\.tar\.gz$/.test(data?.filename||''))throw new Error('invalid download metadata');
   const form=E('form',{method:'post',action:L.env.cgi_base+'/cgi-download',enctype:'application/x-www-form-urlencoded',style:'display:none'},[
    E('input',{type:'hidden',name:'sessionid',value:rpc.getSessionID()}),E('input',{type:'hidden',name:'path',value:data.path}),E('input',{type:'hidden',name:'filename',value:data.filename})]);
   document.body.appendChild(form);form.submit();form.remove();
  };
  const badge=(key,good)=>E('span',{class:'mud-tag mud-nv-badge '+(good?'good':'')},t(key));
  const loading=()=>E('span',{class:'mud-loadline',role:'status'},[E('i',{class:'mud-loading-spinner','aria-hidden':'true'}),t('loading')]);
  const imeis=(s,key)=>['sim1','sim2'].map((slot,i)=>{const value=s.imei?.[key]?.[slot];return E('div',{class:'mud-nv-row'},[E('span',{},'IMEI '+(i+1)),E('code',{'data-imei':key+'-'+slot},value?(revealed?value:'•••••••••••'+value.slice(-4)):t(!statusReady&&statusLoading?'loading':'unavailable'))]);});
  const paint=value=>{
   if(!alive)return;cached={...cached,...value};const s=cached,last=s.last_sync||{},delta=s.comparison;
   busy=!!s.busy||['queued','running'].includes(s.job?.state);const locked=busy||action||statusLoading;
   box.replaceChildren(
    E('div',{class:'mud-nv-toolbar'},[E('div',{class:'mud-nv-tags'},[!statusReady&&statusLoading?loading():badge(s.initialized===true?'initialized':s.initialized===false?'uninitialized':'unavailable',s.initialized),s.firmware_slot?E('span',{class:'mud-tag'},s.profile+' · '+s.firmware_slot.toUpperCase()):E('span')]),E('div',{class:'mud-nv-actions'},[button(revealed?'hide':'show',()=>{revealed=!revealed;paint({});},!statusReady),button('refresh',()=>refresh(true),locked)])]),
    E('div',{class:'mud-nv-grid'},['original','working'].map(key=>E('section',{class:'mud-card'},[E('h3',{},t(key)),E('p',{class:'mud-nv-muted'},t(key==='original'?'originalNote':'workingNote')),!statusReady&&statusLoading?loading():badge((key==='original'?s.original_validated:s.work_validated)?'valid':'invalid',key==='original'?s.original_validated:s.work_validated),...imeis(s,key)]))),
    E('p',{class:'mud-nv-muted'},t('identity')),
    E('section',{class:'mud-card mud-nv-summary'},[E('h3',{},t('differences')),delta?E('div',{class:'mud-nv-tags'},[badge(s.fixed_equal?'same':'different',s.fixed_equal),E('span',{},t('items')+' · '+delta.items),E('span',{},t('identities')+' · '+delta.identity_items)]):!statusReady&&statusLoading?loading():E('p',{},s.validated?t('detailUnavailable'):errorText(s.export_reason||s.reason)),E('p',{class:'mud-nv-muted'},t('compareNote'))]),
    E('div',{class:'mud-nv-grid'},['from-original','to-original'].map(dir=>{const enabled=dir==='from-original'?s.can_import:s.can_export,reason=dir==='from-original'?s.import_reason:s.export_reason;return E('section',{class:'mud-card mud-nv-direction'},[E('h3',{},direction(dir)),E('p',{},t(dir==='from-original'?'importNote':'exportNote')),!enabled&&reason?E('p',{class:'mud-nv-warning'},errorText(reason)):E('span'),dir==='to-original'&&s.writeback_blocked?.length?E('p',{class:'mud-nv-warning'},t('skipped')+' '+s.writeback_blocked.join(', ')):E('span'),button(dir==='from-original'?'import':'export',()=>confirmSync(dir),locked||!enabled)]);})),
    E('section',{class:'mud-card mud-nv-history'},[E('h3',{},t('last')),!statusReady&&statusLoading?loading():E('p',{},last.time?new Date(last.time*1000).toLocaleString()+' · '+direction(last.direction):t(statusReady?'noHistory':'unavailable')),last.time?E('p',{class:last.ok===false?'mud-nv-warning':''},last.ok===false?errorText(last.error):t(last.reboot_required?'reboot':'activated')):E('span'),last.backup?E('code',{},last.backup):E('span')])
   );paintBackups();if(busy)showProgress(s.job?.phase,progressTitle(s.job));
  };
  const paintBackups=()=>{
   if(!alive)return;
   backupBox.replaceChildren(E('div',{class:'mud-nv-toolbar'},[E('h3',{},t('backups')),E('div',{class:'mud-nv-actions'},[E('span',{class:'mud-tag'},backups.total_bytes==null?'—':bytes(backups.total_bytes)),button('manualBackup',()=>startMaintenance('manual_backup',manualBackup),busy||action)])]),E('p',{class:'mud-nv-muted'},t('backupNote')),
    E('div',{class:'mud-nv-backups'},backups.entries.length?backups.entries.map(row=>E('div',{class:'mud-nv-backup'},[E('div',{},[E('code',{},row.id),E('p',{class:'mud-nv-muted'},t(row.kind==='manual'?'manualKind':row.kind==='nv-writeback'||row.kind==='fixed-writeback'?'exportBackup':row.kind==='update-preservation'?'update':'importBackup')+' · '+bytes(row.bytes)+' · '+t(row.complete?'complete':'incomplete')+(row.compressed?' · '+t('compressed')+(row.raw_bytes?' · '+t('rawSize')+' '+bytes(row.raw_bytes):''):''))]),E('div',{class:'mud-nv-actions'},[button('download',()=>startMaintenance('prepare_download',prepareDownload,[row.id]),busy||action||row.protected),row.can_compress?button('compress',()=>confirmCompress(row),busy||action||row.protected):E('span'),button(row.protected?'protected':'remove',()=>confirmDelete(row),busy||action||row.protected)])])):backupLoading?[loading()]:[E('p',{},backupError||t('noBackups'))]));
  };
  const updateBackups=()=>{
   if(!alive)return Promise.resolve();if(backupRequest)return backupRequest;
   backupLoading=true;backupError='';paintBackups();
   backupRequest=(async()=>{try{const result=checked(await list());if(alive)backups=result;}
    catch(e){if(alive)backupError=failure(e);}
    finally{backupLoading=false;backupRequest=null;paintBackups();}})();return backupRequest;
  };
  const schedule=()=>{if(alive){clearTimeout(timer);timer=setTimeout(()=>refresh(false),1500);}};
  const refresh=(withBackups=false)=>{
   if(!alive)return Promise.resolve();if(withBackups)updateBackups();if(statusRequest)return statusRequest;
   statusLoading=true;paint({});
   statusRequest=(async()=>{try{const s=checked(await status());if(!alive)return;const wasBusy=busy;statusReady=true;statusLoading=false;progressError='';paint({...s,busy:!!s.busy});
    if(busy){if(!pendingJob)pendingJob=s.job?.id;say(t(words[s.job?.phase]?s.job.phase:'queued'));schedule();}
    else{
     hideProgress();const result=s.job?.result||{};
     const text=s.job?.state==='failed'?errorText(s.job.error):s.job?.state==='complete'?t(result.download?'downloadStarted':result.manual_backup?'manualDone':result.backup_compressed?'compressDone':result.skipped_files?.length?'partialDone':result.unchanged?'unchanged':s.last_sync?.reboot_required?'reboot':'activated'):'';
     say(text);
     if(pendingJob&&s.job?.id===pendingJob&&['complete','failed'].includes(s.job.state)){
      pendingJob=null;try{if(result.download)downloadFile(result.download);showResult(text,s.job.state==='failed');}catch(e){showResult(failure(e),true);}
     }
     if(wasBusy)updateBackups();
    }
   }catch(e){statusLoading=false;if(busy)progressError=failure(e);paint({can_import:false,can_export:false,reason:'nv_state_unavailable'});say(failure(e));if(busy)schedule();}
   finally{statusRequest=null;statusLoading=false;paint({});}})();return statusRequest;
  };
  const typedModal=(title,nodes,execute,key='sync')=>{
   const input=E('input',{type:'text',autocomplete:'off',spellcheck:'false',placeholder:'yes','aria-label':t('typeYes')});let submitting=false;
   const confirm=button(key,async()=>{if(input.value!=='yes'||submitting)return;submitting=true;confirm.disabled=true;ui.hideModal();await execute();},true);
   input.addEventListener('input',()=>{confirm.disabled=input.value!=='yes';});
   ui.showModal(title,[E('div',{class:'mud-nv-modal'},[...nodes,E('label',{},[t('typeYes'),input]),E('div',{class:'mud-nv-actions'},[button('cancel',ui.hideModal),confirm])])]);input.focus();
  };
  const confirmSync=async(dir)=>{
   if(busy||action||statusLoading||!alive)return;action=true;paint({});say(t('preparing'));showProgress('preparing','preparing');
   try{const plan=checked(await preview(dir));if(!alive)return;
    hideProgress();
    typedModal(direction(dir),[E('p',{},t(dir==='from-original'?'importNote':'exportNote')),E('p',{},t('warning')),dir==='to-original'?E('p',{},t('writeScope')+': '+(plan.writeback_scope||[]).join(', ')):E('span'),plan.writeback_blocked?.length?E('p',{class:'mud-nv-warning'},t('skipped')+' '+plan.writeback_blocked.join(', ')):E('span'),plan.conflict?E('p',{class:'mud-nv-warning'},t('conflict')):E('span')],async()=>{
     if(busy||!alive)return;action=true;paint({});showProgress('queued');try{const result=checked(await sync(dir,plan.token,'yes',!!plan.conflict));if(!alive)return;pendingJob=result.job?.id;paint({busy:true,job:result.job});say(t('queued'));schedule();}catch(e){if(e.code){hideProgress();showResult(failure(e),true);}else{say(failure(e));paint({busy:true});refresh(false);}}finally{action=false;paint({});}
    });say('');
   }catch(e){hideProgress();showResult(failure(e),true);}finally{action=false;paint({});}
  };
  const startMaintenance=async(operation,method,args=[])=>{
   if(busy||action||!alive)return;action=true;paint({});showProgress('queued',progressTitle({operation}));
   try{const result=checked(await method(...args));if(!alive)return;pendingJob=result.job?.id;paint({busy:true,job:result.job});schedule();}
   catch(e){hideProgress();showResult(failure(e),true);}finally{action=false;paint({});}
  };
  const confirmCompress=row=>{
   if(busy||action||row.protected)return;
   typedModal(t('compress'),[E('p',{},t('compressNote')),E('code',{},row.path)],async()=>{
    action=true;paint({});showProgress('backup','compressing');
    try{const result=checked(await compress(row.id,'yes'));if(!alive)return;pendingJob=result.job?.id;paint({busy:true,job:result.job});schedule();}
    catch(e){hideProgress();showResult(failure(e),true);}finally{action=false;paint({});}
   },'compress');
  };
  const confirmDelete=row=>{
   if(busy||action||row.protected)return;
   typedModal(t('remove'),[E('p',{},t('deleteNote')),E('code',{},row.path)],async()=>{action=true;paint({});try{checked(await remove(row.id,'yes'));await updateBackups();showResult(t('deleted'));}catch(e){showResult(failure(e),true);}finally{action=false;paint({});}},'remove');
  };
  paint(initial||{});updateBackups();if(!initial)refresh(false);else if(busy)schedule();this.stopNV=()=>{alive=false;clearTimeout(timer);revealed=false;hideProgress();};
  return E('div',{class:'mud mud-nv'},[
   E('style',{},'.mud-nv{max-width:1120px;color:var(--text,inherit)}.mud-nv>h2{margin-bottom:8px}.mud-nv>p{margin-bottom:24px}.mud-nv-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.mud-nv .mud-card{padding:20px}.mud-nv h3{font-size:.9rem;letter-spacing:0;margin:0 0 12px}.mud-nv p{line-height:1.65}.mud-nv-muted{color:var(--text-muted,#777);font-size:.85rem}.mud-nv-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:15px}.mud-nv code,.mud-nv-modal code{font-size:.84rem;overflow-wrap:anywhere;background:transparent;color:inherit;padding:0;font-variant-numeric:tabular-nums}.mud-nv-toolbar,.mud-nv-actions,.mud-nv-tags{display:flex;align-items:center;flex-wrap:wrap;gap:12px}.mud-nv-toolbar{justify-content:space-between;margin-bottom:16px}.mud-nv-actions{margin:0}.mud-nv-tags{gap:10px}.mud-nv-badge{margin-bottom:6px}.mud-nv-tags>.mud-tag{display:inline-flex;align-items:center;line-height:1.5;margin:0}.mud-nv-badge.good{color:var(--success,#36865a)}.mud-nv-summary,.mud-nv-history{margin:18px 0}.mud-nv-direction{display:flex;flex-direction:column;gap:10px}.mud-nv-direction p{margin:0 0 10px}.mud-nv-direction button{margin-top:auto;align-self:flex-start}.mud-nv-warning{color:var(--warning,#b87a23)}.mud-nv-notice:not(:empty){position:sticky;top:72px;z-index:50;border:1px solid var(--hairline,#8884);border-left:4px solid var(--brand,#0086bf);font-weight:600;padding:14px 18px;margin:16px 0;border-radius:10px;background:var(--surface-sunken,rgba(127,127,127,.08));line-height:1.6}.mud-nv-backups{max-height:320px;overflow:auto;overscroll-behavior:contain}.mud-nv-backup{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-top:1px solid var(--hairline,#8883)}.mud-nv-backup p{margin:6px 0 0}.mud-nv-backup button{flex-shrink:0}.mud-nv-modal{display:grid;gap:16px}.mud-nv-modal p{margin:0;line-height:1.7}.mud-nv-modal input{display:block;width:100%;box-sizing:border-box;margin:10px 0 0;padding:10px;border:1px solid var(--hairline,#8885);border-radius:8px;background:var(--surface,transparent);color:var(--text,inherit)}.mud-nv-modal .mud-nv-actions{justify-content:flex-end}@media(max-width:640px){.mud-nv-grid{grid-template-columns:1fr}.mud-nv .mud-card{padding:16px}.mud-nv-backup{align-items:flex-start;flex-wrap:wrap}}'),
   E('h2',{},t('title')),E('p',{class:'mud-nv-muted'},t('intro')),notice,box,E('section',{class:'mud-card'},[backupBox])]);
 },unload:function(){if(this.stopNV)this.stopNV();},handleSaveApply:null,handleSave:null,handleReset:null
});
