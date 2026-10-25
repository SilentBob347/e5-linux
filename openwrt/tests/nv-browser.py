#!/usr/bin/env python3
"""Browser smoke tests for the real NV view, synthetic RPC only.

Uses an existing Playwright/Chromium installation. No device, network or NV IO.
Optional --screenshots stores representative previews in the selected directory.
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP=Path(__file__).resolve().parents[2]
VIEW=(TOP/'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/nv.js').read_text(encoding='utf-8')
COMMON=(TOP/'openwrt/luci-app-t551m/htdocs/luci-static/resources/mu300/common.js').read_text(encoding='utf-8').split('var CSS = `',1)[1].split('`;',1)[0]
HARNESS=r"""({source,css,lang,dark})=>{
 document.documentElement.lang=lang;
 document.head.innerHTML='';document.body.innerHTML='';
 const style=document.createElement('style');style.textContent=css;
 document.head.append(style);
 document.documentElement.style.cssText=dark?'--surface:#181e28;--surface-sunken:#222b37;--hairline:#354050;--text:#e7edf6;--text-muted:#a6b1c3;--brand:#53cfbd;--success:#65c18c;--warning:#dfb76d':'--surface:white;--surface-sunken:#f0f3f6;--hairline:#d9e0e8;--text:#202c39;--text-muted:#596a7b;--brand:#147b73;--success:#288252;--warning:#9e6300';
 document.body.style.cssText='font:16px system-ui;margin:0;padding:20px;background:'+(dark?'#0f141d':'#f5f7fa');
 function E(tag,attrs={},children=[]){const n=document.createElement(tag);for(const [key,v]of Object.entries(attrs)){if(typeof v==='function')n.addEventListener(key,v);else if(v!=null)n.setAttribute(key,v);}for(const c of [].concat(children)){if(c!=null)n.append(c);}return n;}
 window.__calls=[];
 const state={ok:true,initialized:true,validated:true,work_validated:true,original_validated:true,can_import:true,can_export:true,profile:'yuanhang41s',firmware_slot:'b',fixed_equal:false,comparison:{items:2,identity_items:1},imei:{original:{sim1:'123456789012345',sim2:'987654321098765'},working:{sim1:'111111111111111',sim2:'222222222222222'}},last_sync:{time:1792900000,direction:'from-original',ok:true,reboot_required:false,backup:'/etc/e5-nv/backups/20261025-123456-012345abcdef'}};
 const rpc={declare:spec=>(...args)=>{window.__calls.push({method:spec.method,args});if(spec.method==='status')return Promise.resolve(state);if(spec.method==='backups')return Promise.resolve({ok:true,total_bytes:209715200,entries:Array.from({length:12},(_,i)=>({id:'20261025-123456-012345abcd'+String(i).padStart(2,'0'),path:'/etc/e5-nv/backups/fixture-'+i,bytes:17825792,complete:true,protected:i===0}))});if(spec.method==='preview')return Promise.resolve({ok:true,token:'synthetic',conflict:true});throw Error('Mutating RPC not allowed in browser fixture');}};
 const ui={showModal(title,nodes){const modal=E('div',{id:'test-modal',style:'position:fixed;inset:0;overflow:auto;padding:24px;background:var(--surface);color:var(--text);z-index:100'},[E('h2',{},title),...nodes]);document.body.append(modal);},hideModal(){document.getElementById('test-modal')?.remove();}};
 const M={uiLanguage:()=>lang,injectCss(){},localizeMenu(){}};
 const page=new Function('view','rpc','ui','M','E',source)({extend:o=>o},rpc,ui,M,E);
 document.body.append(page.render(state));window.__page=page;
}"""


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--screenshots',type=Path);args=parser.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        for lang in ('zh','en','tr'):
            for dark in (False,True):
                for width in (380,1120):
                    page.set_viewport_size({'width':width,'height':900})
                    page.evaluate(HARNESS,dict(source=VIEW,css=COMMON,lang=lang,dark=dark))
                    page.wait_for_selector('.mud-nv-backup')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(lang,dark,width,'overflow')
                    assert page.locator('[data-imei]').count()==4
                    assert '123456789012345' not in page.locator('.mud-nv').inner_text()
                    page.locator('.mud-nv-toolbar button').first.click()
                    assert page.locator('[data-imei="original-sim1"]').inner_text()=='123456789012345'
                    page.locator('.mud-nv-toolbar button').first.click()
                    assert '123456789012345' not in page.locator('.mud-nv').inner_text()
                    assert page.locator('.mud-nv-backups').evaluate('(n)=>n.clientHeight<=320&&n.scrollHeight>n.clientHeight')
                    assert page.locator('.mud-nv-backup button').first.is_disabled()
                    page.locator('.mud-nv-direction button').nth(1).click()
                    page.wait_for_selector('#test-modal input')
                    submit=page.locator('#test-modal button').last
                    assert submit.is_disabled();page.locator('#test-modal input').fill('YES');assert submit.is_disabled()
                    page.locator('#test-modal input').fill('yes');assert submit.is_enabled()
                    assert not any(c['method'] in ('sync','delete_backup') for c in page.evaluate('__calls'))
                    page.locator('#test-modal button').first.click()
                    if args.screenshots and lang=='zh' and dark:
                        args.screenshots.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(args.screenshots/f'nv-{width}.png'),full_page=True)
                    page.evaluate('__page.unload()')
        browser.close()
        assert not errors,errors
    print('PASS: 12 real-browser combinations (ZH/EN/TR, light/dark, desktop/mobile), four IMEIs, masking, bounded backup scrolling, typed confirmation, no mutating RPC or JS errors')


if __name__=='__main__':main()
