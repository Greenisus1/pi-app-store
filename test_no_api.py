import unittest,urllib.error,json,io,tarfile,tempfile
from pathlib import Path
from unittest.mock import patch
import appstore as a
SHA='a'*40
ATOM=('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:github.com,2008:Grit::Commit/'+SHA+'</id><title>fix</title><updated>2026-10-08T00:00:00Z</updated></entry></feed>').encode()
class Tests(unittest.TestCase):
 def test_commit(self):
  with patch.object(a,'fetch',return_value=ATOM) as f:self.assertEqual(a.latest_commit('owner','repo','a/b')['sha'],SHA)
  self.assertIn('a%2Fb.atom',f.call_args.args[0]);self.assertNotIn('api.github.com',f.call_args.args[0])
 def test_commit_refuses_missing(self):
  for body in (b'<html>blocked</html>',b'<feed>'):
   with patch.object(a,'fetch',return_value=body):self.assertRaises(ValueError,a.latest_commit,'o','r','main')
 def test_metadata(self):
  with patch.object(a,'fetch',return_value=b'{"defaultBranch":"main","isFork":false}') as f:self.assertEqual(a.api('repos/o/r')['default_branch'],'main')
  self.assertNotIn('api.github.com',f.call_args.args[0])
 def test_no_guess_branch(self):
  with patch.object(a,'fetch',return_value=b'<html>error</html>'):self.assertRaises(ValueError,a.repository_metadata,'o','r')
 def test_listing_two_pages(self):
  pages=[b'<a href="/Greenisus1/One" itemprop="name codeRepository">One</a><a rel="next">Next</a>',b'<a itemprop="name codeRepository" href="/Greenisus1/Two">Two</a>']
  with patch.object(a,'fetch',side_effect=pages):self.assertEqual(a.repository_candidates(),['One','Two'])
 def test_403_graceful(self):
  with patch.object(a.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('u',403,'rate limit exceeded',{},None)):
   with self.assertRaisesRegex(OSError,'No API token needed'):a.fetch('https://github.com/o/r')
 def test_install_never_api(self):
  marker=b'#!/bin/bash\n# pi-app-store: 1\nexit 0\n';data=io.BytesIO()
  with tarfile.open(fileobj=data,mode='w:gz') as tar:
   for name,content in [(a.MARKER,marker),(a.VERSION_FILE,b'{"version":"1.0"}')]:
    m=tarfile.TarInfo('repo/'+name);m.size=len(content);tar.addfile(m,io.BytesIO(content))
  urls=[]
  def fetch(url,limit=0):
   urls.append(url);assert 'api.github.com' not in url
   if url.endswith('.atom'):return ATOM
   if 'codeload.github.com/' in url:return data.getvalue()
   if url.endswith(a.VERSION_FILE):return b'{"version":"1.0"}'
   return marker
  with tempfile.TemporaryDirectory() as d,patch.object(a,'HOME',Path(d)),patch.object(a,'fetch',side_effect=fetch),patch.object(a,'can_install',return_value=True),patch.object(a.subprocess,'run'):
   a.install({'name':'Demo','default_branch':'main'});self.assertEqual(a.load_state()['Demo']['commit'],SHA)
  self.assertTrue(any('codeload.github.com' in x for x in urls))
 def test_invalid_commit_no_download(self):
  with patch.object(a,'can_install',return_value=True),patch.object(a,'fetch') as f:
   self.assertRaises(ValueError,a.install,{'name':'Demo','default_branch':'main'},'../oops');f.assert_not_called()
if __name__=='__main__':unittest.main()
