// Run against staged settings/api sources; all power commands are mocked.
'use strict';
import { readfile } from 'fs';
function check(value, why) { if (!value) die(why); }
let settings_source = readfile(ARGV[0]), api_source = readfile(ARGV[1]);
let calls = [], failed = null, reads = 0;
let ctx = { run: cmd => { push(calls, cmd); return failed && index(cmd, failed) >= 0 ? 1 : 0; } };
let start = index(settings_source, 'function queue_power(');
let end = index(settings_source, 'const usb_cat =', start);
check(start >= 0 && end > start, 'Missing system power backend');
let make_system = loadstring('return function(ctx) { const L = (zh,en) => ({zh,en}); ' + substr(settings_source, start, end-start) + '; return system_cat; };', {raw_mode:true})();
let c = make_system(ctx);
// An accepted operation must reply even when subsequent category reads fail.
let post = true, b;
function category(id) { return id == 'system' ? c : null; }
function read_body() { return b; }
function settings_items() { reads++; die('Backend has already shut down'); }
function reply_json(status, body) { return {status, body}; }
let branch_start = index(api_source, '\t\tlet sm = match(path,');
let branch_end = index(api_source, "\t\tif (!post && path == '/devices')", branch_start);
check(branch_start >= 0 && branch_end > branch_start, 'Missing settings dispatcher');
let dispatch = loadstring('return function(category, read_body, settings_items, reply_json, post) { return function(path, env) { ' + substr(api_source, branch_start, branch_end-branch_start) + ' }; };', {raw_mode:true})()(category, read_body, settings_items, reply_json, post);
for (let action in ['reboot','poweroff','android_once']) {
    calls = []; reads = 0; failed = null; b = {id:action};
    let result = dispatch('/settings/system', {});
    check(result.status == 200 && result.body.ok && result.body.power_action == action, 'Accepted power action reported failure');
    check(reads == 0, 'Power request read category after scheduling');
    let command = action == 'poweroff' ? 'poweroff' : 'reboot';
    check(calls[-1] == `(sleep 2; ${command}) </dev/null >/dev/null 2>&1 &`, 'Shutdown command or detachment changed');
    if (action == 'android_once') check(calls[0] == 'e5-next-boot android >/dev/null 2>&1', 'Android must be selected before reboot');
}
for (let failure in ['command -v','(sleep 2;','e5-next-boot']) {
    calls = []; reads = 0; failed = failure; b = {id:failure == 'e5-next-boot' ? 'android_once' : 'reboot'};
    let result = dispatch('/settings/system', {});
    check(result.status == 400 && !result.body.ok && type(result.body.error) == 'string', 'Real scheduling failure hidden');
    check(reads == 0, 'Failure read departing backend');
    if (failure != '(sleep 2;') check(!length(filter(calls, cmd => index(cmd, '(sleep 2;') >= 0)), 'Reboot scheduled after failed prerequisite');
}
failed = null; calls = []; b = {id:'reboot;poweroff'};
let invalid = dispatch('/settings/system', {});
check(invalid.status == 400 && !length(calls), 'Unknown action reached shell');
print('PASS: three power actions acknowledge without readback; launch/slot failures and invalid actions remain failures; no real power commands executed\n');
