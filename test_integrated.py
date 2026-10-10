import pathlib,tempfile,unittest,json,subprocess
from unittest.mock import patch,Mock
import appstore as app
class Tests(unittest.TestCase):
 def test_boot_updates_only_own_source(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'appstore.py';p.write_text('old=1\n');source=b'new=2\n'
   with patch.object(app,'__file__',str(p)),patch.object(app,'preferences',return_value={'update_on_boot':True}),patch.object(app,'repository_metadata',return_value={'default_branch':'main'}),patch.object(app,'latest_commit',return_value={'sha':'a'*40}),patch.object(app,'fetch',return_value=source),patch.object(app.subprocess,'run') as run,patch.object(app,'load_state',side_effect=AssertionError('no app state read')):
    self.assertEqual(app.boot_self_update(),0);self.assertEqual(p.read_text(),"old=1\n");run.assert_not_called()
 def test_boot_disabled_no_network(self):
  with patch.object(app,'preferences',return_value={'update_on_boot':False}),patch.object(app,'fetch') as fetch:self.assertEqual(app.boot_self_update(),0);fetch.assert_not_called()
 def test_boot_invalid_code_preserves_source(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'appstore.py';p.write_text('old=1\n')
   with patch.object(app,'__file__',str(p)),patch.object(app,'preferences',return_value={'update_on_boot':True}),patch.object(app,'repository_metadata',return_value={'default_branch':'main'}),patch.object(app,'latest_commit',return_value={'sha':'a'*40}),patch.object(app,'fetch',return_value=b'not python $$$'):
    self.assertEqual(app.boot_self_update(),0)
    self.assertEqual(p.read_text(),'old=1\n')
 def test_boot_enable_save_failure_rolls_back(self):
  with patch.object(app,'boot_set_enabled') as boot,patch.object(app,'set_preference',side_effect=OSError('test')):
   with self.assertRaises(ValueError):app.configure_boot_update(True)
   boot.assert_not_called()
 def test_login_only_chosen_installed_apps(self):
  with patch.object(app,'preferences',return_value={'autorun':['selected','absent']}),patch.object(app,'load_state',return_value={'selected':{'x':1},'notselected':{}}),patch.object(app,'installed_directory',return_value=pathlib.Path('/test')),patch.object(app.subprocess,'run') as run:app.login_start();run.assert_not_called()
 def test_login_save_failure_restores_profile(self):
  with tempfile.TemporaryDirectory() as d:
   h=pathlib.Path(d);profile=h/'.bash_login';profile.write_text('original\n')
   with patch.object(app.Path,'home',return_value=h),patch.object(app,'set_preference',side_effect=OSError('test')):
    with self.assertRaises(ValueError):app.configure_login_apps(['example'])
   self.assertEqual(profile.read_text(),'original\n')
 def test_reversed_profile_markers(self):
  with self.assertRaises(ValueError):app.update_profile(app.END+'\n'+app.START,'/x',True)
 def test_recipe_names(self):
  names=dict(app.SOFTWARE);self.assertEqual(names['Lua 5.4 (lua5.4)'],['apt','lua5.4']);self.assertIn('Pi Imager CLI (rpi-imager)',names)
 def test_inline_flasher_cancel(self):
  disk={'path':'/dev/test','size':1024,'serial':'x','model':'x'}
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'file.img';p.write_bytes(b'x')
   with patch.object(app,'scan',return_value=[disk]),patch.object(app.shutil,'which',return_value='x'),patch.object(app.subprocess,'run') as run:self.assertFalse(app.flash(p,'/dev/test',ask=lambda _:'no'));run.assert_not_called()
if __name__=='__main__':unittest.main()
