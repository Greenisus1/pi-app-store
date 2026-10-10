import unittest,tempfile,json,io,tarfile,hashlib,subprocess,os
from pathlib import Path
from unittest.mock import patch
import appstore as a
class Security(unittest.TestCase):
 def test_boot_no_download_or_replace_even_legacy_enabled(self):
  with patch.object(a,'preferences',return_value={'update_on_boot':True}),patch.object(a,'fetch') as f,patch.object(a.subprocess,'run') as r:
   self.assertEqual(a.boot_self_update(),0);f.assert_not_called();r.assert_not_called()
 def test_boot_enable_refused(self):
  with self.assertRaises(ValueError):a.configure_boot_update(True)
 def test_login_no_execution(self):
  with patch.object(a.subprocess,'run') as r:a.login_start();r.assert_not_called()
 def test_login_enable_refused(self):
  with self.assertRaises(ValueError):a.configure_login_apps(['demo'])
 def test_apt_cancel(self):
  with patch.object(a,'can_install',return_value=True),patch.object(a.subprocess,'run') as r:
   self.assertFalse(a.install_software('tool',['apt','tool'],confirm=lambda text:False));r.assert_not_called()
 def test_apt_review_actual_commands(self):
  seen=[]
  with patch.object(a,'can_install',return_value=True),patch.object(a.subprocess,'run') as r:
   self.assertTrue(a.install_software('tool',['apt','tool'],confirm=lambda text:seen.append(text) or True))
  self.assertIn('apt-get install -y tool',seen[0]);self.assertEqual(r.call_count,2)
 def test_remote_script_disabled(self):
  with patch.object(a,'can_install',return_value=True),patch.object(a.subprocess,'run') as r,patch.object(a,'fetch') as f:
   with self.assertRaises(ValueError):a.install_software('Ollama',['script','https://ollama.com/install.sh'],lambda text:True)
   r.assert_not_called();f.assert_not_called()
 def fixture(self,root):
  p=Path(root);(p/a.MARKER).write_text('#!/bin/bash\n# pi-app-store: 1\nbash real.sh\n');(p/'real.sh').write_text('echo real code\n')
 def test_complete_review(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);text=a.installer_review(Path(d),'demo','a'*40)
   self.assertIn('echo real code',text);self.assertIn('Exact root command',text);self.assertIn('SHA256',text)
 def test_escape_source_not_terminal_control(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);(Path(d)/'real.sh').write_text('\x1b[2Jhidden\n');self.assertNotIn('\x1b',a.installer_review(Path(d),'demo','a'*40))
 def test_binary_refused(self):
  with tempfile.TemporaryDirectory() as d:
   self.fixture(d);(Path(d)/'binary').write_bytes(b'\xff\x00')
   with self.assertRaises(ValueError):a.installer_review(Path(d),'demo','a'*40)
 def test_update_missing_pin_fails_closed(self):
  with tempfile.TemporaryDirectory() as d,patch.object(a,'HOME',Path(d)),patch.object(a,'can_install',return_value=True):
   with self.assertRaisesRegex(ValueError,'No trusted'):a.apply_update(('Store','pi-app-store','a'*40,b'pass\n'),lambda _:True)
 def test_update_mismatch_fails_closed(self):
  with tempfile.TemporaryDirectory() as d,patch.object(a,'HOME',Path(d)),patch.object(a,'can_install',return_value=True):
   (Path(d)/'store-update-pin.json').write_text(json.dumps({'commit':'a'*40,'sha256':'0'*64}))
   with self.assertRaisesRegex(ValueError,'differs'):a.apply_update(('Store','pi-app-store','a'*40,b'pass\n'),lambda _:True)
 def test_update_valid_pin_cancel_leaves_program(self):
  source=b'pass\n'
  with tempfile.TemporaryDirectory() as d,patch.object(a,'HOME',Path(d)),patch.object(a,'can_install',return_value=True),patch.object(a.os,'replace') as r:
   (Path(d)/'store-update-pin.json').write_text(json.dumps({'commit':'a'*40,'sha256':hashlib.sha256(source).hexdigest()}))
   self.assertFalse(a.apply_update(('Store','pi-app-store','a'*40,source),lambda _:False));r.assert_not_called()
 def test_install_cancel_no_execution_no_state(self):
  marker=b'#!/bin/bash\n# pi-app-store: 1\nbash real.sh\n';buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as tar:
   for name,data in [(a.MARKER,marker),('real.sh',b'echo real\n')]:
    item=tarfile.TarInfo('repo/'+name);item.size=len(data);tar.addfile(item,io.BytesIO(data))
  def fetch(url,limit=0):return buf.getvalue() if 'codeload' in url else marker
  with tempfile.TemporaryDirectory() as d,patch.object(a,'HOME',Path(d)),patch.object(a,'can_install',return_value=True),patch.object(a,'remote_version',return_value='1'),patch.object(a,'fetch',side_effect=fetch),patch.object(a.subprocess,'run') as r:
   self.assertFalse(a.install({'name':'demo','default_branch':'main'},'a'*40,lambda _:False));r.assert_not_called();self.assertEqual(a.load_state(),{});self.assertFalse((Path(d)/'apps').exists())
 def test_request_link_without_network_or_config(self):
  with patch.object(a,'preferences') as config,patch.object(a,'fetch') as network,patch('sys.stdout',new_callable=io.StringIO) as output:
   self.assertEqual(a.main(['--request-app']),0);self.assertIn(a.APP_REQUEST_URL,output.getvalue());config.assert_not_called();network.assert_not_called()
if __name__=='__main__':unittest.main()
