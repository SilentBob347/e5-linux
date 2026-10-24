// Run the real LuCI view with DOM/RPC fixtures; no device or NV data involved.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname,
    '../luci-app-t551m/htdocs/luci-static/resources/view/mu300/nv.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
function fixture(lang='zh', valid=true, busy=false) {
    const state={modal:[],requests:[],timers:[],status:{ok:true,initialized:true,
        validated:valid,work_validated:valid,original_validated:valid,can_import:valid,
        can_export:false,same:false,export_reason:'nv_calibration_rules_unverified'}};
    if(busy)Object.assign(state.status,{busy:true,can_import:false,job:{state:'running'}});
    function E(tag,attrs={},children=[]) {
        return {tag,...attrs,children:Array.isArray(children)?children:[children],
            textContent:'',value:'',events:{},
            replaceChildren(...nodes){this.children=nodes;},
            addEventListener(event,fn){this.events[event]=fn;},focus(){}};
    }
    const rpc={declare:spec=>(...args)=>{
        state.requests.push({method:spec.method,args});
        if(spec.method==='status')return Promise.resolve(state.status);
        if(spec.method==='preview')return Promise.resolve({ok:true,token:'verified',conflict:true});
        return Promise.resolve({ok:true,job:{state:'queued'}});
    }};
    const M={uiLanguage:()=>lang,injectCss(){state.themed=true;}};
    const ui={showModal(title,nodes){state.modal=nodes;},hideModal(){state.modal=[];}};
    const view=new Function('view','rpc','ui','M','E','setTimeout','clearTimeout',source)(
        {extend:x=>x},rpc,ui,M,E,(fn,ms)=>{state.timers.push(fn);return 1;},()=>{});
    const root=view.render(state.status);
    const all=node=>!node||typeof node!=='object'?[]:[node,...node.children.flatMap(all)];
    state.nodes=()=>[...all(root),...state.modal.flatMap(all)];
    state.button=label=>state.nodes().find(n=>n.tag==='button'&&n.children.includes(label));
    state.text=()=>state.nodes().map(n=>n.textContent+' '+n.children.filter(x=>typeof x==='string').join(' ')).join(' ');
    return state;
}
(async()=>{
    for(const [lang,importLabel,title] of [['zh','原机 NV → OpenWrt','NV 持久化设置'],
            ['en','Original NV → OpenWrt','NV persistence'],['tr','Orijinal NV → OpenWrt','NV kalıcılığı']]) {
        const s=fixture(lang);assert(s.themed);assert(s.text().includes(title));
        const buttons=s.nodes().filter(n=>n.tag==='button');assert.equal(buttons[1].disabled,true);
        await s.button(importLabel).click();
        const input=s.nodes().find(n=>n.tag==='input'),confirm=s.nodes().filter(n=>n.tag==='button').at(-1);
        assert(confirm.disabled);input.value='YES';input.events.input();assert(confirm.disabled);
        input.value='yes';input.events.input();assert.equal(confirm.disabled,false);
        await confirm.click();await flush();
        const request=s.requests.find(r=>r.method==='sync');
        assert.deepEqual(request.args,['from-original','verified','yes',true]);
        // Status fields remain visible while the async job starts.
        assert(!s.text().includes(lang==='en'?'Not initialized':lang==='zh'?'未初始化':'Başlatılmadı'));
    }
    const invalid=fixture('en',false);
    assert(invalid.button('Original NV → OpenWrt').disabled);
    assert(!invalid.text().includes('checksums validated'));
    const running=fixture('en',true,true);await flush();
    assert(running.button('Original NV → OpenWrt').disabled);
    assert(running.timers.length>0);
    console.log('PASS: three languages, theme API, disabled export/invalid state, typed yes, conflict acknowledgment, async status and polling');
})().catch(error=>{console.error(error);process.exitCode=1;});
