import pathlib,tempfile,unittest
import appstore as login_hook
class Tests(unittest.TestCase):
 def test_idempotent(self):
  t=login_hook.update_profile('export X=1\n','/test/program.py',True)
  self.assertEqual(t,login_hook.update_profile(t,'/test/program.py',True));self.assertEqual(t.count(login_hook.START),1)
 def test_disable_preserves_other_content(self):
  t=login_hook.update_profile('export X=1\n','/test/program.py',True)
  self.assertIn('export X=1',login_hook.update_profile(t,'/test/program.py',False));self.assertNotIn(login_hook.START,login_hook.update_profile(t,'/test/program.py',False))
 def test_bad_markers(self):
  with self.assertRaises(ValueError):login_hook.update_profile(login_hook.START,'/x',True)
 def test_backup(self):
  with tempfile.TemporaryDirectory() as d:
   h=pathlib.Path(d);(h/'.profile').write_text('before\n');login_hook.install_hook(h,'/x',True);self.assertEqual((h/'.profile.pi-app-store-backup').read_text(),'before\n')
 def test_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   h=pathlib.Path(d);(h/'other').write_text('a');(h/'.profile').symlink_to(h/'other')
   with self.assertRaises(ValueError):login_hook.install_hook(h,'/x',True)
if __name__=='__main__':unittest.main()
