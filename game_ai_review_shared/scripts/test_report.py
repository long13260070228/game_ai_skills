"""Presentation invariants; all fixtures are generic, not a project answer set."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import report


def fixture():
    findings = [dict(id=p, title=p, status='confirmed', origin='new_implementation', severity=p)
                for p in report.SEVERITIES]
    findings += [dict(id=s, title=s, status=s, origin='unknown', severity='P1')
                 for s in report.PENDING_STATUSES]
    findings += [dict(id=s, title=s, status=s, origin='historical', severity='P0')
                 for s in ['refuted', 'inactive_config']]
    findings += [dict(id='suggestion', title='suggestion', status='confirmed',
                     origin='new_implementation', severity='P4', finding_kind='improvement')]
    return dict(findings=findings)


class PresentationTests(unittest.TestCase):
    def test_counters_partition_confirmed_pending_and_audit(self):
        d = fixture()
        n = report.presentation_counts(d)
        self.assertEqual(n['severity_confirmed'], dict.fromkeys(report.SEVERITIES, 1))
        self.assertEqual((n['confirmed_total'], n['pending_total'], n['archive_total']), (5, 3, 3))
        self.assertEqual(n['main_total'] + n['archive_total'], len(d['findings']))
        self.assertEqual(sum(n['severity_confirmed'].values()), n['confirmed_total'])
        self.assertEqual(report.classification_counts(dict(findings=[dict(f, claim_scope='local_contract',
                         flow_reachability=dict(state='unproved')) for f in d['findings']]))['confirmed_total'], 5)

    def test_long_text_preserves_content_with_paragraphs_and_escaping(self):
        from html.parser import HTMLParser
        class Text(HTMLParser):
            def __init__(self):
                super().__init__(); self.parts = []; self.paragraphs = 0
            def handle_starttag(self, tag, attrs):
                if tag == 'p': self.paragraphs += 1
            def handle_data(self, value): self.parts.append(value)
        value = '第一项说明' * 18 + '；' + '第二项说明' * 18 + '。' + '<script>unsafe</script>'
        rendered = report.field_html(value)
        self.assertNotIn('<script>', rendered)
        text = Text(); text.feed(rendered)
        self.assertEqual(''.join(text.parts), value)
        self.assertEqual(text.paragraphs, 3)
        self.assertIn('<ul', report.field_html(['一', '二']))

    def test_empty_and_all_pending(self):
        self.assertEqual(report.presentation_counts(dict(findings=[]))['main_total'], 0)
        d = dict(findings=[f for f in fixture()['findings'] if f['status'] in report.PENDING_STATUSES])
        self.assertEqual(report.presentation_counts(d)['confirmed_total'], 0)
        self.assertEqual(report.presentation_counts(d)['pending_total'], 3)

    def test_severity_criteria_share_the_reference(self):
        rows = report.severity_rows()
        self.assertEqual([row[0].split()[0] for row in rows], list(report.SEVERITIES))
        self.assertTrue(all(row[1] and row[2] for row in rows))

    @unittest.skipUnless(shutil.which('node'), 'Node required for isolated JS unit test')
    def test_frontend_filters_and_metric_clicks(self):
        items = [dict(id=f['id'], bucket=report.display_bucket(f), origin=f['origin'],
                      severity=f['severity'], origin_group=report.origin_group(f), module='A' if f['title'] == 'P0' else 'B', text=f['title'])
                 for f in fixture()['findings'] if report.display_bucket(f) != 'archive']
        harness = r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const cards=input.items.map(f=>({id:f.id,dataset:{bucket:f.bucket,origin:f.origin,severity:f.severity,module:f.module,originGroup:f.origin_group},textContent:f.text,hidden:false}));
const rows=input.items.map(f=>({dataset:{findingId:f.id},hidden:false}));
const controls={};
for(const [id,value] of Object.entries({q:'',severity:'all',origin:'',module:'',count:''}))
 controls[id]={value,textContent:'',addEventListener:(name,fn)=>{controls[id][name]=fn;}};
const buttons=['confirmed','pending','P0','P1','P2','P3','P4'].map(view=>({dataset:{view},attrs:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this[k]=v;}}));
const originButtons=['group:new_or_omission','historical','group:legacy_code_new_config'].map(originFilter=>({dataset:{originFilter},attrs:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this[k]=v;}}));
const document={querySelector:s=>controls[s.slice(1)],getElementById:id=>controls[id],
 querySelectorAll:s=>s==='#main-findings > article'?cards:s==='#finding-overview tbody tr'?rows:s==='button[data-origin-filter]'?originButtons:s==='[data-view]'?buttons:[]};
vm.runInNewContext(input.js,{document});
const visible=()=>cards.filter(c=>!c.hidden);
assert.equal(visible().length,8);
controls.severity.value='P1';controls.severity.change();assert.equal(visible().length,1);
assert.equal(visible()[0].dataset.bucket,'P1');
controls.severity.value='pending';controls.severity.change();assert.equal(visible().length,3);
controls.severity.value='confirmed';controls.severity.change();assert.equal(visible().length,5);
controls.severity.value='all';controls.q.value='P0';controls.q.input();assert.equal(visible().length,1);
controls.q.value='';controls.module.value='A';controls.module.change();assert.equal(visible().length,1);
controls.q.value='P0';controls.q.input();assert.equal(visible().length,1);
controls.q.value='P1';controls.q.input();assert.equal(visible().length,0);
assert.equal(rows.filter(r=>!r.hidden).length,0);
controls.q.value='';controls.q.input();
assert.equal(rows.filter(r=>!r.hidden).length,1);
controls.module.value='';buttons.find(b=>b.dataset.view==='pending').click();
assert.equal(controls.severity.value,'pending');assert.equal(visible().length,3);
assert.equal(controls.count.textContent,'显示 3 / 8 项主问题记录');
assert.equal(buttons.find(b=>b.dataset.view==='pending').attrs['aria-pressed'],'true');
originButtons[0].click();assert.equal(controls.severity.value,'confirmed');assert.equal(controls.origin.value,'group:new_or_omission');assert.equal(visible().length,5);assert.equal(rows.filter(r=>!r.hidden).length,5);assert.equal(originButtons[0].attrs['aria-pressed'],'true');
originButtons[2].click();assert.equal(visible().length,0);assert.equal(rows.filter(r=>!r.hidden).length,0);
'''
        r = subprocess.run([shutil.which('node'), '-e', harness],
                           input=json.dumps(dict(items=items, js=report.JS)), text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
