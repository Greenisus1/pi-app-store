import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import appstore as a
class Tests(unittest.TestCase):
 def test_update_all_row(self):
  pending=[('demo','demo','a'*40,None)];rows=a.build_rows('updates',[],{},pending)
  self.assertEqual(rows[0]['action'],'update-all');self.assertEqual(rows[1]['pending'],pending[0])
 def fixture(self,root):
  p=Path(root)/'apps/demo';p.mkdir(parents=True);(p/a.MARKER).write_text('#!/bin/bash\n# pi-app-store: 1\n')
  return p,{'demo':{'directory':str(p)}}
 def test_cancel(self):
  with tempfile.TemporaryDirectory() as r:
   p,state=self.fixture(r)
   with patch.object(a,'HOME',Path(r)),patch.object(a,'load_state',return_value=state),patch.object(a,'can_install',return_value=True),patch.object(a,'save_state') as save:
    self.assertFalse(a.uninstall_app('demo',lambda q:False));self.assertTrue(p.exists());save.assert_not_called()
 def test_remove(self):
  with tempfile.TemporaryDirectory() as r:
   p,state=self.fixture(r);outside=Path(r)/'external';outside.write_text('keep')
   with patch.object(a,'HOME',Path(r)),patch.object(a,'load_state',return_value=state),patch.object(a,'can_install',return_value=True),patch.object(a,'save_state') as save:
    self.assertTrue(a.uninstall_app('demo',lambda q:True));self.assertFalse(p.exists());self.assertTrue(outside.exists());save.assert_called_once_with({})
 def test_state_save_failure_restores_checkout(self):
  with tempfile.TemporaryDirectory() as r:
   p,state=self.fixture(r)
   with patch.object(a,'HOME',Path(r)),patch.object(a,'load_state',return_value=state),patch.object(a,'can_install',return_value=True),patch.object(a,'save_state',side_effect=OSError('disk full')):
    with self.assertRaises(OSError):a.uninstall_app('demo',lambda q:True)
    self.assertTrue(p.exists());self.assertFalse(list(p.parent.glob('.uninstall-*')))
 def test_escape(self):
  with tempfile.TemporaryDirectory() as r:
   state={'bad':{'directory':r}}
   with patch.object(a,'HOME',Path(r)),patch.object(a,'load_state',return_value=state),patch.object(a,'can_install',return_value=True):
    with self.assertRaises(ValueError):a.uninstall_app('bad',lambda q:True)
if __name__=='__main__':unittest.main()
