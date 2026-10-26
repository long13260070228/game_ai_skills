import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import bundle
import report

class BundleTests(unittest.TestCase):
    def test_excluded_trees_are_not_traversed(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'cache/deep').mkdir(parents=True)
            (root/'cache/deep/ignored.txt').write_text('not evidence')
            (root/'evidence.txt').write_text('evidence')
            visits=[];scandir=os.scandir
            def tracked(path):
                visits.append(Path(path))
                return scandir(path)
            with patch('os.scandir',side_effect=tracked):
                inventory=bundle.source_files(root)
            self.assertEqual(set(inventory),{'evidence.txt'})
            self.assertFalse(any(path.is_relative_to(root/'cache') for path in visits),visits)

    def test_streamed_entry_supports_zip64(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            (root/'large.txt').write_bytes(b'x'*2048)
            target=Path(tmp)/'evidence.zip'
            with patch('zipfile.ZIP64_LIMIT',1024):
                meta=bundle.build_archive(root,target,{})
            with zipfile.ZipFile(target) as z:
                self.assertEqual(z.read('large.txt'),b'x'*2048)
                self.assertIsNone(z.testzip())
            self.assertEqual(meta['files'],1)

    def test_manifest_matches_archive_and_excludes_generated_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            (root/'review.json').write_text('{}')
            (root/'evidence').mkdir();(root/'evidence/a.txt').write_text('原始证据')
            (root/'delivery.json').write_text('stale')
            (root/'packages').mkdir();(root/'packages/duplicate.zip').write_bytes(b'stale')
            destination=Path(tmp)/'evidence.zip'
            meta=bundle.build_archive(root,destination,{'index.html':b'package view'})
            with zipfile.ZipFile(destination) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(z.read('index.html'),b'package view')
                self.assertNotIn('delivery.json',z.namelist())
                self.assertFalse(any(n.startswith('packages/') for n in z.namelist()))
                entries=json.loads(z.read('MANIFEST.json'))
                self.assertEqual({x['path'] for x in entries},set(z.namelist())-{'MANIFEST.json'})
                for item in entries:
                    data=z.read(item['path'])
                    self.assertEqual(item['bytes'],len(data))
                    self.assertEqual(item['sha256'],hashlib.sha256(data).hexdigest())
            self.assertEqual(meta['sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
            self.assertEqual(meta['bytes'],destination.stat().st_size)

    def test_build_archive_reuses_supplied_source_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            evidence=root/'evidence.txt';evidence.write_text('fixed evidence')
            destination=Path(tmp)/'evidence.zip'
            with mock.patch.object(bundle,'source_files',side_effect=AssertionError('rescanned')):
                meta=bundle.build_archive(root,destination,{},source_inventory={'evidence.txt':evidence})
            self.assertEqual(meta['files'],1)
            with zipfile.ZipFile(destination) as z:self.assertEqual(z.read('evidence.txt'),b'fixed evidence')

    def test_archive_verification_rejects_corrupt_entry_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'corrupt.zip'
            payload=b'original bytes'
            manifest=[{'path':'evidence.bin','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as z:
                z.writestr('evidence.bin',payload)
                z.writestr('MANIFEST.json',json.dumps(manifest))
            with zipfile.ZipFile(path) as z:
                info=z.getinfo('evidence.bin')
                name_len,extra_len=struct.unpack_from('<HH',path.read_bytes(),info.header_offset+26)
                byte_offset=info.header_offset+30+name_len+extra_len
            with path.open('r+b') as f:
                f.seek(byte_offset);original=f.read(1);f.seek(byte_offset);f.write(bytes([original[0]^0x01]))
            with self.assertRaisesRegex(zipfile.BadZipFile,'CRC'):
                bundle.verify_archive(path,manifest)

    def test_valid_crc_does_not_hide_incorrect_sha_or_size(self):
        payload=b'valid CRC'
        with tempfile.TemporaryDirectory() as tmp:
            for field,value in [('sha256','0'*64),('bytes',len(payload)+1)]:
                with self.subTest(field=field):
                    path=Path(tmp)/(field+'.zip')
                    entry={'path':'evidence.bin','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
                    entry[field]=value;manifest=[entry]
                    with zipfile.ZipFile(path,'w') as z:
                        z.writestr('evidence.bin',payload)
                        z.writestr('MANIFEST.json',json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError,'Manifest mismatch'):
                        bundle.verify_archive(path,manifest)

    def test_archive_verification_rejects_manifest_entry_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'extra.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('evidence.txt',b'evidence')
                z.writestr('unexpected.txt',b'extra')
                z.writestr('MANIFEST.json',b'[]\n')
            with self.assertRaises(ValueError):bundle.verify_archive(path,[])

    def test_rejects_self_inclusion_and_symlink_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            with self.assertRaises(ValueError):bundle.build_archive(root,root/'evidence.zip',{})
            (root/'alias').symlink_to(Path(tmp)/'missing')
            with self.assertRaises(ValueError):bundle.build_archive(root,Path(tmp)/'out.zip',{})

class BundleIntegrationTests(unittest.TestCase):
    def test_cli_preserves_facts_and_renders_local_and_offline_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            doc=dict(title='Generic review',mode='independent',target='a'*40,baseline='b'*40,
                     scope='Fixed snapshots',limitations=['Static only'],sources=[],coverage=[],findings=[],
                     skill_version='test-version',timings={},high_severity_review=[],review_state='completed',
                     handoffs=[],classification_schema='local-flow-v1')
            facts=json.dumps(doc).encode();(root/'review.json').write_bytes(facts)
            (root/'review.md').write_text('Generic review')
            (root/'data-sources.md').write_text('No source attachments in this empty fixture')
            destination=Path(tmp)/'evidence.zip'
            command=[sys.executable,str(Path(bundle.__file__)),str(root),'--zip',str(destination)]
            for _ in range(2):
                run=subprocess.run(command,text=True,capture_output=True)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertEqual((root/'review.json').read_bytes(),facts)
                meta=json.loads((root/'delivery.json').read_text())
                self.assertEqual(meta['bytes'],destination.stat().st_size)
                self.assertEqual(meta['sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
                local=(root/'index.html').read_text();links=bundle.Links();links.feed(local)
                self.assertIn(meta['url'],links.hrefs)
                self.assertIn(meta['sha256'],local)
                self.assertTrue(destination.with_name('evidence-SHA256.txt').read_text().startswith(meta['sha256']))
                with zipfile.ZipFile(destination) as z:
                    self.assertEqual(z.read('review.json'),facts)
                    package=z.read('index.html').decode();package_links=bundle.Links();package_links.feed(package)
                    self.assertFalse(any('.zip' in href for href in package_links.hrefs))
                    self.assertIn('证据已包含',package)
                    self.assertNotIn('delivery.json',z.namelist())
                    z.extractall(Path(tmp)/'offline')
                    bundle.check_links(Path(tmp)/'offline',package,included=set(z.namelist()))
            self.assertEqual(len(list(Path(tmp).glob('*.zip'))),1)

    def test_finalize_generates_markdown_without_changing_frozen_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            doc=dict(title='Generic review',mode='independent',target='a'*40,baseline='b'*40,
                     scope='Fixed snapshots',limitations=['Static only'],sources=[],coverage=[],findings=[],
                     skill_version='test-version',timings={},high_severity_review=[],review_state='completed',
                     handoffs=[],classification_schema='local-flow-v1')
            frozen=json.dumps(doc,ensure_ascii=False,indent=2).encode()+b'\n'
            (root/'review.json').write_bytes(frozen)
            (root/'data-sources.md').write_text('Source inventory')
            destination=Path(tmp)/'evidence.zip'
            run=subprocess.run([sys.executable,str(Path(bundle.__file__)),str(root),'--zip',str(destination),'--finalize'],text=True,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual((root/'review.json').read_bytes(),frozen)
            self.assertEqual((root/'review.md').read_text(),report.markdown(doc))
            self.assertTrue((root/'index.html').is_file())
            self.assertEqual(len(list(Path(tmp).glob('*.zip'))),1)
            with zipfile.ZipFile(destination) as z:
                self.assertEqual(z.read('review.md').decode(),report.markdown(doc))
                package=z.read('index.html').decode()
                offline=Path(tmp)/'offline';z.extractall(offline)
                bundle.check_links(offline,package,included=set(z.namelist()))
                self.assertIn('证据已包含',package)

    def test_finalize_requires_data_sources_but_not_existing_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            doc=dict(title='Generic review',mode='independent',target='a'*40,baseline='b'*40,
                     scope='Fixed snapshots',limitations=['Static only'],sources=[],coverage=[],findings=[],
                     skill_version='test-version',timings={},high_severity_review=[],review_state='completed',
                     handoffs=[],classification_schema='local-flow-v1')
            (root/'review.json').write_text(json.dumps(doc))
            destination=Path(tmp)/'evidence.zip'
            run=subprocess.run([sys.executable,str(Path(bundle.__file__)),str(root),'--zip',str(destination),'--finalize'],text=True,capture_output=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('data-sources.md',run.stderr)
            self.assertFalse((root/'review.md').exists())

class LinkTests(unittest.TestCase):
    def test_package_links_must_be_in_archive_and_fragments_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'report';root.mkdir()
            (Path(tmp)/'sibling.txt').write_text('outside')
            (root/'cache').mkdir();(root/'cache/dup.txt').write_text('excluded')
            (root/'other.html').write_text('<h1 id="valid">ok</h1>')
            for href in ('../sibling.txt','cache/dup.txt','other.html#missing'):
                with self.subTest(href=href),self.assertRaises(ValueError):
                    bundle.check_links(root,'<a href="'+href+'">link</a>',included={'other.html'})
            self.assertEqual(bundle.check_links(root,'<a href="other.html#valid">ok</a>',included={'other.html'}),1)
            with self.assertRaises(ValueError):bundle.check_links(root,'<img src="missing.png">')

    def test_repeated_fragments_read_linked_html_once_and_still_validate_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'other.html'
            target.write_text('<h1 id="one">one</h1><h2 id="two">two</h2>')
            markup='<a href="other.html#one">1</a><a href="other.html#two">2</a><a href="other.html#one">3</a>'
            original=bundle.Links.feed;reads=[]
            def counted(parser,markup):
                if '<h1 id="one">' in markup:reads.append(markup)
                return original(parser,markup)
            with mock.patch.object(bundle.Links,'feed',counted):
                self.assertEqual(bundle.check_links(root,markup),3)
            self.assertEqual(len(reads),1)

    def test_repeated_fragment_cache_does_not_hide_missing_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'other.html').write_text('<h1 id="present">ok</h1>')
            markup='<a href="other.html#present">ok</a><a href="other.html#missing">bad</a>'
            with self.assertRaisesRegex(ValueError,'missing'):
                bundle.check_links(root,markup)

if __name__=='__main__':unittest.main()
