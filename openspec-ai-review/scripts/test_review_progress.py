import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from common import ReviewError, digest_file, load_json, save_json
import document_cache
from review import render
from review_progress import assemble, checkpoint, start, status
import test_review as fixtures


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review-doc-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_run(self, name, suffix, data):
        run = self.root / name
        (run / "documents").mkdir(parents=True)
        path = run / ("documents/spec" + suffix)
        path.write_bytes(data)
        save_json(run / "context.json", {"documents": [{"file": path.relative_to(run).as_posix(), "sha256": digest_file(path)}]})
        return run, path.relative_to(run).as_posix()

    def test_cache_reuse_and_source_parser_invalidation(self):
        one, file = self.make_run("one", ".md", "需求一\n需求二\n".encode())
        first = document_cache.page(one, file)
        self.assertFalse(first["cache_hit"])
        two, _ = self.make_run("two", ".md", "需求一\n需求二\n".encode())
        second = document_cache.page(two, file)
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["cache_key"], second["cache_key"])
        three, _ = self.make_run("three", ".md", "需求已修改\n".encode())
        self.assertNotEqual(first["cache_key"], document_cache.page(three, file)["cache_key"])
        with patch.object(document_cache, "PARSER_VERSION", "next"):
            self.assertNotEqual(first["cache_key"], document_cache.page(two, file)["cache_key"])
        (two / file).write_text("tampered", encoding="utf-8")
        with self.assertRaises(ReviewError):
            document_cache.page(two, file)

    def test_long_text_pagination_is_lossless(self):
        text = "中文" * 10000
        run, file = self.make_run("long", ".md", text.encode())
        cursor, parts = {"offset": 0, "text_offset": 0}, []
        while cursor:
            result = document_cache.page(run, file, **cursor)
            parts.extend(block["text"] for block in result["blocks"])
            cursor = result["next"]
        self.assertEqual("".join(parts), text)

    def test_docx_tables_revisions_and_visual_warnings(self):
        source = self.root / "source.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>主需求</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格条件</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:del><w:r><w:delText>旧需求</w:delText></w:r></w:del><w:r><w:drawing/></w:r></w:p></w:body></w:document>')
        run, file = self.make_run("docx", ".docx", source.read_bytes())
        result = document_cache.page(run, file)
        self.assertEqual([block["text"] for block in result["blocks"]], ["主需求", "表格条件", "[deleted:旧需求]"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["blocks"][1]["anchor"], "word/document.xml:p:2")
        self.assertTrue(result["blocks"][1]["table_location"].endswith("tr:1/tc:1"))

    def test_unsupported_and_corrupted_cache_never_claim_success(self):
        run, file = self.make_run("pdf", ".pdf", b"%PDF manual")
        result = document_cache.page(run, file)
        self.assertEqual(result["status"], "manual-required")
        cached = self.root / ".document-cache" / (result["cache_key"] + ".json")
        content = load_json(cached)
        content["payload"]["status"] = "text-extracted"
        save_json(cached, content)
        with self.assertRaises(ReviewError):
            document_cache.page(run, file)


class ProgressTests(unittest.TestCase):
    tearDown = fixtures.GitFixture.tearDown
    git = fixtures.GitFixture.git
    collect = fixtures.GitFixture.collect

    def setUp(self):
        fixtures.GitFixture.setUp(self)
        for name in ("A/A.cs", "B/B.cs"):
            path = self.repository / name
            path.parent.mkdir()
            path.write_text("public class " + path.stem + " {}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "modules")
        self.git("branch", "-f", "release/test", "master")

    def plan(self, run):
        context = load_json(run / "context.json")
        source = next(item["file"] for item in context["documents"] if item["kind"] == "requirements")
        return {"requirements_complete": True, "requirements_basis": "spec.md current effective requirements", "review_profile": "fixture static",
                "requirements": [{"id": "REQ-" + str(i), "module": module, "description": "requirement " + str(i),
                                  "sources": [{"file": source, "anchor": "line:" + str(i)}]} for i, module in ((1, "a"), (2, "b"))],
                "modules": [{"id": "shared", "paths": ["Shared.cs"], "depends_on": [], "dependencies_complete": True},
                            {"id": "a", "paths": ["A"], "depends_on": ["shared"], "dependencies_complete": True},
                            {"id": "b", "paths": ["B"], "depends_on": [], "dependencies_complete": True}]}

    def data(self, identifier):
        result = fixtures.review_data()
        if identifier == "shared":
            result["requirements"] = []
        else:
            result["requirements"][0]["id"] = "REQ-1" if identifier == "a" else "REQ-2"
        result["summary"] = identifier
        return result

    def complete(self, run, identifier, data=None, **extra):
        return checkpoint(run, {"module": identifier, "status": "complete", "pending": [], "notes": "Reviewed C# entry and requirements", "evidence_kind": "static", "review": data or self.data(identifier), **extra})

    def seal(self, run, plan=None):
        start(run, plan or self.plan(run), "full")
        for identifier in ("shared", "a", "b"):
            self.complete(run, identifier)
        assemble(run)
        render(run, run / "review.json")

    def change(self, path, text="// changed\n"):
        self.git("checkout", "release/test")
        (self.repository / path).write_text(text, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "change " + path)

    def test_resume_preserves_completed_modules_and_partial_draft(self):
        run = self.collect()
        plan = self.plan(run)
        start(run, plan, "full")
        self.complete(run, "shared")
        checkpoint(run, {"module": "a", "status": "in_progress", "notes": "entry examined", "pending": ["callback"], "review": self.data("a")})
        resumed = start(run)
        self.assertEqual(resumed["modules"]["shared"]["status"], "complete")
        self.assertEqual(resumed["modules"]["a"]["draft_review"], self.data("a"))
        with self.assertRaises(ReviewError):
            assemble(run)
        save_json(run / "review.json", self.data("a"))
        with self.assertRaises(ReviewError):
            render(run, run / "review.json")
        self.complete(run, "a")
        self.complete(run, "b")
        assemble(run)
        altered = load_json(run / "review.json")
        altered["summary"] = "unrecorded conclusion"
        save_json(run / "altered.json", altered)
        with self.assertRaises(ReviewError):
            render(run, run / "altered.json")
        manifest = load_json(render(run, run / "review.json"))
        self.assertEqual(manifest["progress_sha256"], digest_file(run / "progress.final.json"))
        with self.assertRaises(ReviewError):
            self.complete(run, "a")

    def test_no_change_reuses_and_shared_change_invalidates_dependents_only(self):
        first = self.collect()
        self.seal(first)
        same = self.collect()
        self.assertEqual(status(start(same))["reused"], 3)
        self.change("Shared.cs")
        changed = self.collect()
        state = start(changed)
        self.assertEqual(state["modules"]["shared"]["status"], "pending")
        self.assertEqual(state["modules"]["a"]["status"], "pending")
        self.assertEqual(state["modules"]["b"]["status"], "complete")
        self.assertEqual(state["modules"]["b"]["reused_from"], first.name)

    def test_unknown_dependencies_force_full_on_any_csharp_change(self):
        first = self.collect()
        plan = self.plan(first)
        plan["modules"][1]["dependencies_complete"] = False
        self.seal(first, plan)
        self.change("B/B.cs")
        state = start(self.collect())
        self.assertEqual(status(state)["reused"], 0)
        self.assertIn("C# changed with incomplete dependency knowledge", state["fallback_reasons"])

    def test_document_change_requires_new_effective_plan_and_full_review(self):
        first = self.collect()
        self.seal(first)
        self.change("spec.md", "REQ-1 changed\nREQ-2 cancelled\n")
        second = self.collect()
        with self.assertRaises(ReviewError):
            start(second)
        plan = self.plan(second)
        plan["requirements"] = plan["requirements"][:1]
        state = start(second, plan)
        self.assertEqual(status(state)["reused"], 0)
        self.assertIn("documents or document gaps changed", state["fallback_reasons"])

    def test_new_and_deleted_files_invalidate_owner(self):
        first = self.collect()
        self.seal(first)
        self.git("checkout", "release/test")
        self.git("mv", "A/A.cs", "A/Renamed.cs")
        self.git("commit", "-m", "rename")
        state = start(self.collect())
        self.assertEqual(state["modules"]["a"]["status"], "pending")
        self.assertEqual(status(state)["reused"], 2)

    def test_baseline_and_rules_changes_force_full_and_tampering_is_rejected(self):
        first = self.collect()
        self.seal(first)
        self.git("checkout", "master")
        (self.repository / "B/B.cs").write_text("// base changed\n", encoding="utf-8")
        self.git("commit", "-am", "base change")
        second = self.collect()
        state = start(second)
        self.assertIn("base_sha changed", state["fallback_reasons"])
        self.assertEqual(status(state)["reused"], 0)
        with patch("review_progress.rules_digest", return_value="new rules"):
            with self.assertRaises(ReviewError):
                start(second)
        (first / "progress.final.json").write_text("{}", encoding="utf-8")
        third = self.collect()
        with self.assertRaises(ReviewError):
            start(third, self.plan(third), previous=first)

    def test_old_open_findings_require_explicit_recheck(self):
        first = self.collect()
        start(first, self.plan(first), "full")
        data = self.data("a")
        data["findings"] = [{"id": "ISSUE-1", "priority": "P2", "module": "a", "title": "fixture issue", "scope": "client", "resolution": "open", "requirement_ids": ["REQ-1"], "source": "REQ-1", "path": "A/A.cs", "line": 1, "evidence": "静态证据充分", "origin": "历史遗留", "trigger": "trigger", "expected": "expected", "actual": "actual", "impact": "impact", "fix": "fix", "regression": "regression"}]
        for identifier in ("shared", "a", "b"):
            self.complete(first, identifier, data if identifier == "a" else None)
        assemble(first)
        render(first, first / "review.json")
        second = self.collect()
        state = start(second)
        self.assertEqual(state["modules"]["a"]["status"], "pending")
        with self.assertRaises(ReviewError):
            self.complete(second, "a")
        self.complete(second, "a", rechecked_findings={"ISSUE-1": {"resolution": "resolved", "evidence": "fixture current recheck"}})
        self.assertFalse(assemble(second)["findings"])

    def test_unowned_changes_and_missing_coverage_cannot_be_skipped(self):
        first = self.collect()
        self.seal(first)
        self.change("Unknown.cs")
        second = self.collect()
        with self.assertRaises(ReviewError):
            start(second)
        plan = self.plan(second)
        plan["modules"].append({"id": "new", "paths": ["Unknown.cs"], "depends_on": [], "dependencies_complete": False})
        state = start(second, plan)
        self.assertEqual(status(state)["reused"], 0)
        with self.assertRaises(ReviewError):
            self.complete(second, "a", self.data("shared"))

    def test_resource_only_change_reuses_csharp_and_forced_full_does_not(self):
        first = self.collect()
        self.seal(first)
        self.change("Panel.prefab", "m_Name: changed\n")
        second = self.collect()
        self.assertEqual(status(start(second))["reused"], 3)
        third = self.collect()
        self.assertEqual(status(start(third, self.plan(third), "full"))["reused"], 0)

    def test_runtime_evidence_and_rule_changes_are_not_silently_reused(self):
        first = self.collect()
        start(first, self.plan(first), "full")
        for identifier in ("shared", "a", "b"):
            self.complete(first, identifier, evidence_kind="runtime" if identifier == "a" else "static")
        assemble(first)
        render(first, first / "review.json")
        second = self.collect()
        self.assertEqual(start(second)["modules"]["a"]["status"], "pending")
        with patch("review.rules_digest", return_value="new rules"), patch("review_progress.rules_digest", return_value="new rules"):
            third = self.collect()
            state = start(third)
            self.assertIn("rules_sha256 changed", state["fallback_reasons"])
            self.assertEqual(status(state)["reused"], 0)

    def test_cli_full_checkpoint_assemble_and_resume(self):
        import subprocess
        import sys
        run = self.collect()
        save_json(run / "plan.json", self.plan(run))
        script = Path(__file__).with_name("review_progress.py")
        def cli(*args):
            return subprocess.run([sys.executable, "-X", "utf8", str(script), *args, "--run", str(run)], capture_output=True, check=True)
        cli("start", "--plan", str(run / "plan.json"), "--mode", "full")
        cli("start")
        for identifier in ("shared", "a", "b"):
            submission = {"module": identifier, "status": "complete", "pending": [], "notes": "fixture CLI coverage", "evidence_kind": "static", "review": self.data(identifier)}
            save_json(run / "checkpoint.json", submission)
            cli("checkpoint", "--file", str(run / "checkpoint.json"))
        cli("status", "--module", "a")
        cli("assemble")
        self.assertTrue((run / "review.json").is_file())
        self.assertIn("progress-checkpoint", (run / "input-usage.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
