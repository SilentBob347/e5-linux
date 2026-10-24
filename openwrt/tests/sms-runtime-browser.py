"""Real SMS page; fake RPC only. Never sends or deletes a real message."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP = Path(__file__).resolve().parents[2]
CODE = (TOP / 'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/sms.js').read_text(encoding='utf-8')


def setup(browser):
    page = browser.new_page()
    page.set_content('<main></main>')
    page.evaluate('''code => {
        window.rows=[{id:'1000000001',status:'read',card:0,sim:'SIM1',peer:'10000',
            dir:'mt',time:'2026-10-24T12:00:00+08:00',preview:'original',revision:'a'}];
        window.result=()=>({total:rows.length,msgs:structuredClone(rows)});
        window.notices=[];window.sends=[];window.gates=[];
        window.M={injectCss(){},watchSms(){},localize(){},translate:s=>s,esc:s=>String(s??''),
            callSmsList:()=>Promise.resolve(result()),
            callSmsShow:()=>Promise.resolve({ok:1,text:'from: test\\n---\\nbody'}),
            callSmsSend:(...args)=>new Promise(resolve=>sends.push({args,resolve})),
            callSmsDel:()=>Promise.resolve({ok:0,error:'delete failed'}),
            confirmBox:()=>Promise.resolve(true),
            toast:(text,options)=>notices.push({text,options}),busy:(btn,on)=>btn.disabled=on};
        window.app=new Function('view','poll','M','L','E',code)(
            {extend:x=>x},{add(){}},M,
            {resource:()=>'',resolveDefault:p=>Promise.resolve(p).catch(()=>null)},
            tag=>document.createElement(tag));
        document.querySelector('main').appendChild(app.render());
    }''', CODE)
    page.wait_for_selector('.mud-conv')
    return page


def list_recovery(page):
    page.evaluate("M.callSmsList=()=>Promise.resolve({error:'temporary failure'});app.reload()")
    page.evaluate('M.callSmsList=()=>Promise.resolve(result());app.reload()')
    assert page.locator('.mud-conv').count() == 1, 'healthy unchanged response must restore list'
    page.evaluate("M.callSmsList=()=>Promise.reject(Error('transport failure'));app.reload()")
    assert page.locator('.mud-conv').count() == 1, 'transport failure must retain last good list'


def list_race(page):
    page.evaluate('''() => {
        M.callSmsList=()=>new Promise(resolve=>gates.push(resolve));
        app.reload();app.reload();
        const newest=result();newest.msgs[0].preview='newest';
        gates[1](newest);
    }''')
    page.wait_for_function("document.querySelector('.mud-conv .p').textContent==='newest'")
    page.evaluate('gates[0](result())')
    assert page.locator('.mud-conv .p').first.inner_text() == 'newest', 'late old list must not overwrite newer reply'


def clear_failure(page):
    page.locator('.mud-conv').click()
    page.wait_for_function("app.sel==='10000'")
    page.locator('#mud-sms-clear').click()
    page.wait_for_timeout(50)
    assert page.evaluate("app.sel==='10000'"), 'failed clear must preserve selected conversation'
    assert page.evaluate("notices.some(n=>n.options.type==='error')"), 'failed clear must report failure'


def duplicate_send(page):
    page.locator('#mud-sms-num').fill('10000')
    page.locator('#mud-sms-text').fill('first draft')
    page.evaluate('app.send();app.send()')
    assert page.evaluate('sends.length') == 1, 'pending send must not submit twice'
    page.locator('#mud-sms-text').fill('next draft')
    page.evaluate('sends[0].resolve({ok:1})')
    page.wait_for_function("!document.querySelector('#mud-sms-send').disabled")
    assert page.locator('#mud-sms-text').input_value() == 'next draft', 'send completion must not erase a newer draft'
    page.evaluate('app.send()')
    assert page.evaluate('sends.length') == 2
    page.evaluate("sends[1].resolve({ok:0,error:'send failed'})")
    page.wait_for_function("!document.querySelector('#mud-sms-send').disabled")
    assert page.locator('#mud-sms-text').input_value() == 'next draft', 'failed send must keep draft for retry'


def ime_enter(page):
    page.locator('#mud-sms-num').fill('10000')
    page.locator('#mud-sms-text').fill('输入法候选')
    page.evaluate("document.querySelector('#mud-sms-text').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}))")
    assert page.evaluate('sends.length') == 0, 'IME confirmation Enter must not send a message'


failures=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    for test in (list_recovery,list_race,clear_failure,duplicate_send,ime_enter):
        page=setup(browser)
        try:
            test(page)
            print('PASS:',test.__name__)
        except AssertionError as error:
            failures.append(test.__name__)
            print('FAIL:',test.__name__,str(error))
        finally:
            page.close()
    browser.close()
assert not failures, failures
