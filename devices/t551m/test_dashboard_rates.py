"""CLI compatibility clients of the resident snapshot/rates implementation.

Counter/TTL behaviour is exercised by openwrt/tests/native-dashboard.py.
"""
import json
import os
from pathlib import Path
import subprocess
import unittest

SOURCE=(Path(__file__).resolve().parents[2]/'openwrt/luci-app-t551m/root/usr/libexec/rpcd/mu300dash').read_text()
def function(name):
    start=SOURCE.index(name+'() {');end=SOURCE.index('\n}',start)+2
    return SOURCE[start:end]

class RatesTest(unittest.TestCase):
    def test_compatibility_calls_preserve_slot_and_method(self):
        for function_name,arg,method in [('m_rates','','rates'),('m_status','','status'),('m_status','cells','cells')]:
            code="""ubus() { printf '%s\\n' "$@"; }
"""+function(function_name)+'\n'+function_name+' '+arg
            result=subprocess.run(['sh','-c',code],env=dict(os.environ,MU300_SIM_SLOT='1'),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('e5status\n'+method+'\n',result.stdout)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1]),{'slot':'1'})

    def test_native_failure_is_visible_without_old_collector_takeover(self):
        for name in ('m_rates','m_status'):
            code='ubus() { return 1; }\n'+function(name)+'\n'+name
            r=subprocess.run(['sh','-c',code],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('error',json.loads(r.stdout))
            self.assertNotIn('setsid',function(name))

if __name__=='__main__':unittest.main()
