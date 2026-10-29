#!/usr/bin/env python3
"""Check the explicitly deployed read-only-storage Changxing60 RAM trial.

Optional exercises restore the original PA, core and policy settings. They do
not initiate calls, send messages or write partitions/NV. This is not an
installer or a substitute for actual audio/USB hardware acceptance.
"""
import argparse
import json
from pathlib import Path
import shlex
import paramiko

EXERCISE = r'''
import json, subprocess, time
from pathlib import Path
def run(args, payload=None):
    p = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                       text=True, capture_output=True, timeout=25, check=True)
    return p.stdout
def cpu(payload=None):
    return json.loads(run(['/usr/libexec/unisoc-modem/cpu-control',
                           'apply' if payload is not None else 'get'], payload))
before = cpu()
assert before['ok']
policy = before['policies'][0]
saved = {k: policy[k] for k in ('id', 'min', 'max', 'governor')}
try:
    low = policy['frequencies'][1]
    result = cpu({'changes': {'policies': [{'id':policy['id'], 'min':policy['min'],
                         'max':low, 'governor':'powersave'}]}})
    assert result['ok'], result
    p = result['policies'][0]
    assert p['max'] == low and p['effective_max'] <= low and p['governor'] == 'powersave'
    print('policy frequency/governor: accepted')
finally:
    assert cpu({'changes': {'policies':[saved]}})['ok']
after = cpu()['policies'][0]
assert all(after[k] == saved[k] for k in saved)
print('policy: restored')
zone = next(z for z in before['zones'] if z['name'] == 'soc-thmzone')
trips = [t for t in zone['trips'] if t['type'] == 'passive' and t['writable']]
saved_trips = [{'zone':zone['name'], 'trip':t['id'], 'temp':t['temp']} for t in trips]
try:
    changed = [dict(t, temp=t['temp']-1000) for t in saved_trips]
    result = cpu({'changes': {'thermal':changed}})
    assert result['ok'], result
    actual = next(z for z in result['zones'] if z['name']==zone['name'])
    for t in changed:
        assert next(x for x in actual['trips'] if x['id']==t['trip'])['temp']==t['temp']
    assert next(t for t in actual['trips'] if t['type']=='critical') == next(
        t for t in zone['trips'] if t['type']=='critical')
    print('passive thermal thresholds: accepted; critical unchanged')
finally:
    assert cpu({'changes': {'thermal':saved_trips}})['ok']
print('thermal: restored')
cores_tool = '/usr/libexec/unisoc-modem/cpu-cores'
state = json.loads(run([cores_tool, 'get']))
assert state['ok'] and not state['persistent'], 'RAM fixture must have no user core profile'
original = [{k:c[k] for k in ('id', 'online')} for c in state['cores']]
try:
    target = [dict(c) for c in original]
    core = next(c for c in target if c['id'] == 1)
    assert core['online']
    core['online'] = False
    result = json.loads(run([cores_tool, 'apply'], {'cores':target, 'persist':False}))
    assert result['ok'] and not next(c for c in result['cores'] if c['id']==1)['online']
    print('CPU1: offline accepted')
finally:
    result = json.loads(run([cores_tool, 'apply'], {'cores':original, 'persist':False}))
    assert result['ok']
    assert [{k:c[k] for k in ('id','online')} for c in result['cores']] == original
print('cores: restored')
amixer = ['amixer', '-c', '0']
control = 'name=aw87xxx_profile_switch_0'
old = run(amixer + ['cget', control]).rsplit('values=', 1)[1].strip()
try:
    for mode in ('Receiver', 'Music'):
        result = run(amixer + ['cset', control, mode])
        wanted = 'values=' + ('2' if mode == 'Receiver' else '0')
        assert wanted in result, result
        time.sleep(.3)
        print('factory PA mode: ' + mode + ' accepted')
finally:
    assert 'values='+old in run(amixer + ['cset', control, old])
print('PA: restored')
print('RESTORATION COMPLETE; no call or message initiated')
'''

KEEP_RUNNING = r'''
import json, os, signal
from pathlib import Path
state = json.loads(Path('/run/e5-voice-audio/status.json').read_text())
assert state['available'] and state['observer_ready'] and state['error'] is None
offsets = [int(p.read_text()) for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_voltage_offset')]
assert len(offsets) == 3 and offsets == [0, 0, 0], 'Do not retain the positive-offset experiment'
ready = Path('/tmp/probe-watchdog.ready')
guards = []
for process in Path('/proc').iterdir():
    if not process.name.isdecimal():
        continue
    try:
        if os.readlink(process/'exe') == '/usr/libexec/e5-ram-watchdog':
            guards.append(process)
    except FileNotFoundError:
        pass
assert len(guards) == 1, 'Expected exactly one owned lab return timer'
process = guards[0]
pid = int(process.name)
args = (process/'cmdline').read_bytes().split(b'\0')
assert args[1] == b'480'
os.kill(pid, signal.SIGTERM)
ready.unlink(missing_ok=True)
print('Stopped only the owned 480-second lab return timer; original Android fallback remains selected')
'''

VOICE_METADATA = r'''
import json, subprocess, re
from pathlib import Path
routes = json.loads(Path('/usr/share/e5/voice-routes.json').read_text())
names = set()
for group in routes.values():
    names.update(group if isinstance(group, (dict,list)) else [])
missing = []
metadata = {}
for name in sorted(names):
    r = subprocess.run(['amixer','-c','0','cget','name='+name], text=True,
                        capture_output=True, timeout=3)
    if r.returncode:
        missing.append(name)
    else:
        metadata[name] = r.stdout
assert not missing, missing
for group in ('ROUTES','CODEC_IIS','RECEIVER_AOL','SPEAKER'):
    for name, value in routes[group].items():
        info = metadata[name]
        choices = re.findall(r"Item #\d+ '([^']*)'", info)
        fields = str(value).split(',')
        count = int(re.search(r'values=(\d+)', info).group(1))
        assert len(fields) in (1, count), (name, value, count)
        for field in fields:
            if choices and field in choices:
                continue
            if 'type=BOOLEAN' in info and field in ('on','off'):
                continue
            number = int(field, 0)
            if choices:
                assert 0 <= number < len(choices), (name, value)
            bounds = re.search(r'min=(-?\d+),max=(-?\d+)', info)
            if bounds:
                minimum, maximum = int(bounds[1]), int(bounds[2])
                # Vendor virtual-command controls (notably VBC_VOLUME) expose
                # UINT_MAX as signed max=-1. That is not a usable gain bound.
                assert number >= minimum, (name, value)
                if maximum >= minimum:
                    assert number <= maximum, (name, value)
assert routes['RECEIVER_AOL']['aw87xxx_profile_switch_0'] == 'Receiver'
assert routes['SPEAKER']['aw87xxx_profile_switch_0'] == 'Music'
print(str(len(names))+' native voice mixer controls available; distinct factory PA profiles')
'''

DISPLAY_EXERCISE = r'''
import json, time, urllib.request
from pathlib import Path
lights = list(Path('/sys/class/backlight').iterdir())
assert len(lights) == 1
light = lights[0]
old = int((light/'brightness').read_text())
def set_level(level):
    data = json.dumps({'level':level}).encode()
    request = urllib.request.Request('http://127.0.0.1:8088/api/backlight', data=data,
                                    headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=5) as r:
        result = json.load(r)
    assert result.get('ok'), result
    time.sleep(1)
    assert int((light/'brightness').read_text()) == level
try:
    for level in (120, 0, 120, 0):
        set_level(level)
finally:
    set_level(old)
print('two screen wake/sleep cycles through the production API; original brightness restored')
'''

GATEWAY_CONFIG = r'''
import json, subprocess, urllib.request
from pathlib import Path
text = '\n'.join(p.read_text() for p in Path('/var/etc').glob('dnsmasq.conf.*'))
assert '192.168.9.10,192.168.9.200,255.255.255.0,12h' in text
for option in ('3', '6'):
    assert 'dhcp-option=tag:cx60probe,'+option+'\n' in text+'\n'
assert 'dhcp-host=02:50:00:00:60:02,set:cx60probe,' in text
assert subprocess.check_output(['uci','-q','get','network.lan.ip6assign'], text=True).strip() == '64'
rules = subprocess.check_output(['nft','list','chain','inet','fw4','srcnat_wan'], text=True)
assert 'masquerade' in rules
wan = json.loads(subprocess.check_output(['ubus','call','network.interface.wan','status'], text=True))
assert wan['up'] and wan['ipv4-address'] and wan['dns-server']
with urllib.request.urlopen('http://127.0.0.1:8088/api/status', timeout=10) as r:
    state = json.load(r)
assert isinstance(state, dict) and state.get('screen')
print('normal hotspot pool, PC-only gateway/DNS exclusion, IPv6 /64 configuration, NAT, WAN and screen API verified')
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='192.168.9.1')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--exercise', action='store_true')
    p.add_argument('--keep-running', action='store_true',
                   help='After checks, stop only the lab return timer for the user-requested overnight RAM test')
    a = p.parse_args()
    if a.out.exists():
        raise ValueError('Retain previous diagnostic output')
    c = paramiko.SSHClient()
    # The temporary, physically connected RAM fixture has a freshly generated
    # host key, root/root and no persistent storage. Never use this for releases.
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, username='root', password='root', timeout=5,
              allow_agent=False, look_for_keys=False)
    report = {}
    def command(label, text, timeout=30):
        _, out, err = c.exec_command(text, timeout=timeout)
        result = {'stdout':out.read().decode(errors='replace'),
                  'stderr':err.read().decode(errors='replace'),
                  'exit':out.channel.recv_exit_status()}
        report[label] = result
        if result['exit']:
            raise RuntimeError(label + ': ' + result['stderr'] + result['stdout'])
        return result['stdout']
    try:
        identity = command('identity', 'cat /etc/e5/device-profile /etc/e5/ram-probe; findmnt -n -o FSTYPE /')
        if identity.splitlines() != ['changxing60', 'changxing60', 'tmpfs']:
            raise ValueError('Only use with the own RAM fixture')
        command('cpu', '/usr/libexec/unisoc-modem/cpu-control get')
        if a.exercise:
            command('controls', 'python3 -c ' + shlex.quote(EXERCISE), timeout=100)
            command('display', 'python3 -c ' + shlex.quote(DISPLAY_EXERCISE), timeout=30)
        command('nv', '/opt/e5/t551m-nv-verify')
        command('usb', '/usr/libexec/unisoc-modem/device-usb get')
        command('charge', '/usr/libexec/e5-charge status')
        command('wireless', 'ubus call network.wireless status')
        command('wan', 'ubus call network.interface.wan status')
        command('gateway', 'python3 -c ' + shlex.quote(GATEWAY_CONFIG))
        command('audio', 'test -e /run/e5-audio.ready && cat /run/e5-voice-audio/status.json')
        command('voice_metadata', 'python3 -c ' + shlex.quote(VOICE_METADATA), timeout=60)
        command('bluetooth', 'bluetoothctl show')
        command('warnings', 'dmesg | tail -160')
        if a.keep_running:
            command('keep_running', 'python3 -c ' + shlex.quote(KEEP_RUNNING))
    finally:
        c.close()
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RAM controls checked; receipt: ' + str(a.out))


if __name__ == '__main__':
    main()
