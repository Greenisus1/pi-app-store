import unittest
import appstore as app
class Tests(unittest.TestCase):
 def test_isolation(self):
  apps=[{'name':c,'category':c} for c in ('apps','games','learning-games','beta')]
  for c in ('apps','games','learning-games','beta'):self.assertEqual([r['name'] for r in app.build_rows(c,apps,{},[])],[c])
 def test_marker(self):self.assertEqual(app.marker_category(b'#!/bin/bash\n# pi-app-store: 1\n# pi-app-store-category: learning-games\n'),'learning-games')
 def test_section(self):self.assertIn(('learning-games','Learning games'),app.SECTIONS)
