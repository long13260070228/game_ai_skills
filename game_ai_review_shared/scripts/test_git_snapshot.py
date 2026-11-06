import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import git_snapshot


class SnapshotTests(unittest.TestCase):
    def make_repo(self, root):
        repo=root/'repo';repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        (repo/'stable.cs').write_text('shared source\n')
        (repo/'alias.cs').write_text('shared source\n')
        (repo/'changed.cs').write_text('before\n')
        (repo/'skip.txt').write_text('not exported')
        (repo/'alias-link.cs').symlink_to('stable.cs')
        git('add','.');git('commit','-m','baseline');baseline=git('rev-parse','HEAD')
        (repo/'changed.cs').write_text('after\n')
        git('add','.');git('commit','-m','target');target=git('rev-parse','HEAD')
        return repo,baseline,target

    def verify_snapshot(self, out, result):
        self.assertEqual(result.get('unique_blobs'),3)
        self.assertEqual(result.get('reused_blob_files'),3)
        self.assertEqual(result['exported_files'],6)
        self.assertEqual((out/'baseline/changed.cs').read_text(),'before\n')
        self.assertEqual((out/'target/changed.cs').read_text(),'after\n')
        self.assertEqual((out/'baseline/stable.cs').read_text(),(out/'target/alias.cs').read_text())
        self.assertFalse((out/'target/alias-link.cs').exists())
        self.assertFalse((out/'target/skip.txt').exists())
        import json
        index=json.loads((out/'index.json').read_text())
        for version,entries in index['trees'].items():
            for item in entries:
                if item['exported']:
                    self.assertEqual(item['sha256'],hashlib.sha256((out/version/item['path']).read_bytes()).hexdigest())
                    self.assertEqual((out/version/item['path']).stat().st_mode & 0o222,0)

    def test_shared_blobs_reused_without_losing_version_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo,baseline,target=self.make_repo(root);out=root/'snapshot'
            requests=[];popen=subprocess.Popen
            class TrackedInput:
                def __init__(self,stream):self.stream=stream
                def write(self,value):
                    requests.append(value.decode().strip())
                    return self.stream.write(value)
                def __getattr__(self,name):return getattr(self.stream,name)
            def tracked(*args,**kwargs):
                process=popen(*args,**kwargs)
                if 'cat-file' in args[0]:process.stdin=TrackedInput(process.stdin)
                return process
            with patch.object(git_snapshot.subprocess,'Popen',side_effect=tracked):
                result=git_snapshot.prepare(repo,baseline,target,out,{'.cs'})
            self.assertEqual(len(requests),3)
            self.assertEqual(len(set(requests)),3)
            self.verify_snapshot(out,result)
            self.assertEqual((out/'baseline/stable.cs').stat().st_ino,(out/'target/stable.cs').stat().st_ino)
            self.assertEqual((out/'baseline/stable.cs').stat().st_mode & 0o222,0)
            with self.assertRaises(ValueError):git_snapshot.prepare(repo,baseline,target,out,{'.cs'})

    def test_reuse_falls_back_when_hardlinks_are_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo,baseline,target=self.make_repo(root);out=root/'snapshot'
            with patch('os.link',side_effect=OSError('hardlinks unavailable')):
                result=git_snapshot.prepare(repo,baseline,target,out,{'.cs'})
            self.verify_snapshot(out,result)

    def test_index_only_does_not_export_or_count_blobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo,baseline,target=self.make_repo(root);out=root/'snapshot'
            result=git_snapshot.prepare(repo,baseline,target,out,set())
            self.assertEqual(result.get('unique_blobs'),0)
            self.assertFalse((out/'baseline').exists())
            self.assertFalse((out/'target').exists())


if __name__=='__main__':unittest.main()
