"""Regression tests for the report's HTML-only presentation context."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report


SHA_TARGET = "a" * 40
SHA_BASELINE = "b" * 40


def finding(fid, *, status="confirmed", kind=None, module="西行试炼"):
    value = {
        "id": fid, "title": "刷新状态缺失 " + fid, "status": status,
        "origin": "new_implementation", "severity": "P2", "claim_scope": "local_contract",
        "flow_reachability": {"state": "reachable", "basis": "已到达", "evidence_refs": ["E1"]},
        "local_input_basis": {"description": "合法输入", "evidence_refs": ["E1"]},
        "trigger": "进度改变", "actual": "显示旧值", "expected": "显示新值", "impact": "需要重开",
        "reachability": "可以到达", "counterevidence": "未发现反证", "evidence_level": "静态推导",
        "scope": "固定提交", "limitations": ["未联服"], "evidence": [
            {"source_id": "S1", "location": "Data.cs", "locator": "10-15", "quote": "源代码片段",
             "supports": "状态未更新", "role": "implementation"}
        ], "severity_basis": {"consequence": "状态滞后", "affected_scope": "一个页面",
             "trigger_basis": "合法输入", "recovery": "重开页面", "rationale": "有限影响", "evidence_refs": ["E1"]}
    }
    if module is not None:
        value["module"] = module
    if kind:
        value["finding_kind"] = kind
    return value


def document():
    return {
        "title": "固定版本审查", "mode": "independent", "target": SHA_TARGET,
        "baseline": SHA_BASELINE, "scope": "两个固定提交间的审查范围",
        "limitations": ["没有运行联服"], "sources": [
            {"id": "S1", "kind": "git", "location": "repo", "version": SHA_TARGET,
             "allowed": True, "limitations": "固定对象"}
        ], "coverage": [{"module": "西行试炼", "state": "covered"}],
        "findings": [finding("F-01"), finding("ARCHIVE", status="refuted", kind="improvement"),
                     finding("NO-MODULE", module=None)],
        "disclaimer": {"summary": "摘要免责声明", "details": ["详细免责声明"]},
        "presentation_revision": {"notice": "此展示副本不是合并审查结论。"}
    }


class ReportPresentationTests(unittest.TestCase):
    def test_overview_rows_map_only_to_main_cards_and_keep_archive_separate(self):
        rendered = report.render(document(), "review")
        self.assertIn('href="#F-01"', rendered)
        self.assertIn('href="#NO-MODULE"', rendered)
        self.assertIn('id="F-01"', rendered)
        self.assertIn('id="ARCHIVE"', rendered)
        overview = rendered.split('id="finding-overview"', 1)[1].split('</table>', 1)[0]
        self.assertIn('F-01', overview)
        self.assertNotIn('ARCHIVE', overview)
        self.assertIn('未分类', overview)

    def test_shared_filters_have_module_severity_origin_data(self):
        from html.parser import HTMLParser

        class RowsAndCards(HTMLParser):
            def __init__(self):
                super().__init__(); self.rows = []; self.cards = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'tr' and attrs.get('data-finding-id'):
                    self.rows.append(attrs)
                if tag == 'article' and attrs.get('data-finding-id'):
                    if attrs.get('data-bucket') != 'archive':
                        self.cards.append(attrs)

        rendered = report.render(document(), "review")
        self.assertIn('id="module"', rendered)
        self.assertIn('id="severity"', rendered)
        self.assertIn('id="origin"', rendered)
        parsed = RowsAndCards(); parsed.feed(rendered)
        row_keys = {r['data-finding-id']: (r['data-bucket'], r['data-origin'], r['data-module']) for r in parsed.rows}
        card_keys = {c['data-finding-id']: (c['data-bucket'], c['data-origin'], c['data-module']) for c in parsed.cards}
        self.assertEqual(row_keys, card_keys)
        self.assertEqual(row_keys['F-01'], ('P2', 'new_implementation', '西行试炼'))
        self.assertEqual(row_keys['NO-MODULE'], ('P2', 'new_implementation', '未分类'))
        self.assertNotIn('ARCHIVE', row_keys)

    def test_inputs_and_long_boundaries_are_after_findings(self):
        rendered = report.render(document(), "review")
        issues = rendered.index('id="finding-overview"')
        toolbar = rendered.index('class="toolbar"')
        inputs = rendered.index('id="complete-inputs"')
        standards = rendered.index('id="severity-guide"')
        limitations = rendered.index('id="review-limitations"')
        self.assertGreater(inputs, issues)
        self.assertLess(toolbar, issues)
        self.assertGreater(standards, issues)
        self.assertGreater(limitations, issues)
        self.assertIn('摘要免责声明', rendered[:issues])
        for anchor in ('#overview', '#problem-overview', '#finding-details', '#complete-inputs', '#sources', '#audit-records'):
            self.assertIn('href="' + anchor + '"', rendered)
        self.assertIn('问题详情', rendered)
        self.assertIn('<b>2</b> 项确定问题', rendered)
        self.assertIn('没有运行联服', rendered)
        self.assertIn(SHA_TARGET, rendered[:rendered.index('id="review-scope"')])
        self.assertIn('目标完整 SHA', rendered[rendered.index('id="review-scope"'):])
        self.assertIn('触发条件', rendered)
        self.assertIn('影响', rendered)
        self.assertIn('实际行为', rendered)
        self.assertIn('预期依据', rendered)
        # Only trigger/impact are in the always-visible preview.
        card = rendered.split('id="F-01"', 1)[1].split('</article>', 1)[0]
        visible = card.split('<details class="finding-details"', 1)[0]
        self.assertIn('进度改变', visible)
        self.assertIn('需要重开', visible)
        self.assertNotIn('显示旧值', visible)

    def test_delivery_local_package_and_missing_semantics(self):
        doc = document()
        before = copy.deepcopy(doc)
        local = report.render(doc, "review", {
            "profile": "local", "url": "evidence.zip", "bytes": 2048,
            "sha256": "c" * 64, "checksum_url": "evidence.zip.sha256"
        })
        self.assertIn('href="evidence.zip"', local)
        self.assertIn('href="evidence.zip.sha256"', local)
        self.assertIn('2,048 bytes', local)
        self.assertIn('0.00 MiB', local)
        self.assertIn('包含报告、原始输入与核证资料；解压后打开', local)
        self.assertIn("c" * 64, local)
        self.assertIn('此展示副本不是合并审查结论。', local)
        self.assertLess(local.index('id="delivery"'), local.index('id="finding-overview"'))
        self.assertEqual(local.count('class="download-button"'), 1)
        self.assertIn('href="#delivery"', local)
        self.assertIn('包含报告、原始输入与核证资料；解压后打开', local)

        package = report.render(doc, "review", {"profile": "package"})
        self.assertIn('证据已包含在随包目录', package)
        self.assertIn('此展示副本不是合并审查结论。', package)
        self.assertEqual(package.count('class="download-button"'), 0)
        self.assertIn('包含报告、原始输入与核证资料；解压后打开', package)
        self.assertNotIn('href="evidence.zip"', package)
        self.assertNotIn('下载证据包', package)

        missing = report.render(doc, "review")
        self.assertIn('证据包尚未生成', missing)
        self.assertIn('此展示副本不是合并审查结论。', missing)
        self.assertNotIn('包含报告、原始输入与核证资料；解压后打开', missing)
        self.assertNotIn('href="evidence.zip"', missing)
        self.assertNotIn('href="#"', missing)
        self.assertEqual(doc, before, "delivery is presentation context and must not enter fact JSON")

    def test_local_delivery_requires_a_safe_checksum_link(self):
        base = {
            "profile": "local", "url": "evidence.zip", "bytes": 2048,
            "sha256": "d" * 64,
        }
        for checksum_url in (None, "javascript:alert(1)"):
            with self.subTest(checksum_url=checksum_url):
                context = dict(base)
                if checksum_url is not None:
                    context["checksum_url"] = checksum_url
                rendered = report.delivery_html(context)
                self.assertNotIn('class="download-button"', rendered)
                self.assertIn('证据包尚未生成或下载校验信息不完整。', rendered)
                self.assertNotIn('href="evidence.zip"', rendered)
                self.assertNotIn('包含报告、原始输入与核证资料；解压后打开', rendered)

    def test_nav_links_to_delivery_section(self):
        rendered = report.render(document(), "review")
        self.assertIn('href="#delivery"', rendered)

    def test_versions_use_recorded_branches_and_full_shas_without_live_git(self):
        from html.parser import HTMLParser
        doc=document()
        doc['sources']=[
            {'kind':'git','version':SHA_TARGET,'requested_ref':'master'},
            {'kind':'git','version':SHA_BASELINE,'requested_ref':'origin/develop_feature'},
            {'kind':'git','version':'different','requested_ref':'wrong-branch'}]
        text=report.version_summary(doc)
        class VersionRows(HTMLParser):
            def __init__(self):
                super().__init__();self.rows=[];self.depth=0
            def handle_starttag(self,tag,attrs):
                if tag=='div':
                    if dict(attrs).get('class')=='version-item':self.rows.append('');self.depth=1
                    elif self.depth:self.depth+=1
            def handle_endtag(self,tag):
                if tag=='div' and self.depth:self.depth-=1
            def handle_data(self,value):
                if self.depth:self.rows[-1]+=value
        parsed=VersionRows();parsed.feed(text)
        self.assertEqual(len(parsed.rows),2)
        self.assertIn('master',parsed.rows[0]);self.assertIn(SHA_TARGET,parsed.rows[0])
        self.assertIn('origin/develop_feature',parsed.rows[1]);self.assertIn(SHA_BASELINE,parsed.rows[1])
        self.assertNotIn('wrong-branch',text);self.assertNotIn('…',text)
        doc['sources']=[]
        self.assertIn('分支未登记',report.version_summary(doc))

    def test_download_metadata_has_separate_size_hash_and_checksum_fields(self):
        from html.parser import HTMLParser
        sha='d'*64
        rendered=report.delivery_html({'profile':'local','url':'evidence.zip','bytes':2048,
                                     'sha256':sha,'checksum_url':'evidence-SHA256.txt'})
        class Metadata(HTMLParser):
            def __init__(self):super().__init__();self.values={};self.field=None
            def handle_starttag(self,tag,attrs):
                field=dict(attrs).get('data-delivery-field')
                if field:self.field=field;self.values[field]=''
            def handle_endtag(self,tag):
                if tag=='dd':self.field=None
            def handle_data(self,value):
                if self.field:self.values[self.field]+=value
        parsed=Metadata();parsed.feed(rendered)
        self.assertIn('2,048 bytes',parsed.values['size'])
        self.assertEqual(parsed.values['sha256'],sha)
        self.assertIn('SHA-256 校验文件',parsed.values['checksum'])

    def test_cli_delivery_context_changes_html_only(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / 'facts.json'
            context = base / 'delivery.json'
            output = base / 'out'
            facts = {"title": "test", "mode": "independent", "target": SHA_TARGET,
                     "baseline": SHA_BASELINE, "scope": "scope", "limitations": [],
                     "sources": [], "coverage": [], "findings": []}
            source.write_text(report.json.dumps(facts))
            context.write_text(report.json.dumps({"profile": "package", "notice": "presentation only"}))
            with patch.object(sys, 'argv', ['report.py', str(source), '--out', str(output), '--delivery', str(context)]), \
                    patch.object(report, 'validate', return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                report.main()
            saved = report.json.loads((output / 'review.json').read_text())
            rendered = (output / 'index.html').read_text()
            self.assertNotIn('delivery', saved)
            self.assertIn('presentation only', rendered)


if __name__ == "__main__":
    unittest.main()
