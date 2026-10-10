import unittest
import appstore as boot_update
class Tests(unittest.TestCase):
 def test_boot_once(self):
  text=boot_update.boot_unit('/home/a/appstore.py','/home/a','a');self.assertIn('Type=oneshot',text);self.assertIn('--boot-self-update',text);self.assertNotIn('Restart=',text);self.assertIn('User=a',text)
 def test_invalid_user(self):
  with self.assertRaises(ValueError):boot_update.boot_unit('/x','/a','a;id')
 def test_percent_rejected(self):
  with self.assertRaises(ValueError):boot_update.boot_unit('/home/a%/appstore.py','/a','a')
if __name__=='__main__':unittest.main()
