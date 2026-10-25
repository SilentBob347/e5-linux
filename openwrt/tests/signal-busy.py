"""Actual collector admission and RPC response; private directories, no AT."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
APP=TOP/'openwrt/luci-app-t551m/root/usr/libexec'

class SignalBusy(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def sh(self,source,**env):
        return subprocess.run(['sh','-c',source],capture_output=True,text=True,env=dict(os.environ,**{k:str(v) for k,v in env.items()}),timeout=5)
    def test_fast_busy_is_distinct_from_full_background_overlap(self):
        source=(APP/'unisoc-modem/cell').read_text()
        admission=source[source.index('alive() {'):source.index('# ------------------------------------------------------------------- identity')]
        pool=self.root/'pool';(pool/'nr6').mkdir(parents=True);(pool/'nr7').mkdir()
        for mode,code in [('fast',75),('full',0)]:
            out=self.root/mode;out.mkdir()
            result=self.sh(admission,MODE=mode,DIR=out,MU300_DASH_POOL_DIR=pool)
            self.assertEqual(result.returncode,code,result.stderr)
            self.assertFalse((out/'collect.lck').exists())
    def test_rpc_reports_busy_without_cached_signal_and_cleans_private_output(self):
        source=(APP/'rpcd/mu300dash').read_text()
        function=source[source.index('m_signal() {'):source.index('\nm_act() {')]
        gate=self.root/'applying';function=function.replace('/run/unisoc-modem-lock-apply',str(gate))
        dash=self.root/'dash';dash.mkdir();cell=dash/'cell'
        output=self.root/'output';output.mkdir()
        cached=self.root/'sig.json';cached.write_text('{"ts":1,"old":true}')
        for code,expected in [(75,{'busy':1,'error':'busy'}),(1,{'error':'live signal read failed'})]:
            cell.write_text('#!/bin/sh\nexit '+str(code)+'\n');cell.chmod(0o755)
            result=self.sh(function+'\nm_signal',DASH=dash,DIR=output,SIGF=cached)
            self.assertEqual(json.loads(result.stdout),expected)
            self.assertEqual(list(output.iterdir()),[])
        gate.mkdir();cell.write_text('#!/bin/sh\necho should-not-run\n');cell.chmod(0o755)
        result=self.sh(function+'\nm_signal',DASH=dash,DIR=output,SIGF=cached)
        self.assertEqual(json.loads(result.stdout),{'busy':1,'error':'busy'})

if __name__=='__main__':unittest.main()
