"""Origin summary partitions and presentation use generic, synthetic findings."""
import copy
import unittest
import report
from test_report_presentation import document, finding


def origin_fixture():
    doc=document()
    doc['target_label']='候选版本'
    doc['baseline_label']='基线版本'
    doc['findings']=[]
    for fid,origin,subtype in [('impl','new_implementation',None),('req','new_requirement',None),
                             ('entry','migration_gap',None),('config','migration_gap','legacy_code_new_config'),
                             ('past','historical',None),('unknown','unknown',None)]:
        f=finding(fid);f['origin']=origin
        if subtype:f['origin_subtype']=subtype
        doc['findings'].append(f)
    for status in ['conditional','refuted','inactive_config']:
        f=finding(status,status=status);f.update(origin='migration_gap',origin_subtype='legacy_code_new_config')
        doc['findings'].append(f)
    doc['findings'].append(finding('suggestion',kind='improvement'))
    return doc


class OriginSummaryTests(unittest.TestCase):
    def test_confirmed_groups_are_disjoint_and_preserve_inclusive_new_total(self):
        doc=origin_fixture();before=copy.deepcopy(doc)
        counts=report.origin_counts(doc)
        self.assertEqual(counts,dict(new_or_omission=3,historical=1,legacy_code_new_config=1,unknown=1))
        self.assertEqual(sum(counts.values()),report.presentation_counts(doc)['confirmed_total'])
        self.assertEqual(report.classification_counts(doc)['new_bug_total'],4)
        self.assertEqual(report.presentation_counts(doc)['origin_confirmed'],counts)
        self.assertEqual(doc,before)

    def test_unmarked_migration_is_not_assumed_to_be_configuration(self):
        doc=origin_fixture();doc['findings']=[f for f in doc['findings'] if f['id']=='entry']
        self.assertEqual(report.origin_counts(doc)['legacy_code_new_config'],0)
        self.assertEqual(report.origin_counts(doc)['new_or_omission'],1)
        self.assertEqual(sum(report.origin_counts(dict(findings=[])).values()),0)

    def test_html_and_markdown_expose_all_three_groups_and_unknown(self):
        doc=origin_fixture();page=report.render(doc,'review');md=report.markdown(doc)
        for label in ['候选版本新增 / 遗漏','基线版本历史问题','旧代码 × 新配置','归因未知']:
            self.assertIn(label,page);self.assertIn(label,md)
        self.assertIn('id="origin-summary"',page)
        self.assertIn('data-origin-filter="group:legacy_code_new_config"',page)
        self.assertIn('data-origin-group="legacy_code_new_config"',page)
        self.assertIn('互斥',page)

    def test_labels_only_use_explicit_or_frozen_metadata(self):
        doc=origin_fixture();doc.pop('target_label');doc.pop('baseline_label')
        doc.update(target_ref='release_candidate',baseline_ref='main')
        self.assertEqual(report.origin_summary_labels(doc)['new_or_omission'],'release_candidate新增 / 遗漏')
        self.assertEqual(report.origin_summary_labels(doc)['historical'],'main历史问题')
        doc.pop('target_ref');doc.pop('baseline_ref');doc['sources']=[]
        self.assertEqual(report.origin_summary_labels(doc)['new_or_omission'],'本次新增 / 遗漏')
        self.assertEqual(report.origin_summary_labels(doc)['historical'],'基线历史问题')


if __name__=='__main__':unittest.main()
