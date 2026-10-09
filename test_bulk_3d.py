import unittest
from unittest.mock import patch
import appstore as a
class Tests(unittest.TestCase):
 def test_category(self):
  rows=[{'name':'maze','category':'games-3d'},{'name':'pong','category':'games'}]
  self.assertEqual([r['name'] for r in a.build_rows('games-3d',rows,{},[])],['maze'])
  self.assertEqual([r['name'] for r in a.build_rows('games',rows,{},[])],['pong'])
  self.assertIn(('games-3d','  3D games'),a.SECTIONS)
 def test_cancel(self):
  rows=[('x','x','commit',None)]
  with patch.object(a,'can_install',return_value=True),patch.object(a,'apply_update') as apply:
   self.assertEqual(a.update_all(rows,lambda _:False),[]);apply.assert_not_called();self.assertEqual(len(rows),1)
 def test_partial_and_order(self):
  rows=[('Store','pi-app-store','c',b'code'),('Good','good','c',None),('Bad','bad','c',None)];seen=[]
  def apply(row,confirm):
   seen.append(row[1]);return row[1]!='bad'
  with patch.object(a,'can_install',return_value=True),patch.object(a,'apply_update',side_effect=apply):result=a.update_all(rows,lambda _:True)
  self.assertEqual(seen,['good','bad','pi-app-store']);self.assertEqual([r[1] for r in rows],['bad']);self.assertEqual(sum(r[1] for r in result),2)
 def test_error_keeps_row(self):
  rows=[('bad','bad','c',None)]
  with patch.object(a,'can_install',return_value=True),patch.object(a,'apply_update',side_effect=OSError('no')):
   result=a.update_all(rows,lambda _:True)
  self.assertEqual(len(rows),1);self.assertFalse(result[0][1])
 def test_plain_bulk(self):
  rows=[('x','x','c',None)]
  with patch.object(a,'choose',return_value=0),patch.object(a,'update_all') as bulk:a.updates(rows)
  bulk.assert_called_once_with(rows)
if __name__=='__main__':unittest.main()
