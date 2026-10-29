"""Run the real pre-write profile/geometry guard against temporary files."""
from pathlib import Path
import subprocess
import tempfile
import unittest

TOP = Path(__file__).resolve().parents[2]


class UpdateProfile(unittest.TestCase):
    def guard(self, installed, source, target, cid='bound', size='4096'):
        text=(TOP/'boot/part-update.sh').read_text()
        start=text.index('    SOURCE_PROFILE=${SOURCE_PROFILE:-$PROFILE}')
        stop=text.index('    # Copy EVERY payload',start)
        guard=text[start:stop]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);etc=root/'etc/e5';etc.mkdir(parents=True)
            (etc/'device-profile').write_text(installed+'\n');(etc/'part-root').touch()
            script='''
storage_update_id() { echo bound; }
blockdev() { echo 4096; }
umount() { :; }
part_fail() { echo "STOP: $*"; }
run_guard() {
    VERSION=1; CID=$1; ROOT_BYTES=$2; RAW_BYTES=2048
    SOURCE_PROFILE=$3; PROFILE=$4; mp=$5; KIND=part; disk=fixture; dev=fixture
'''+guard+'''
    echo VERIFIED
}
run_guard "$@"
'''
            return subprocess.run(['sh','-c',script,'fixture',cid,size,source,target,str(root)],
                                  capture_output=True,text=True)

    def test_old_same_model_request_still_works(self):
        result=self.guard('e5','','e5')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('VERIFIED',result.stdout)

    def test_distinct_source_and_target_do_not_disable_identity_check(self):
        result=self.guard('e5','e5','m8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('VERIFIED',result.stdout)
        for installed,cid,size in [('t551m','bound','4096'),('e5','other','4096'),('e5','bound','8192')]:
            with self.subTest(installed=installed,cid=cid,size=size):
                result=self.guard(installed,'e5','m8',cid,size)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn('VERIFIED',result.stdout)

    def test_malformed_profile_metadata_is_not_evaluated(self):
        for source,target in [('e5;echo bad','m8'),('e5',''),('e5','m8 x')]:
            result=self.guard('e5',source,target)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('invalid profile metadata',result.stdout)


if __name__=='__main__':unittest.main()
