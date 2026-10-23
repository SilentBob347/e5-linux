"""Run the staged metadata helper in a real ucode VM, with private files only."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

TOP=Path(__file__).resolve().parents[2]
IMAGE=os.environ.get('E5_TEST_IMAGE','mu300-openwrt-base:25.12.5')


class Metadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Explicit existing image; never download an image or access hardware.
        subprocess.run(['docker','image','inspect',IMAGE],check=True,stdout=subprocess.DEVNULL)
        cls.source=runpy.run_path(str(TOP/'devices/t551m/infoscreen/stage.py'))['sources']()['api.uc']

    def test_ota_and_legacy_versions_in_full_staged_module(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'hotspot.uc').write_text('export const fixture = true;\n')
            (root/'ubus.uc').write_text('export function connect() { die("Unexpected ubus access"); };\n')
            (root/'uci.uc').write_text('export function cursor() { die("Unexpected UCI access"); };\n')
            source=self.source.replace("'/usr/libexec/unisoc-modem/hotspot.uc'","'/fixture/hotspot.uc'")
            source=source.replace("from 'ubus'", "from '/fixture/ubus.uc'")
            source=source.replace("from 'uci'", "from '/fixture/uci.uc'")
            source=source.replace("'/etc/unisoc-ota/current.json'","'/fixture/current.json'")
            source=source.replace("'/etc/e5/image-version'","'/fixture/image-version'")
            end=source.rindex('%}')
            source=source[:end]+"printf('%J', image_version());\n"+source[end:]
            (root/'api.uc').write_text(source,encoding='utf-8')
            cases=[(None,' legacy-1\n','legacy-1'),
                   ('{"version":"ota-2"}','legacy-1','ota-2'),
                   ('broken json','legacy-1','legacy-1'),
                   ('{"version":""}','legacy-1','legacy-1'),
                   ('{"version":3}','legacy-1','legacy-1'),
                   (None,None,None)]
            for ota,legacy,expected in cases:
                with self.subTest(ota=ota,legacy=legacy):
                    for name,value in (('current.json',ota),('image-version',legacy)):
                        path=root/name
                        if value is None:path.unlink(missing_ok=True)
                        else:path.write_text(value,encoding='utf-8')
                    result=subprocess.run(['docker','run','--rm','--network','none',
                        '-v',str(root)+':/fixture:ro',IMAGE,'ucode','-T','/fixture/api.uc'],
                        capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(result.stdout),expected)

    def test_error_envelope_is_not_rendered_as_empty_page(self):
        app=(TOP/'devices/t551m/infoscreen/base/app.js').read_text(encoding='utf-8')
        start=app.index('function pageRead(');end=app.index('\nasync function poll()',start)
        harness='''const assert=require('node:assert/strict');
const pageRequests=new Map();let data, marks=[];
function beginPageLoad(){return failed=>marks.push(failed);}
async function fetch(){return {ok:true,status:200,json:async()=>data};}
'''+app[start:end]+'''
(async()=>{
 data={error:'left-hand side is not a function'};
 await assert.rejects(pageRead('/api/settings/system',7));
 assert.equal(marks.pop(),true);assert.equal(pageRequests.size,0);
 data={items:[{id:'version',value:'legacy-1'}]};
 assert.equal((await pageRead('/api/settings/system',7)).items.length,1);
 assert.equal(marks.pop(),false);
 data={device:{image:'legacy-1'},error:'partial warning'};
 assert.equal((await pageRead('/api/advanced',6)).device.image,'legacy-1');
 assert.equal(marks.pop(),false);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        subprocess.run(['node','-e',harness],check=True,timeout=8)


if __name__=='__main__':unittest.main()
