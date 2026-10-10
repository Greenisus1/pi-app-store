import unittest
from unittest.mock import patch
import appstore as app
class Tests(unittest.TestCase):
 def test_positive_empty(self):
  with patch.object(app,'fetch',return_value=b'<h3>This repository is empty.</h3>'):self.assertTrue(app.repository_metadata('Greenisus1','Null')['empty'])
 def test_unknown_page_stays_failure(self):
  with patch.object(app,'fetch',return_value=b'<h3>Weird page</h3>'):
   with self.assertRaises(ValueError):app.repository_metadata('Greenisus1','Null')
 def test_skip_empty_without_marker_fetch(self):
  with patch.object(app,'repository_candidates',return_value=['Null']),patch.object(app,'repository_metadata',return_value={'name':'Null','empty':True}),patch.object(app,'fetch') as fetch,patch('builtins.print') as output:self.assertEqual(app.discover(),[]);fetch.assert_not_called();output.assert_not_called()
 def test_gui_empty_row(self):
  self.assertIsNone(app.gui_selected_row([],['empty']));self.assertIsNone(app.gui_selected_row([],['0']));self.assertEqual(app.gui_selected_row([{'name':'ok'}],['0']),{'name':'ok'})
if __name__=='__main__':unittest.main()
