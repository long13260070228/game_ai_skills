#!/usr/bin/env python3
"""Index fixed Git trees and optionally export selected source suffixes, without checkout."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def tree(repo, commit):
    entries = []
    for row in git(repo, 'ls-tree', '-r', '-l', '-z', commit).split(b'\0'):
        if not row:
            continue
        meta, raw_path = row.split(b'\t', 1)
        mode, kind, oid, size = meta.decode().split()
        path = raw_path.decode('utf-8', 'surrogateescape')
        entries.append(dict(path=path, mode=mode, kind=kind, oid=oid,
                            bytes=int(size) if size != '-' else None))
    return entries


def prepare(repo, baseline, target, out, suffixes):
    repo = Path(repo).resolve()
    commits = {k: git(repo, 'rev-parse', '--verify', v + '^{commit}').decode().strip()
               for k, v in [('baseline', baseline), ('target', target)]}
    # Resolve before exporting; future branch movement cannot alter these reads.
    trees = {k: tree(repo, sha) for k, sha in commits.items()}
    out = Path(out)
    if out.exists():
        raise ValueError('output must be a new directory; existing snapshots are never overwritten')
    out.mkdir(parents=True)
    records = []
    blobs = {}
    process = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for version, entries in trees.items():
            for item in entries:
                item['exported'] = False
                path = PurePosixPath(item['path'])
                if (item['kind'] != 'blob' or item['mode'] not in ('100644', '100755')
                        or path.suffix.lower() not in suffixes):
                    continue
                if path.is_absolute() or '..' in path.parts:
                    raise ValueError('unsafe repository path')
                dest = out / version / item['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                if item['oid'] in blobs:
                    original, checksum = blobs[item['oid']]
                    try:
                        os.link(original, dest)
                    except OSError:
                        shutil.copyfile(original, dest)
                        dest.chmod(0o444)
                else:
                    process.stdin.write((item['oid'] + '\n').encode())
                    process.stdin.flush()
                    header = process.stdout.readline().decode().split()
                    if len(header) != 3 or header[0] != item['oid'] or header[1] != 'blob':
                        raise ValueError('unexpected cat-file header')
                    data = process.stdout.read(int(header[2]))
                    if len(data) != item['bytes'] or process.stdout.read(1) != b'\n':
                        raise ValueError('incomplete blob')
                    dest.write_bytes(data)
                    dest.chmod(0o444)
                    checksum = hashlib.sha256(data).hexdigest()
                    blobs[item['oid']] = (dest, checksum)
                # Shared sources are immutable preparation artifacts, not a checkout.
                item['exported'] = True
                item['sha256'] = checksum
                records.append(dict(version=version, path=item['path'], bytes=item['bytes']))
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    diff = git(repo, 'diff', '--name-status', '--no-renames', '-z',
               commits['baseline'], commits['target'])
    (out / 'changed-files.z').write_bytes(diff)
    result = dict(repository=str(repo), **commits, suffixes=sorted(suffixes), trees=trees,
                  limitation='Index/export is source preparation, not evidence of review coverage. '
                  'Symlinks/submodules are indexed but never followed or exported. '
                  'Identical blobs share read-only hardlinks when supported; never edit snapshots.')
    (out / 'index.json').write_text(json.dumps(result, ensure_ascii=True, indent=2) + '\n')
    return dict(commits=commits, exported_files=len(records), unique_blobs=len(blobs),
                reused_blob_files=len(records)-len(blobs),
                exported_bytes=sum(r['bytes'] for r in records), out=str(out.resolve()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('repo', 'baseline', 'target', 'out'):
        p.add_argument('--' + key, required=True)
    p.add_argument('--suffix', action='append', default=[],
                   help='Export this suffix, e.g. .cs; repeat as needed. Default: index only.')
    a = p.parse_args()
    suffixes = {s.lower() if s.startswith('.') else '.' + s.lower() for s in a.suffix}
    print(json.dumps(prepare(a.repo, a.baseline, a.target, a.out, suffixes), ensure_ascii=False))


if __name__ == '__main__':
    main()
