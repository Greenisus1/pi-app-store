import pathlib,tempfile,unittest,subprocess
from unittest import mock
import appstore as flasher
class Tests(unittest.TestCase):
 def test_root_mounted_rejected(self):
  self.assertEqual(flasher.candidates({'blockdevices':[{'path':'/dev/sda','type':'disk','rm':True,'children':[{'mountpoints':['/']}]}]}),[])
 def test_nonremovable_rejected(self):self.assertEqual(flasher.candidates({'blockdevices':[{'path':'/dev/sda','type':'disk','rm':False}]}),[])
 def test_partition_rejected(self):self.assertEqual(flasher.candidates({'blockdevices':[{'path':'/dev/sda1','type':'part','rm':True}]}),[])
 def test_verify_and_confirm(self):
  disk={'path':'/dev/test','type':'disk','size':1024,'rm':True,'ro':False,'serial':'TEST','model':'test','mountpoints':[]}
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'test.img';p.write_bytes(b'test')
   with mock.patch('appstore.shutil.which',return_value='/mock/rpi-imager'),mock.patch('appstore.scan',return_value=[disk]),mock.patch('appstore.os.geteuid',return_value=0):
    run=mock.Mock();self.assertFalse(flasher.flash(p,'/dev/test',ask=lambda _: 'no',run=run));run.assert_not_called()
    self.assertTrue(flasher.flash(p,'/dev/test',ask=lambda _: 'ERASE /dev/test',run=run));cmd=run.call_args.args[0];self.assertIn('--cli',cmd);self.assertIn('--sha256',cmd);self.assertNotIn('--disable-verify',cmd);self.assertNotIn('--enable-writing-system-drives',cmd)
 def test_replaced_drive_rejected(self):
  disk={'path':'/dev/test','size':1024,'serial':'a','model':'x'}
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'test.img';p.write_bytes(b'test')
   with mock.patch('appstore.shutil.which',return_value='x'),mock.patch('appstore.scan',side_effect=[[disk],[dict(disk,serial='b')]]):
    with self.assertRaises(ValueError):flasher.flash(p,'/dev/test',ask=lambda _:'ERASE /dev/test')
if __name__=='__main__':unittest.main()
