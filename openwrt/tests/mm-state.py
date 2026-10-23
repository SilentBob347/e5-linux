"""Exercise the production mirror with D-Bus-shaped events and no hardware."""
from pathlib import Path
import runpy
import sys
import unittest

TOP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(TOP/'openwrt/overlay/usr/lib/e5/vendor/dbus_next-0.2.3-py3-none-any.whl'))
module=runpy.run_path(str(TOP/'openwrt/overlay/usr/libexec/e5-mm-state'))
Mirror=module['Mirror'];MM=module['MM'];OM=module['MANAGER'];PROPS=module['PROPERTIES']
from dbus_next import Variant


class Properties(unittest.TestCase):
    def setUp(self):
        self.m=Mirror();self.m.owner=':1.5'
        self.m.apply('',OM,'InterfacesAdded',['/modem',{MM+'.Modem':{
            'Device':Variant('s','unisoc-sipc'),'Plugin':Variant('s','unisoc'),
            'Sim':Variant('o','/sim'),'State':Variant('i',8),
            'OwnNumbers':Variant('as',['PRIVATE-NUMBER'])}}])
        self.m.apply('',OM,'InterfacesAdded',['/sim',{MM+'.Sim':{
            'SimIdentifier':Variant('s','1234567890123456789'),'Imsi':Variant('s','460001234567890')}}])

    def test_snapshot_is_filtered_and_scoped(self):
        s=self.m.snapshot('1')
        self.assertTrue(s['alive']);self.assertEqual(s['sim']['slot'],'1')
        self.assertEqual(s['sim']['iccid'],'1234567890123456789')
        self.assertNotIn('PRIVATE-NUMBER',str(self.m.objects))
        self.assertFalse(self.m.snapshot('bad')['alive'])

    def test_invalidated_sim_does_not_reuse_identity(self):
        self.m.apply('/sim',PROPS,'PropertiesChanged',[MM+'.Sim',{},['SimIdentifier','Imsi']])
        self.assertEqual(self.m.snapshot('0')['sim']['iccid'],'')
        self.m.apply('',OM,'InterfacesRemoved',['/modem',[MM+'.Modem']])
        self.assertFalse(self.m.snapshot('0')['alive'])

    def test_sms_and_voice_properties_never_enter_cache(self):
        self.m.apply('/sms',OM,'InterfacesAdded',['/sms',{MM+'.Sms':{'Text':'PRIVATE BODY'}}])
        self.m.apply('/call',PROPS,'PropertiesChanged',[MM+'.Call',{'Number':'PRIVATE NUMBER'},[]])
        self.assertNotIn('PRIVATE',str(self.m.objects))

    def test_owner_loss_and_wrong_device_are_not_alive(self):
        self.m.owner=None;self.assertFalse(self.m.snapshot('0')['alive'])
        self.m.owner=':1.8'
        self.m.apply('/modem',PROPS,'PropertiesChanged',[MM+'.Modem',{'Plugin':'other'},[]])
        self.assertFalse(self.m.snapshot('0')['alive'])


if __name__=='__main__':unittest.main()
