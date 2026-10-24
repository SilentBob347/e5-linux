"""Exercise real staged UI timers and slow reads with Chromium's virtual clock.

No device access. Uses the same --fixtures/--webroot inputs as screen tests.
"""
import argparse
from datetime import datetime, timezone
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
    state['screen'].update(idle=0, lock_enabled=False, clock_seconds=False, awake=True)
    state['tz_offset'] = 0
    traffic_reads = []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
            browser = p.chromium.launch(**({'executable_path': str(chrome)} if chrome.exists() else {}))
            page = browser.new_page(viewport={'width': 320, 'height': 480})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def api(route):
                path = urlsplit(route.request.url).path
                if route.request.method == 'POST':
                    if path == '/api/backlight':
                        state['screen']['awake'] = route.request.post_data_json.get('level', 0) > 0
                    result = {'ok': True}
                else:
                    if path == '/api/traffic':
                        traffic_reads.append(path)
                    result = fixtures.get(path, {})
                route.fulfill(json=result)

            page.route('**/api/**', api)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_function('typeof last !== "undefined" && last !== null && pollRequest === null')
            page.clock.install(time=datetime(2026, 10, 24, 12, 33, 59, tzinfo=timezone.utc))
            page.clock.pause_at(datetime(2026, 10, 24, 12, 34, tzinfo=timezone.utc))
            page.evaluate('''() => {
                clearTimeout(pollTimer);
                window.clockTicks = 0;
                const clock = T551M.clock;
                T551M.clock = () => { ++clockTicks; clock(); };
                tickClock(); clockTicks = 0;
            }''')
            page.clock.run_for(59000)
            assert page.evaluate('clockTicks') == 0, 'minute clock must not wake every second'
            page.clock.run_for(1000)
            assert page.evaluate('clockTicks') == 1
            assert page.locator('#lock-time').text_content() == '12:35'
            page.evaluate('last.screen.clock_seconds = true; tickClock(); clockTicks = 0')
            page.clock.run_for(2100)
            assert page.evaluate('clockTicks') == 2, 'seconds setting must retain second ticks'

            page.evaluate('showPage(P.traffic)')
            page.wait_for_function('!pageRequests.size')
            page.evaluate('setBlank(true); clockTicks = 0')
            page.evaluate('powerQueue')
            reads_before = len(traffic_reads)
            assert page.evaluate('clockTimer === null && advTimer === null')
            page.clock.run_for(65000)
            assert page.evaluate('clockTicks') == 0, 'dark screen must have no clock wakeups'
            assert len(traffic_reads) == reads_before, 'hidden page must not refresh'
            page.evaluate('setBlank(false)')
            page.wait_for_function('pollRequest === null && !blank')
            assert page.evaluate('clockTimer !== null && advTimer !== null')
            assert page.locator('#lock-time').text_content() == '12:36', 'wake must paint current time'

            # External backlight changes use the same timer lifecycle.
            page.clock.run_for(1100)
            state['screen']['awake'] = False
            page.evaluate('poll()')
            assert page.evaluate('blank && clockTimer === null && advTimer === null')
            state['screen']['awake'] = True
            page.evaluate('poll()')
            assert page.evaluate('!blank && clockTimer !== null && advTimer !== null')

            # A slow read plus a burst of refresh/wake events: only one in
            # flight, one fresh follow-up, then exactly one periodic chain.
            page.evaluate('''() => {
                clearTimeout(pollTimer);
                window.statusReads = [];
                window.originalFetch = fetch;
                window.fetch = (url, options) => url === '/api/status' ?
                    new Promise(resolve => statusReads.push(value =>
                        resolve(new Response(JSON.stringify(value))))) : originalFetch(url, options);
                poll();
                for (let i = 0; i < 20; ++i) poll();
                setBlank(true); setBlank(false);
            }''')
            assert page.evaluate('statusReads.length') == 1
            page.evaluate('(value) => { const read = pollRequest; statusReads[0](value); return read; }', state)
            page.clock.run_for(1)
            assert page.evaluate('statusReads.length') == 2
            page.evaluate('(value) => { const read = pollRequest; statusReads[1](value); return read; }', state)
            for expected in (3, 4):
                page.clock.run_for(2000)
                assert page.evaluate('statusReads.length') == expected, 'duplicate periodic poll chain'
                page.evaluate('([index, value]) => { const read = pollRequest; statusReads[index](value); return read; }', [expected - 1, state])

            # A failed status read must release the guard and remain retryable.
            page.evaluate('fetch = () => Promise.reject(new Error("offline")); poll()')
            assert page.evaluate('pollRequest === null')
            page.evaluate('fetch = originalFetch; poll()')
            assert page.evaluate('pollRequest === null && last !== null')

            # Completion of a page read started before sleep must not replace
            # a timer belonging to a later page/wake generation.
            page.evaluate('''() => {
                clearTimeout(pollTimer);
                window.oldTraffic = loadTraffic;
                loadTraffic = () => new Promise(resolve => window.finishTraffic = resolve);
                page = P.traffic;
                schedulePageRefresh();
            }''')
            page.clock.run_for(30000)
            page.evaluate('''() => {
                setBlank(true); setBlank(false);
                window.newPageTimer = advTimer;
                finishTraffic();
            }''')
            assert page.evaluate('advTimer === newPageTimer'), 'stale page read replaced the new timer'
            page.evaluate('loadTraffic = oldTraffic; showPage(P.overview)')

            # Retain notification wake and the original 5-second dark cadence.
            page.evaluate('setBlank(true)')
            page.evaluate('powerQueue')
            state['notifications'] = [{'plugin': 'test', 'id': 'wake', 'title': 'Wake', 'wake': True}]
            page.evaluate('poll()')
            assert page.evaluate('!blank'), 'notification wake must survive timer suspension'
            assert page.evaluate('POLL_BLANK === 5000 && POLL_AWAKE === 2000')
            assert not errors, errors
            browser.close()
            print('PASS: minute/second clocks, dark/wake/external power, page timer races, coalesced reads, failure recovery, notification wake')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
