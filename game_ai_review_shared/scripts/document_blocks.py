#!/usr/bin/env python3
"""Query HTML blocks inside a local HTML/JSON document without dumping the whole source."""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BLOCKS = {'p','li','pre','h1','h2','h3','h4','h5','h6','td','th'}


class Blocks(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.stack = []
        self.blocks = []
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))

    def source_offset(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        own_deleted = tag in {'s','del','strike'} or bool(re.search(r'text-decoration(?:-line)?\s*:[^;]*line-through', attrs.get('style',''), re.I))
        deleted = own_deleted or bool(self.stack and self.stack[-1]['deleted'])
        node = dict(tag=tag, id=attrs.get('id'), start=self.source_offset(), deleted=deleted, segments=[])
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, value):
        if not self.stack or any(n['tag'] in {'script','style'} for n in self.stack):
            return
        segment = dict(text=value, deleted=self.stack[-1]['deleted'])
        for node in self.stack:
            node['segments'].append(segment)

    def handle_endtag(self, tag):
        match = next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i]['tag'] == tag), None)
        if match is None:
            return
        end = self.source.find('>', self.source_offset())
        end = len(self.source) if end < 0 else end + 1
        for node in self.stack[match:]:
            if node['tag'] in BLOCKS:
                node['text'] = ''.join(x['text'] for x in node['segments']).strip()
                node['contains_deleted_text'] = any(x['deleted'] for x in node['segments'])
                node['raw_html'] = self.source[node['start']:end]
                self.blocks.append(node)
        del self.stack[match:]


def html_values(value, locator='$'):
    if isinstance(value, str) and re.search(r'<(?:p|li|h[1-6]|pre|table)[\s>]', value, re.I):
        yield locator, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from html_values(child, locator + '.' + key)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from html_values(child, locator + '[' + str(i) + ']')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', type=Path)
    p.add_argument('--query', help='Regex over actual element text; image alt is not used')
    p.add_argument('--id', help='Exact HTML block id')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--raw', action='store_true', help='Include original HTML snippets')
    a = p.parse_args()
    source = a.file.read_text()
    data = json.loads(source) if a.file.suffix.lower() == '.json' else source
    result = []
    for locator, value in html_values(data):
        parser = Blocks(value)
        parser.feed(value)
        parser.close()
        for block in sorted(parser.blocks, key=lambda x: x['start']):
            if a.id and block['id'] != a.id:
                continue
            if a.query and not re.search(a.query, block['text'], re.I):
                continue
            item = dict(json_locator=locator, **block)
            if not a.raw:
                item.pop('raw_html')
            result.append(item)
    print(json.dumps(dict(total_matches=len(result), shown=result[:a.limit],
                          limitation='Text/deletion locator only; verify source applicability and conflicts separately. '
                          'Nested blocks can overlap. Missing/implicit HTML closures may not be indexed.'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
