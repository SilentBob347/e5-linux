"""Shared kernel prepare contracts and production C against emulated MMIO."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class KernelPrepare(unittest.TestCase):
    def test_old_kernel_config_is_rejected_before_release_assembly(self):
        top=HERE.parents[1]
        check=runpy.run_path(str(top/'upstream/check-container-support.py'))['config_check']
        source=(top/'upstream/e5-mainline.config').read_text()
        with tempfile.TemporaryDirectory() as td:
            config=Path(td)/'config';config.write_text(source)
            check(config)
            config.write_text(source.replace('CONFIG_UCLAMP_TASK=y','CONFIG_UCLAMP_TASK=n'))
            with self.assertRaisesRegex(ValueError,'UCLAMP_TASK'):check(config)

    def test_usb_lifetime_and_module_staging_are_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name in ('f_ncm.c','f_rndis.c'):
                p=root/'drivers/usb/gadget/function'/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('void unbind(void) {\n\tkfree(f->os_desc_table);\n\tf->os_desc_n = 0;\n}\n')
            base=root/'drivers/soc/sprd';base.mkdir(parents=True)
            for name in ('Makefile','Kconfig'):(base/name).write_text('')
            apply=runpy.run_path(str(HERE/'boot-optimization.py'))['apply']
            apply(root);before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            apply(root);after={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            for name in ('f_ncm.c','f_rndis.c'):
                self.assertIn('kfree(f->os_desc_table);\n\tf->os_desc_table = NULL;',
                              (root/'drivers/usb/gadget/function'/name).read_text())
            self.assertEqual((base/'ums9620_lpintc.c').read_bytes(),(HERE/'ums9620_lpintc.c').read_bytes())

    def test_real_lpintc_source_lifecycle_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);include=root/'linux';include.mkdir()
            for name in ('bits','io','module','of','of_address','spinlock','syscore_ops','workqueue'):
                (include/(name+'.h')).touch()
            binary=root/'lpintc'
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                '-Wno-unused-function','-I',td,str(HERE/'tests/lpintc-harness.c'),'-o',str(binary)],check=True)
            for case in ('lifecycle','clock-off','wrong-soc','no-gic','all-clocks-off','bad-gic','bad-gate','partial-map'):
                p=subprocess.run([str(binary),case],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'OK')


if __name__=='__main__':unittest.main()
