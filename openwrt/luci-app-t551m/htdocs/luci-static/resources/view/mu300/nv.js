'use strict';
'require view';
'require rpc';
'require ui';
'require mu300.common as M';

const words={
 'NV 持久化设置':['NV persistence','NV kalıcılığı'],
 'OpenWrt 工作 NV':['OpenWrt working NV','OpenWrt çalışma NV'], '原机 NV':['Original NV','Orijinal NV'],
 '原机 NV → OpenWrt':['Original NV → OpenWrt','Orijinal NV → OpenWrt'],
 'OpenWrt NV → 原机':['OpenWrt NV → original','OpenWrt NV → orijinal'],
 '初始化状态':['Initialization','Başlatma'], '已初始化':['Initialized','Başlatıldı'], '未初始化':['Not initialized','Başlatılmadı'],
 '校验状态':['Validation','Doğrulama'], '通过':['Passed','Başarılı'], '不可用':['Unavailable','Kullanılamıyor'],
 '按完整文件比较；运行时变化或主备配对也会产生差异。':['Full files are compared; runtime changes or redundant-copy reconciliation can also cause differences.','Dosyaların tamamı karşılaştırılır; çalışma değişiklikleri veya yedek eşleme de fark oluşturabilir.'],
 '两者一致':['Copies match','Kopyalar aynı'], '一致':['Matching','Aynı'], '不同':['Different','Farklı'],
 '上次同步':['Last sync','Son eşitleme'], '暂无记录':['No history','Kayıt yok'],
 '备份位置':['Backup location','Yedek konumu'], '需要重启生效':['Reboot required','Yeniden başlatma gerekli'],
 '刷新':['Refresh','Yenile'], '取消':['Cancel','İptal'], '执行同步':['Synchronize','Eşitle'],
 '操作失败':['Operation failed','İşlem başarısız'], '正在同步，请勿断电…':['Synchronizing; keep power connected…','Eşitleniyor; gücü kesmeyin…'],
 '同步完成，请重启设备使基带使用导入的数据。':['Import complete. Reboot to activate it.','İçe aktarma tamamlandı. Etkinleştirmek için yeniden başlatın.'],
 '该操作会用原机分区中的 NV 覆盖 OpenWrt 工作副本。会停止蜂窝服务并备份两边数据；完成后需重启。':['This replaces the OpenWrt working copies with the original partitions. Both sides are backed up. The modem is stopped for the import; reboot afterwards.','OpenWrt çalışma kopyaları orijinal bölümlerle değiştirilir. Her iki taraf yedeklenir. Modem durdurulur; ardından yeniden başlatın.'],
 '原机与 OpenWrt 的 NV 都有变化；继续将明确舍弃 OpenWrt 当前修改。':['Both NV sets changed. Continuing explicitly replaces the OpenWrt changes.','Her iki NV değişti. Devam etmek OpenWrt değişikliklerini siler.'],
 '输入 yes 确认覆盖':['Type yes to confirm replacement','Değiştirmeyi onaylamak için yes yazın'],
 '原机写回尚未开放：本机校准条目和主备写回规则尚未核实，不会把整套运行时 NV 写回原分区。':['Original writeback is unavailable: calibration items and redundant-copy write rules are not verified. Entire runtime NV will never be written back.','Kalibrasyon öğeleri ve yedek yazma kuralları doğrulanmadığı için orijinale yazma kapalıdır. Çalışma NV seti bütünüyle geri yazılmaz.'],
 '固定与运行时 NV 校验通过；delta/calinv 仅核对原始来源，不展示 NV 内容。':['Fixed/runtime NV checksums validated; delta/calinv use source fingerprints. NV contents are never displayed.','Sabit/çalışma NV sağlama toplamları doğrulandı; delta/calinv kaynak özetiyle kontrol edilir. NV içeriği gösterilmez.'],
 '备份空间不足，未修改 NV。':['Insufficient backup space; NV was not changed.','Yedek alanı yetersiz; NV değiştirilmedi.'],
 '请等待其他维护操作完成。':['Wait for the other maintenance operation.','Diğer bakım işlemini bekleyin.'],
 '原机不透明 NV 来源已变化，无法确认格式，已禁用同步。':['Opaque original NV changed; its format cannot be verified, so import is disabled.','Opak orijinal NV değişti; biçim doğrulanamadığı için içe aktarma kapalı.'],
 '来源或工作副本发生变化，请刷新后重新确认。':['The source or working copy changed. Refresh and confirm again.','Kaynak veya çalışma kopyası değişti. Yenileyip tekrar onaylayın.'],
 '存在 NV 冲突，需要明确确认覆盖方向。':['NV conflict: explicitly confirm which copy to replace.','NV çakışması: değiştirilecek tarafı açıkça onaylayın.'],
 'NV 格式或校验失败，已停止操作。':['NV format or checksum validation failed; operation stopped.','NV biçimi veya sağlama toplamı geçersiz; işlem durduruldu.'],
 '无法可靠识别机型、槽位或 NV 布局，已禁用同步。':['Model, slot or NV layout could not be identified reliably; synchronization is disabled.','Model, yuva veya NV düzeni belirlenemedi; eşitleme kapalı.'],
 '工作副本或来源记录不完整，已禁用同步。':['Working copies or origin records are incomplete; synchronization is disabled.','Çalışma kopyaları veya kaynak kayıtları eksik; eşitleme kapalı.'],
 '导入未完成。备份与错误记录已保留，请检查后重启。':['Import did not complete. Backups and error records are retained; inspect them before rebooting.','İçe aktarma tamamlanmadı. Yedekler ve hata kayıtları korundu; yeniden başlatmadan önce inceleyin.']
};
function t(s){const lang=M.uiLanguage();return words[s]?lang==='zh'?s:words[s][lang==='tr'?1:0]:s;}
const status=rpc.declare({object:'e5-nv',method:'status',expect:{}});
const preview=rpc.declare({object:'e5-nv',method:'preview',params:['direction'],expect:{}});
const sync=rpc.declare({object:'e5-nv',method:'sync',params:['direction','token','confirmation','conflict_ack'],expect:{}});
function message(code){
 if(code==='nv_calibration_rules_unverified')return t('原机写回尚未开放：本机校准条目和主备写回规则尚未核实，不会把整套运行时 NV 写回原分区。');
 if(code==='nv_opaque_source_changed')return t('原机不透明 NV 来源已变化，无法确认格式，已禁用同步。');
 if(code==='nv_preview_expired')return t('来源或工作副本发生变化，请刷新后重新确认。');
 if(code==='nv_conflict')return t('存在 NV 冲突，需要明确确认覆盖方向。');
 if(code==='nv_backup_space')return t('备份空间不足，未修改 NV。');
 if(code==='nv_busy'||code==='nv_writer_busy')return t('请等待其他维护操作完成。');
 if(/^nv_invalid_/.test(code||''))return t('NV 格式或校验失败，已停止操作。');
 if(['nv_profile_unknown','nv_slot_unknown','nv_layout_unknown','nv_original_not_protected'].includes(code))return t('无法可靠识别机型、槽位或 NV 布局，已禁用同步。');
 if(['nv_origin_unavailable','nv_work_unavailable','nv_state_unavailable'].includes(code))return t('工作副本或来源记录不完整，已禁用同步。');
 return t('导入未完成。备份与错误记录已保留，请检查后重启。');
}
function checked(value){if(!value||!value.ok)throw new Error(message(value?.error));return value;}
return view.extend({
 load:()=>status().then(checked),
 render:function(initial){
  M.injectCss();
  const box=E('div'),notice=E('p',{role:'status','aria-live':'polite'});let busy=!!initial?.busy,timer=null,cached=initial||{};
  const paint=value=>{
   const s=cached={...cached,...value};
   const yes=v=>t(v?'通过':'不可用'),last=s.last_sync||{};
   box.replaceChildren(E('div',{class:'mud-card',style:'padding:20px;margin-bottom:16px'},[
    E('dl',{class:'nv-grid'},[
     E('dt',{},t('初始化状态')),E('dd',{},t(s.initialized?'已初始化':'未初始化')),
     E('dt',{},t('OpenWrt 工作 NV')),E('dd',{},yes(s.work_validated)),
     E('dt',{},t('原机 NV')),E('dd',{},yes(s.original_validated)),
     E('dt',{},t('两者一致')),E('dd',{},s.same==null?'—':t(s.same?'一致':'不同')),
     E('dt',{},t('上次同步')),E('dd',{},last.time?(new Date(last.time*1000).toLocaleString()+' · '+t(last.direction==='from-original'?'原机 NV → OpenWrt':'OpenWrt NV → 原机')):t('暂无记录')),
     E('dt',{},t('备份位置')),E('dd',{},last.backup||s.backup_path||'—')]),
    s.validated?E('p',{},t('固定与运行时 NV 校验通过；delta/calinv 仅核对原始来源，不展示 NV 内容。')):E('span'),
    E('p',{},t('按完整文件比较；运行时变化或主备配对也会产生差异。')),
    last.reboot_required?E('p',{},t('需要重启生效')):E('span'),
    last.ok===false?E('p',{class:'alert-message warning'},message(last.error)):E('span'),
    s.reason||s.import_reason?E('p',{class:'alert-message warning'},message(s.reason||s.import_reason)):E('span'),
    E('div',{class:'nv-actions'},[
     E('button',{class:'cbi-button cbi-button-action',disabled:busy||!s.can_import,click:()=>confirmImport()},t('原机 NV → OpenWrt')),
     E('button',{class:'cbi-button',disabled:true,title:message(s.export_reason)},t('OpenWrt NV → 原机')),
     E('button',{class:'cbi-button',disabled:busy,click:()=>refresh()},t('刷新'))]),
    E('p',{},message(s.export_reason))]));
  };
  const refresh=async()=>{try{const s=checked(await status());paint(s);return cached;}catch(e){notice.textContent=e.message||t('操作失败');}};
  const pollJob=async()=>{
   const s=await refresh();if(!s){if(busy)timer=setTimeout(pollJob,3000);return;}
   if(['queued','running'].includes(s.job?.state)){notice.textContent=t('正在同步，请勿断电…');timer=setTimeout(pollJob,1000);return;}
   busy=false;paint(s);notice.textContent=s.job?.state==='complete'?t('同步完成，请重启设备使基带使用导入的数据。'):message(s.job?.error);
  };
  const confirmImport=async()=>{
   try{
    const plan=checked(await preview('from-original')),input=E('input',{type:'text',autocomplete:'off',spellcheck:'false',placeholder:'yes'});
    const button=E('button',{class:'cbi-button cbi-button-action',disabled:true,click:async()=>{
     if(input.value!=='yes')return;ui.hideModal();busy=true;paint({});
     try{checked(await sync('from-original',plan.token,'yes',!!plan.conflict));pollJob();}
     catch(e){busy=false;notice.textContent=e.message||t('操作失败');refresh();}
    }},t('执行同步'));
    input.addEventListener('input',()=>{button.disabled=input.value!=='yes';});
    ui.showModal(t('原机 NV → OpenWrt'),[
     E('p',{},t('该操作会用原机分区中的 NV 覆盖 OpenWrt 工作副本。会停止蜂窝服务并备份两边数据；完成后需重启。')),
     plan.conflict?E('p',{class:'alert-message warning'},t('原机与 OpenWrt 的 NV 都有变化；继续将明确舍弃 OpenWrt 当前修改。')):E('span'),
     E('label',{},[E('span',{},t('输入 yes 确认覆盖')),input]),
     E('div',{class:'nv-actions',style:'margin-top:20px'},[E('button',{class:'cbi-button',click:ui.hideModal},t('取消')),button])]);input.focus();
   }catch(e){notice.textContent=e.message||t('操作失败');}
  };
  paint(initial||{});if(initial?.busy)pollJob();
  this.pollTimer=()=>timer;return E('div',{class:'nv-page'},[
   E('style',{},'.nv-page{max-width:1080px}.nv-grid{display:grid;grid-template-columns:minmax(100px,150px) minmax(0,1fr);gap:12px 20px}.nv-grid dd{margin:0;overflow-wrap:anywhere}.nv-actions{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.nv-page input{display:block;margin-top:10px;width:100%;max-width:360px}.nv-page .mud-card{background:var(--surface,var(--background-color,#181d26));border:1px solid var(--border-color,#ffffff20);border-radius:16px}'),
   E('h2',{},t('NV 持久化设置')),box,notice]);
 },unload:function(){if(this.pollTimer)clearTimeout(this.pollTimer());},handleSaveApply:null,handleSave:null,handleReset:null
});
