import unittest
from unittest.mock import patch
import appstore as app
class BetaTests(unittest.TestCase):
 def test_beta_isolated(self):
  apps=[{'name':'beta-app','category':'beta'},{'name':'game','category':'games'},{'name':'normal','category':'apps'}]
  self.assertEqual([r['name'] for r in app.build_rows('apps',apps,{},[])],['normal'])
  self.assertEqual([r['name'] for r in app.build_rows('beta',apps,{},[])],['beta-app'])
  self.assertEqual([r['name'] for r in app.build_rows('games',apps,{},[])],['game'])
 def test_beta_marker(self):self.assertEqual(app.marker_category(b'#!/bin/bash\n# pi-app-store: 1\n# pi-app-store-category: beta\n'),'beta')

class BetaInstallTests(unittest.TestCase):
 def test_beta_cancel_no_fetch(self):
  with patch.object(app,'can_install',return_value=True),patch.object(app,'OFFLINE',False),patch.object(app,'fetch') as fetch:
   self.assertFalse(app.install({'name':'Demo','default_branch':'main','category':'beta'},confirm=lambda *_:False));fetch.assert_not_called()
