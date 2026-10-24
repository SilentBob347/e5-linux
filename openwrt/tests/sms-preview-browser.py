"""Exercise the shipped SMS view with changing multipart messages and fake RPC."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP = Path(__file__).resolve().parents[2]
SOURCE = TOP / 'openwrt/luci-app-t551m/htdocs/luci-static/resources/view/mu300/sms.js'


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content('<main></main>')
    page.evaluate('''code => {
        window.rows = [{id:'1000000001', status:'read', card:0, sim:'SIM1',
            peer:'10000', dir:'mt', time:'2026-10-24T12:00:00+08:00',
            preview:':00 fragment', revision:'first'}];
        window.requests = [];
        window.M = {
            injectCss(){}, watchSms(){}, localize(){}, translate:s=>s,
            esc:s=>String(s ?? '').replace(/[&<>"']/g,c=>
                ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
            callSmsList:()=>Promise.resolve({total:rows.length, msgs:rows}),
            callSmsShow:id=>new Promise(resolve=>requests.push({id,resolve}))
        };
        const L={resource:()=>'', resolveDefault:p=>Promise.resolve(p).catch(()=>null)};
        const E=tag=>document.createElement(tag);
        window.app=new Function('view','poll','M','L','E',code)(
            {extend:x=>x},{add(){}},M,L,E);
        document.querySelector('main').appendChild(app.render());
        window.reply=(index,body)=>requests[index].resolve({ok:1,text:'from: test\\n---\\n'+body});
        window.change=values=>{Object.assign(rows[0],values);return app.reload();};
    }''', SOURCE.read_text(encoding='utf-8'))
    page.wait_for_selector('.mud-conv')
    page.locator('.mud-conv').click()
    page.wait_for_function('requests.length===1')
    page.evaluate("reply(0, 'first incomplete body')")
    page.wait_for_function("document.querySelector('.bd').textContent==='first incomplete body'")
    page.evaluate("change({preview:'complete message', revision:'second'})")
    assert page.locator('.mud-conv .p').first.inner_text() == 'complete message', 'same ID must refresh corrected preview'
    page.wait_for_function('requests.length===2')
    page.evaluate("reply(1, 'complete message with all parts')")
    page.wait_for_function("document.querySelector('.bd').textContent==='complete message with all parts'")

    # A later fragment can change only the tail, beyond the 100-character preview.
    page.evaluate("change({revision:'third'})")
    page.wait_for_function('requests.length===3')
    page.evaluate("reply(2, 'complete message with corrected tail')")
    page.wait_for_function("document.querySelector('.bd').textContent.endsWith('corrected tail')")
    # No-op polls must preserve the DOM and avoid fetching the full body again.
    page.evaluate("window.bubble=document.querySelector('.mud-bub'); app.reload()")
    assert page.evaluate("bubble===document.querySelector('.mud-bub') && requests.length===3")
    page.evaluate("change({status:'unread'})")
    assert page.evaluate('requests.length===3'), 'read status must not invalidate body cache'

    # Two body reads finish out of order. An old version must not poison the cache.
    page.evaluate("change({preview:'older fragment', revision:'fourth'})")
    page.wait_for_function('requests.length===4')
    page.evaluate("change({preview:':0 is actual text <b>&', revision:'fifth'})")
    page.wait_for_function('requests.length===5')
    page.evaluate("reply(4, ':0 is actual text <b>& full body')")
    page.wait_for_function("document.querySelector('.bd').textContent.endsWith('full body')")
    page.evaluate("reply(3, 'stale fragment body')")
    page.evaluate("change({status:'read'})")
    assert page.locator('.bd').inner_text() == ':0 is actual text <b>& full body'
    assert page.locator('.mud-conv .p').first.inner_text() == ':0 is actual text <b>&'
    assert page.locator('.bd b,.mud-conv .p b').count() == 0
    page.evaluate("rows=[];app.reload()")
    page.wait_for_selector('.mud-sms-list-empty')
    assert not errors, errors
    browser.close()
print('PASS: corrected preview, multipart tail, no-op poll, read status, stale replies and literal :0 text')
