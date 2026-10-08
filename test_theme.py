import unittest,io,os
from unittest.mock import patch
import appstore as a
class Tests(unittest.TestCase):
 def test_toggle(self):
  with patch.object(a,'THEME','dark'):self.assertEqual(a.toggle_theme(),'light');self.assertEqual(a.toggle_theme(),'dark')
 def test_light(self):
  p=a.theme_palette({'warn':(3,-1),'bad':(1,-1),'head':(7,4)},True);self.assertEqual(p['base'],(0,7));self.assertEqual(p['warn'],(4,7));self.assertEqual(p['bad'],(1,7));self.assertEqual(p['head'],(7,4))
 def test_dark(self):self.assertEqual(a.theme_palette({'ok':(2,-1)})['ok'],(2,0))
 def test_does_not_mutate(self):
  p={'warn':(3,-1)};a.theme_palette(p,True);self.assertEqual(p,{'warn':(3,-1)})
 def test_plain_toggle_no_network(self):
  with patch.object(a,'THEME','dark'),patch('builtins.input',side_effect=['t','0']),patch.object(a,'fetch') as f,patch('sys.stdout',io.StringIO()):a.main(['--offline','--plain']);self.assertEqual(a.THEME,'light')
  f.assert_not_called()
 def test_light_ansi(self):
  out=io.StringIO();out.isatty=lambda:True
  with patch.object(a,'THEME','light'),patch.dict(os.environ,{'TERM':'xterm'}):ui=a.Terminal(out);ui.color=True;ui.write('hello','36')
  self.assertIn('\x1b[30;47m',out.getvalue())
if __name__=='__main__':unittest.main()
