import pathlib,tempfile,unittest,json
import appstore as settings
class Tests(unittest.TestCase):
 def test_defaults(self):
  with tempfile.TemporaryDirectory() as d:self.assertEqual(settings.load_preferences(pathlib.Path(d)/'x'),settings.SETTINGS_DEFAULTS)
 def test_persist(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'x';a=dict(settings.SETTINGS_DEFAULTS,theme='light');settings.save_preferences(p,a);self.assertEqual(settings.load_preferences(p),a);self.assertEqual(p.stat().st_mode&0o777,0o600)
 def test_invalid_preserves_old(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'x';settings.save_preferences(p,settings.SETTINGS_DEFAULTS)
   with self.assertRaises(ValueError):settings.save_preferences(p,dict(settings.SETTINGS_DEFAULTS,theme='blue'))
   self.assertEqual(settings.load_preferences(p),settings.SETTINGS_DEFAULTS)
 def test_bad_json(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'x';p.write_text('{bad')
   with self.assertRaises(ValueError):settings.load_preferences(p)
 def test_wrong_update_type(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):settings.save_preferences(pathlib.Path(d)/'x',dict(settings.SETTINGS_DEFAULTS,update_on_boot='yes'))
if __name__=='__main__':unittest.main()
