"""Real staged UI: native scroll, gesture routing, frame batching and DOM reuse."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--webroot', type=Path, required=True)
    args = parser.parse_args()
    fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
    state = fixtures['/api/status']
    state['screen'].update(idle=0, lock_enabled=False, donate_seen=True,
                           desktop_wallpaper='none', lock_wallpaper='none')

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
            browser = p.chromium.launch(**({'executable_path': str(chrome)} if chrome.exists() else {}))
            for width, height in [(320, 480), (480, 800), (720, 1280)]:
                page = browser.new_page(viewport={'width': width, 'height': height}, has_touch=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))

                def api(route):
                    path = urlsplit(route.request.url).path
                    result = {'ok': True} if route.request.method == 'POST' else fixtures.get(path, {})
                    route.fulfill(json=result)

                page.route('**/api/**', api)
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.wait_for_function('typeof last !== "undefined" && last !== null && !T551M.isLocked()')
                page.wait_for_timeout(500)
                for language in ['zh', 'en']:
                    page.evaluate('(v) => { lang=v; applyLang(); T551M.status(last); }', language)
                    # Decorations must not turn equal render inputs into a list
                    # rebuild, losing focus and scroll position on every refresh.
                    page.evaluate('''() => {
                        showPage(P.settings);
                        const root=document.getElementById('st-view');
                        setHTML('st-view', '<button class="strow">A &amp; B</button>');
                        window.keptRow=root.firstElementChild;
                        keptRow.appendChild(document.createElement('i'));
                        keptRow.focus({preventScroll:true});
                        for(let i=0;i<30;i++) setHTML('st-view', '<button class="strow">A &amp; B</button>');
                    }''')
                    assert page.evaluate('keptRow === document.querySelector("#st-view button") && document.activeElement === keptRow')
                    assert page.evaluate('''() => {
                        const node=document.getElementById('bar-bat').querySelector('b');
                        const observer=new MutationObserver(()=>{}); observer.observe(node,{attributes:true});
                        for(let i=0;i<30;i++) setStyle(node,'transform',node.style.transform);
                        const changed=observer.takeRecords().length; observer.disconnect(); return changed===0;
                    }'''), 'unchanged status repaints the battery'
                    page.evaluate('''() => {
                        setHTML('st-view', '<div style="height:2000px;flex:none">Scroll test</div>');
                        window.scrollPage=pages[P.settings];
                    }''')
                    page.wait_for_timeout(350)
                    assert page.evaluate("getComputedStyle(scrollPage).touchAction === 'pan-y'")
                    assert page.evaluate("pages.filter(p=>getComputedStyle(p).display!=='none').length") == 1
                    session = page.context.new_cdp_session(page)

                    def touch(kind, x, y):
                        session.send('Input.dispatchTouchEvent', {'type': kind,
                                     'touchPoints': [] if kind in ['touchEnd', 'touchCancel'] else
                                     [{'x': x, 'y': y, 'id': 0}]})

                    touch('touchStart', width/2, height*.72)
                    for i in range(1, 9):
                        touch('touchMove', width/2, height*.72-i*15)
                        page.wait_for_timeout(16)
                    touch('touchEnd', 0, 0)
                    page.wait_for_timeout(180)
                    assert page.evaluate('page === P.settings && scrollPage.scrollTop > 40'), 'native vertical scrolling failed'
                    # A drag starting vertically cannot become a page swipe as
                    # the finger later arcs sideways. A fresh horizontal can.
                    page.evaluate('''() => {
                        window.fireTouch=(type,x,y)=>{
                            const e=new Event(type,{bubbles:true,cancelable:true});
                            const points=[{clientX:x,clientY:y}];
                            Object.defineProperties(e,{touches:{value:type==='touchend'||type==='touchcancel'?[]:points},changedTouches:{value:points}});
                            pages[page].dispatchEvent(e);
                        };
                        fireTouch('touchstart',180,280); fireTouch('touchmove',180,260);
                        fireTouch('touchmove',70,255); fireTouch('touchend',70,255);
                    }''')
                    assert page.evaluate('page === P.settings')
                    page.evaluate("fireTouch('touchstart',180,280); fireTouch('touchmove',70,280); fireTouch('touchend',70,280)")
                    assert page.evaluate('page !== P.settings')
                    page.wait_for_timeout(350)
                    # Coalesce many lock input samples into exactly one frame.
                    page.evaluate('''() => {
                        document.getElementById('mobile-lock').click();
                        window.realRAF=requestAnimationFrame; window.realCancel=cancelAnimationFrame;
                        window.frames=new Map(); window.frameId=0;
                        window.requestAnimationFrame=fn=>{const id=++frameId;frames.set(id,fn);return id;};
                        window.cancelAnimationFrame=id=>frames.delete(id);
                        fireTouch('touchstart',160,innerHeight-40);
                        for(let i=1;i<=8;i++) fireTouch('touchmove',160,innerHeight-40-i*8);
                    }''')
                    assert page.evaluate('frames.size') == 1
                    page.evaluate('''() => { const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn()); }''')
                    assert page.evaluate("document.getElementById('mobile-lockscreen').style.transform.includes('-64px')")
                    page.evaluate("fireTouch('touchmove',160,innerHeight-120);fireTouch('touchcancel',160,innerHeight-120)")
                    assert page.evaluate('frames.size === 0 && T551M.isLocked()')
                    page.evaluate('''() => {
                        window.requestAnimationFrame=realRAF; window.cancelAnimationFrame=realCancel;
                        setBlank(true);
                    }''')
                    touch('touchStart', width/2, height*.7)
                    touch('touchEnd', 0, 0)
                    assert page.evaluate('blank && T551M.isLocked()'), 'touch woke a dark screen'
                    page.evaluate('setBlank(false)')
                    page.wait_for_timeout(500)
                    assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print('PASS: 6 viewport/language cases; native scroll, axis lock, DOM reuse, frame coalescing, cancel and dark-screen guards')


if __name__ == '__main__':
    main()
