import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common import ReviewError, contained, digest, load_config, load_json, lock, report_filename, safe_url, save_json, version_name
from review import collect, report_findings, html_report, render as render_raw, validate_review
from review_input import index_page, read_evidence
from publish import ApiRejected, Svn, deliver, publish, send_once


def review_data(status="已实现"):
    return {
        "summary": "完整目标实现的证据审核",
        "requirements": [{"id": "REQ-1", "module": "共享能力", "description": "复用已有能力", "source": "spec.md:1", "status": status, "verification": "静态检查", "evidence": "Shared.cs:1，完整目标快照", "finding_ids": []}],
        "findings": [], "checks": [{"name": "调用链检查", "result": "通过", "evidence": "追踪到 Shared.cs:1"}],
        "limitations": [], "document_gaps": [], "document_conflicts": []
    }


def render(run, review_path):
    """Existing rendering fixtures explicitly complete their synthetic coverage."""
    from review_progress import start, checkpoint, assemble
    context = load_json(run / "context.json")
    if context.get("progress_version") and not (run / "report-manifest.json").exists():
        data = load_json(review_path)
        plan = {"requirements_complete": True, "requirements_basis": "fixture requirements",
                "review_profile": "fixture static", "modules": [{"id": "all", "paths": ["*"], "depends_on": [], "dependencies_complete": False}],
                "requirements": [{"id": item["id"], "module": "all", "description": item["description"],
                                  "sources": [{"file": context["documents"][0]["file"], "anchor": "line:1"}]} for item in data["requirements"]]}
        start(run, plan, "full")
        checkpoint(run, {"module": "all", "status": "complete", "notes": "fixture evidence", "pending": [], "evidence_kind": "static", "review": data})
        assemble(run)
    return render_raw(run, review_path)


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openspec-review-test-")
        self.root = Path(self.temporary.name)
        self.repository = self.root / "source"
        self.repository.mkdir()
        self.git("init", "-b", "master")
        for name, content in (("Shared.cs", "public class Shared {}\n"), ("spec.md", "REQ-1 use Shared\nREQ-2 optional feature\n"), ("api.md", "no network API\n"), ("design.md", "reuse Shared\n"), ("openspec/changes/test/tasks.md", "- [ ] implement\n")):
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.git("branch", "release/test")
        self.config = {
            "schema_version": 1, "project": "fixture", "default_mode": "review",
            "git": {"url": str(self.repository), "auth": "credential-manager-or-ssh", "review_cache": str(self.root / "cache")},
            "versions": [{"version": "test", "target_branch": "release/test", "base_branch": "master", "openspec_changes": ["openspec/changes/test"], "documents": [{"id": kind, "kind": kind, "source": "target", "path": path} for kind, path in (("requirements", "spec.md"), ("api", "api.md"), ("design", "design.md"))], "svn_version_dir": "test"}],
            "svn": {"working_copy": str(self.root / "svn"), "repository_url": "https://svn.example.com/reports", "username": "tester", "auth": "local-cache"},
            "feishu": {"app_id": "test", "app_secret_env": "TEST_SECRET_NOT_USED", "chat_id": "test", "chat_name": "客户端开发-U3D"}
        }
        (self.root / "svn/test").mkdir(parents=True)
        self.config_path = self.root / "config.json"
        save_json(self.config_path, self.config)

    def tearDown(self):
        def writable_retry(function, path, exception):
            os.chmod(path, 0o700)
            function(path)

        import shutil
        shutil.rmtree(self.root, onerror=writable_retry)
        self.temporary.cleanup()

    def git(self, *arguments):
        result = subprocess.run(["git", "-c", "user.name=Review Test", "-c", "user.email=review@example.invalid", "-c", "commit.gpgsign=false", "-C", str(self.repository), *arguments], capture_output=True, check=True)
        return result.stdout.decode().strip()

    def collect(self):
        save_json(self.config_path, self.config)
        return collect(self.config_path, "release/test", "master")

    def sealed(self):
        run = self.collect()
        data = review_data()
        save_json(run / "review.json", data)
        render(run, run / "review.json")
        return run

    def test_zero_diff_still_has_full_implementation_and_requirements(self):
        run = self.collect()
        context = load_json(run / "context.json")
        self.assertEqual((run / "introduced.diff").read_bytes(), b"")
        self.assertTrue((run / "snapshot/Shared.cs").exists())
        data = review_data("未实现")
        validate_review(data, context, run)
        self.assertEqual(report_findings(data), [])
        data["requirements"][0]["status"] = "已实现"
        data["requirements"][0]["verification"] = "已验证"
        self.assertEqual(report_findings(data), [])
        self.assertEqual(self.git("branch", "--show-current"), "master")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_fetches_new_heads_and_keeps_old_snapshot(self):
        first = self.collect()
        self.git("checkout", "release/test")
        (self.repository / "Shared.cs").write_text("public class Shared { public int Added; }\n", encoding="utf-8")
        self.git("commit", "-am", "change")
        second = self.collect()
        self.assertNotEqual(load_json(first / "context.json")["target_sha"], load_json(second / "context.json")["target_sha"])
        self.assertIn("Added", (second / "introduced.diff").read_text())
        self.assertNotIn("Added", (first / "snapshot/Shared.cs").read_text())

    def test_input_index_covers_divergent_heads_and_unmodified_shared_code(self):
        self.git("checkout", "release/test")
        (self.repository / "新增 空格.cs").write_text("public class Added {}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "target feature")
        self.git("checkout", "master")
        (self.repository / "OnlyBase.cs").write_text("public class OnlyBase {}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base diverged")
        run = self.collect()
        page = index_page(run)
        entries = {item["path"]: item for item in page["entries"]}
        self.assertEqual(entries["新增 空格.cs"]["comparisons"], ["introduced", "heads"])
        self.assertEqual(entries["OnlyBase.cs"]["comparisons"], ["heads"])
        removed, _ = read_evidence(run, entry_id=entries["OnlyBase.cs"]["id"])
        self.assertIn("deleted file mode", removed["content"])
        shared, _ = read_evidence(run, source="snapshot", path="Shared.cs")
        self.assertIn("class Shared", shared["content"])
        with self.assertRaises(ReviewError):
            read_evidence(run, source="snapshot", path=".git")

    def test_input_cli_records_bounded_outputs_and_old_runs_can_render(self):
        run = self.collect()
        script = Path(__file__).with_name("review_input.py")
        import sys
        result = subprocess.run([sys.executable, "-X", "utf8", str(script), "read", "--run", str(run),
                                 "--source", "snapshot", "--path", "Shared.cs", "--max-bytes", "10"],
                                capture_output=True, check=True)
        page = json.loads(result.stdout)
        self.assertEqual(page["source_bytes"], 10)
        self.assertEqual(page["next_offset"], 10)
        event = json.loads((run / "input-usage.jsonl").read_text(encoding="utf-8"))
        # Windows stdout can translate LF to CRLF; accounting uses normalized LF.
        self.assertEqual(event["output_utf8_bytes"], len(result.stdout.replace(b"\r\n", b"\n")))
        context = load_json(run / "context.json")
        del context["artifacts"]["input-index.json"]
        context.pop("progress_version", None)
        save_json(run / "context.json", context)
        save_json(run / "review.json", review_data())
        self.assertTrue(render(run, run / "review.json").is_file())

    def test_render_rejects_modified_input_index(self):
        run = self.collect()
        save_json(run / "review.json", review_data())
        with (run / "input-index.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(ReviewError):
            render(run, run / "review.json")

    def test_csharp_collection_excludes_resources_and_preserves_deletions_and_renames(self):
        self.git("checkout", "release/test")
        self.git("mv", "Shared.cs", "Renamed.cs")
        paths = ["Root.CS", "Assets/Scripts/中文 空格.cs", "Assets/Scripts/Mixed.Cs",
                 "Assets/Scripts/Shared.cs.meta", "Assets/Panel.prefab", "Assets/Clip.anim",
                 "Assets/Material.mat", "Assets/Model.FBX", "Assets/Data.asset", "Other.lua"]
        for name in paths:
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("changed\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "mixed changes")
        run = self.collect()
        context = load_json(run / "context.json")
        self.assertEqual(context["review_scope"], "csharp-only")
        entries = index_page(run)["entries"]
        self.assertEqual({entry["path"] for entry in entries},
                         {"Shared.cs", "Renamed.cs", "Root.CS", "Assets/Scripts/中文 空格.cs", "Assets/Scripts/Mixed.Cs"})
        for name in ("introduced.diff", "heads.diff", "changes.txt"):
            content = (run / name).read_text(encoding="utf-8")
            self.assertIn("Shared.cs", content)
            self.assertIn("Renamed.cs", content)
            for excluded in paths[3:]:
                self.assertNotIn(excluded, content)
        for excluded in paths[3:]:
            with self.assertRaises(ReviewError):
                read_evidence(run, source="snapshot", path=excluded)
        upper, _ = read_evidence(run, source="snapshot", path="Root.CS")
        self.assertIn("changed", upper["content"])

    def test_resource_only_changes_keep_requirements_and_shared_csharp(self):
        self.git("checkout", "release/test")
        (self.repository / "Panel.prefab").write_text("m_Name: Panel\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "resource only")
        run = self.collect()
        for name in ("introduced.diff", "heads.diff", "changes.txt"):
            self.assertEqual((run / name).read_bytes(), b"")
        self.assertEqual(index_page(run)["entries"], [])
        context = load_json(run / "context.json")
        document = next(item for item in context["documents"] if item["kind"] == "requirements")
        requirement, _ = read_evidence(run, source="documents", path=document["file"].removeprefix("documents/"))
        self.assertIn("REQ-1", requirement["content"])
        shared, _ = read_evidence(run, source="snapshot", path="Shared.cs")
        self.assertIn("class Shared", shared["content"])

    def test_configured_local_project_is_validated_without_checkout(self):
        self.git("remote", "add", "origin", str(self.repository))
        self.config["git"]["local_path"] = str(self.repository)
        run = self.collect()
        self.assertTrue((run / "context.json").is_file())
        self.assertEqual(self.git("branch", "--show-current"), "master")
        self.git("remote", "set-url", "origin", "https://other.example.com/repo.git")
        with self.assertRaises(ReviewError):
            self.collect()

    def test_missing_branch_cannot_use_previous_cache(self):
        self.collect()
        self.git("branch", "-D", "release/test")
        with self.assertRaises(ReviewError):
            self.collect()

    def test_no_common_ancestor_stops(self):
        self.git("checkout", "--orphan", "other")
        self.git("rm", "-rf", ".")
        (self.repository / "orphan.txt").write_text("unrelated")
        self.git("add", ".")
        self.git("commit", "-m", "orphan")
        self.git("branch", "-f", "release/test", "other")
        with self.assertRaises(ReviewError):
            self.collect()

    def test_document_gaps_stay_internal(self):
        self.config["versions"][0]["documents"][1]["path"] = "missing.md"
        run = self.collect()
        context = load_json(run / "context.json")
        data = review_data()
        data["requirements"][0]["verification"] = "已验证"
        self.assertTrue(context["document_gaps"])
        html = html_report(data, context)
        for gap in context["document_gaps"]:
            self.assertNotIn(gap, html)
        self.assertNotIn("审核结论", html)

    def test_html_escapes_evidence_and_seals_report(self):
        run = self.collect()
        data = review_data()
        data["summary"] = "<script>alert('x')</script> & 审核"
        context = load_json(run / "context.json")
        context["project"] = data["summary"]
        save_json(run / "context.json", context)
        save_json(run / "review.json", data)
        manifest = load_json(render(run, run / "review.json"))
        self.assertTrue(manifest["file"].startswith("test-ai-review-"))
        html = manifest["html"]
        self.assertNotIn(data["summary"], html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("P1: 阻断", html)
        self.assertEqual(manifest["sha256"], digest(html.encode("utf-8")))
        self.assertFalse(list(run.glob("*.html")))
        self.assertFalse(list(run.glob("*.png")))
        self.assertFalse(list(run.glob("*.jpg")))
        with self.assertRaises(ReviewError):
            render(run, run / "review.json")

    def test_modified_document_and_snapshot_are_rejected(self):
        run = self.collect()
        save_json(run / "review.json", review_data())
        document = load_json(run / "context.json")["documents"][0]
        (run / document["file"]).write_text("tampered")
        with self.assertRaises(ReviewError):
            render(run, run / "review.json")
        other = self.collect()
        save_json(other / "review.json", review_data())
        (other / "snapshot/Shared.cs").write_text("tampered")
        with self.assertRaises(ReviewError):
            render(other, other / "review.json")

    def test_findings_validate_locations_and_evidence_levels(self):
        run = self.collect()
        context = load_json(run / "context.json")
        data = review_data()
        finding = {"id": "ISSUE-1", "priority": "P1", "module": "core", "title": "risk", "scope": "client", "resolution": "open", "requirement_ids": ["REQ-1"], "source": "spec.md:1", "path": "Shared.cs", "line": 1, "evidence": "待验证", "origin": "历史遗留", "trigger": "trigger", "expected": "expected", "actual": "actual", "impact": "impact", "fix": "fix", "regression": "regression"}
        data["findings"] = [finding]
        validate_review(data, context, run)
        self.assertEqual(report_findings(data), [])
        finding["evidence"] = "静态证据充分"
        self.assertEqual(report_findings(data), [finding])
        finding["line"] = 999
        with self.assertRaises(ReviewError):
            validate_review(data, context, run)
        finding["line"] = 1
        finding["priority"] = "P0"
        with self.assertRaises(ReviewError):
            validate_review(data, context, run)

    def test_config_secrets_branch_mapping_and_svn_path(self):
        self.config["git"]["password"] = "test-secret"
        save_json(self.config_path, self.config)
        with self.assertRaises(ReviewError):
            load_config(self.config_path)
        del self.config["git"]["password"]
        self.config["versions"].append(copy.deepcopy(self.config["versions"][0]))
        with self.assertRaises(ReviewError):
            self.collect()
        self.config["versions"][0]["svn_version_dir"] = "../escape"
        with self.assertRaises(ReviewError):
            Svn(self.config["svn"], self.config["versions"][0])

    def test_publish_resumes_and_never_commits_twice(self):
        run = self.sealed()
        service = FakeFeishu()
        service.reject_summary_once = True
        commits = []

        def commit(instance, report, expected_hash, marker, state, save, content=None):
            if not state.get("svn_revision"):
                self.assertEqual(report.parent, instance.directory)
                report.write_bytes(content)
                commits.append(report.name)
                state["svn_revision"] = "42"
                save()
            return state["svn_revision"]

        with patch("publish.Feishu", return_value=service), patch.object(Svn, "commit", commit):
            with self.assertRaises(ApiRejected):
                publish(self.config_path, run)
            state = publish(self.config_path, run)
            calls = len(service.calls)
            self.assertEqual(state["svn_revision"], "42")
            publish(self.config_path, run)
            self.assertEqual(len(service.calls), calls)
        self.assertEqual(len(commits), 1)
        self.assertEqual(service.uploads, 1)
        self.assertEqual([kind for kind in service.calls if kind == "file"], ["file"])
        report = Path(state["report_path"])
        self.assertEqual(service.uploaded_paths, [report])
        self.assertEqual(service.uploaded_bytes, [report.read_bytes()])
        self.assertEqual(list(self.root.rglob("*.html")), [report])
        self.assertEqual(list(report.parent.iterdir()), [report])

    def test_modified_sealed_html_and_lost_state_block_publication(self):
        run = self.sealed()
        manifest = load_json(run / "report-manifest.json")
        manifest["html"] = "tampered"
        save_json(run / "report-manifest.json", manifest)
        with patch("publish.Feishu") as service:
            with self.assertRaises(ReviewError):
                publish(self.config_path, run)
            service.assert_not_called()
        other = self.sealed()
        (other / ".publication-started").touch()
        with self.assertRaises(ReviewError):
            publish(self.config_path, other)

    def test_publication_writes_only_svn_html_and_uploads_identical_bytes(self):
        run = self.sealed()
        manifest = load_json(run / "report-manifest.json")
        service = FakeFeishu()

        def invoke(*arguments):
            if arguments[0] == "status":
                return b'<status><entry><wc-status item="unversioned" props="none"/></entry></status>'
            return b"<properties/>"

        with patch("publish.Feishu", return_value=service), patch.object(Svn, "preflight"), patch.object(Svn, "invoke", side_effect=invoke) as execute, patch.object(Svn, "remote_revision", return_value="42"):
            state = publish(self.config_path, run)
        report = Path(state["report_path"])
        self.assertEqual(report.parent, self.root / "svn/test")
        self.assertEqual(list(self.root.rglob("*.html")), [report])
        self.assertEqual(list(report.parent.iterdir()), [report])
        self.assertEqual(service.uploaded_paths, [report])
        self.assertEqual(service.uploaded_bytes, [manifest["html"].encode("utf-8")])
        commits = [call.args for call in execute.call_args_list if call.args[0] == "commit"]
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0][-1], str(report) + "@")
        self.assertEqual(service.calls, ["file", "text"])
        self.assertNotIn("conclusion", manifest)
        self.assertNotIn("结论", service.contents[-1]["text"])
        self.assertNotIn("待验证", service.contents[-1]["text"])

    def test_report_contains_only_open_client_facts(self):
        run = self.collect()
        context = load_json(run / "context.json")
        data = review_data()
        data["summary"] = "DO_NOT_SHOW_SUMMARY"
        data["requirements"][0]["description"] = "DO_NOT_SHOW_COMPLETED_REQUIREMENT"
        data["checks"][0]["evidence"] = "DO_NOT_SHOW_CHECK"
        data["limitations"] = ["DO_NOT_SHOW_LIMITATION"]
        data["document_conflicts"] = ["DO_NOT_SHOW_DOCUMENT_CONFLICT"]
        data["document_gaps"] = ["DO_NOT_SHOW_DOCUMENT_GAP"]
        base = {"id": "ISSUE-1", "priority": "P2", "module": "client-module", "title": "CLIENT_FACT", "scope": "client", "resolution": "open", "requirement_ids": ["REQ-1"], "source": "DO_NOT_SHOW_DOCUMENT_SOURCE", "path": "Shared.cs", "line": 1, "evidence": "静态证据充分", "origin": "本次引入", "trigger": "FACT_TRIGGER", "expected": "FACT_EXPECTED", "actual": "<script>FACT_ACTUAL</script>", "impact": "FACT_IMPACT", "fix": "DO_NOT_SHOW_ADVICE", "regression": "DO_NOT_SHOW_REGRESSION"}
        data["findings"] = [base]
        for index, changes in enumerate(({"scope": "backend-integration"}, {"scope": "configuration"}, {"scope": "visual-layout"}, {"resolution": "resolved"}, {"resolution": "removed"}, {"resolution": "cancelled"}, {"resolution": "superseded"}, {"evidence": "待验证"})):
            item = dict(base, **changes)
            item.update(id="EXCLUDED-" + str(index), title="DO_NOT_SHOW_" + str(index), module="DO_NOT_SHOW_MODULE_" + str(index))
            data["findings"].append(item)
        validate_review(data, context, run)
        save_json(run / "review.json", data)
        manifest = load_json(render(run, run / "review.json"))
        html = manifest["html"]
        for fact in ("CLIENT_FACT", "FACT_TRIGGER", "FACT_EXPECTED", "&lt;script&gt;FACT_ACTUAL&lt;/script&gt;", "FACT_IMPACT", "Shared.cs:1"):
            self.assertIn(fact, html)
        for hidden in ("DO_NOT_SHOW", "审核结论", "证据状态", "需求状态", "验证状态", "文档证据", "需求矩阵", "静态证据充分", "待验证", "已实现", "data-evidence", "id='status'"):
            self.assertNotIn(hidden, html)
        self.assertEqual(manifest["counts"], {"P1": 0, "P2": 1, "P3": 0, "P4": 0})
        self.assertNotIn("conclusion", manifest)
        self.assertEqual(html.count("<article class='finding'"), 1)
        del base["scope"]
        with self.assertRaises(ReviewError):
            validate_review(data, context, run)

    def test_empty_client_scope_has_no_conclusion_or_completed_items(self):
        run = self.collect()
        data = review_data()
        data["requirements"] = []
        validate_review(data, load_json(run / "context.json"), run)
        html = html_report(data, load_json(run / "context.json"))
        self.assertIn("本次记录的客户端问题数量：0", html)
        self.assertNotIn("通过", html)
        self.assertNotIn("已实现", html)

    def test_legacy_manifest_resumes_upload_from_svn(self):
        run = self.sealed()
        manifest = load_json(run / "report-manifest.json")
        content = manifest.pop("html").encode("utf-8")
        manifest["schema_version"] = 1
        save_json(run / "report-manifest.json", manifest)
        (run / manifest["file"]).write_bytes(content)
        report = self.root / "svn/test" / manifest["file"]
        report.write_bytes(content)
        service = FakeFeishu()

        def commit(instance, report, expected_hash, marker, state, save, content=None):
            state["svn_revision"] = "42"
            save()

        with patch("publish.Feishu", return_value=service), patch.object(Svn, "commit", commit):
            publish(self.config_path, run)
        self.assertEqual(service.uploaded_paths, [report])
        self.assertEqual(service.uploaded_bytes, [content])


class FakeFeishu:
    def __init__(self):
        self.calls = []
        self.contents = []
        self.uploads = 0
        self.uploaded_paths = []
        self.uploaded_bytes = []
        self.reject_summary_once = False
        self.uncertain = False

    def upload(self, report):
        self.uploads += 1
        self.uploaded_paths.append(report)
        self.uploaded_bytes.append(report.read_bytes())
        return "file-key"

    def send(self, message_type, content, request_id):
        self.calls.append(message_type)
        self.contents.append(content)
        if self.uncertain:
            raise ReviewError("uncertain timeout")
        if message_type == "text" and self.reject_summary_once:
            self.reject_summary_once = False
            raise ApiRejected("rejected")
        return "message-" + str(len(self.calls))


class PublicationTests(unittest.TestCase):
    def test_svn_uses_unicode_working_directory_and_precise_relative_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "客户端" / "1.2.0"
            directory.mkdir(parents=True)
            svn = Svn({"working_copy": str(root), "report_root": str(directory.parent), "repository_url": "svn://example.com/reports", "auth": "local-cache"}, {"version": "1.2.0"})
            with patch("publish.command", return_value=b"") as execute:
                svn.invoke("info", "--xml", str(directory) + "@")
                self.assertEqual(execute.call_args.kwargs["cwd"], directory)
                self.assertIn(".@", execute.call_args.args[0])
                svn.invoke("commit", "--depth", "empty", "-m", "marker", str(directory) + "@", str(directory / "1.2.0-review.html") + "@")
                self.assertEqual(execute.call_args.kwargs["cwd"], directory)
                self.assertIn("1.2.0-review.html@", execute.call_args.args[0])
                self.assertIn(".@", execute.call_args.args[0])
                svn.invoke("info", "--xml", svn.url + "@")
                self.assertIsNone(execute.call_args.kwargs["cwd"])

    def test_version_is_a_safe_single_component_and_names_the_report(self):
        for value in ("", "release/1.2.0", "../escape", "1.2.", "CON", "LPT1.txt", "version ", "a:b"):
            with self.assertRaises(ReviewError):
                version_name(value)
        self.assertEqual(report_filename({"version": "1.2.0", "run_id": "test-run"}), "1.2.0-ai-review-test-run.html")

    def test_missing_version_directory_is_created_and_committed_with_only_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "客户端"
            report_root.mkdir()
            unrelated = report_root / "unrelated.txt"
            unrelated.write_text("dirty")
            svn = Svn({"working_copy": str(root), "report_root": str(report_root), "repository_url": "svn://example.com/reports", "username": "", "auth": "local-cache"}, {"version": "1.2.0"})
            report = svn.directory / "1.2.0-ai-review-test.html"
            content = "sealed 审核".encode("utf-8")
            self.assertFalse(svn.directory.exists())
            state = {}
            saved = []
            calls = []

            def invoke(*arguments):
                calls.append(arguments)
                if arguments[0] == "list":
                    return b"<lists><list/></lists>"
                if arguments[0] == "status":
                    return b'<status><entry><wc-status item="unversioned" props="none"/></entry></status>'
                if arguments[0] == "proplist":
                    return b"<properties/>"
                return b""

            with patch.object(svn, "preflight"), patch.object(svn, "invoke", side_effect=invoke), patch.object(svn, "remote_revision", return_value="8"):
                svn.commit(report, digest(content), "marker", state, lambda: saved.append(copy.deepcopy(state)), content=content)
            self.assertTrue(svn.directory.is_dir())
            self.assertEqual(saved[0]["svn_owned_directory"], "客户端/1.2.0")
            commit_call = next(arguments for arguments in calls if arguments[0] == "commit")
            self.assertEqual(commit_call[-2:], (str(svn.directory) + "@", str(svn.directory / report.name) + "@"))
            self.assertEqual(unrelated.read_text(), "dirty")
            self.assertEqual(report.read_bytes(), content)
            self.assertEqual(list(root.rglob("*.html")), [report])
            self.assertEqual(list(svn.directory.iterdir()), [report])

    def test_owned_directory_creation_resumes_without_readding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "client"
            (report_root / "1.2.0").mkdir(parents=True)
            svn = Svn({"working_copy": str(root), "report_root": str(report_root), "repository_url": "svn://example.com/reports", "auth": "local-cache"}, {"version": "1.2.0"})
            state = {"svn_owned_directory": "client/1.2.0"}
            calls = []

            def invoke(*arguments):
                calls.append(arguments)
                if arguments[0] == "status":
                    return b'<status><entry><wc-status item="added" props="none"/></entry></status>'
                return b"<properties/>"

            with patch.object(svn, "invoke", side_effect=invoke):
                self.assertEqual(svn.prepare_directory(root / "report.html", state, lambda: None), [str(svn.directory) + "@"])
            self.assertFalse(any(arguments[0] in ("add", "list") for arguments in calls))
            (svn.directory / "unrelated.txt").write_text("user file")
            with self.assertRaises(ReviewError):
                svn.prepare_directory(root / "report.html", state, lambda: None)

    def test_remote_only_version_is_updated_instead_of_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "client"
            report_root.mkdir()
            svn = Svn({"working_copy": str(root), "report_root": str(report_root), "repository_url": "svn://example.com/reports", "auth": "local-cache"}, {"version": "1.2.0"})
            state = {}
            calls = []

            def invoke(*arguments):
                calls.append(arguments)
                if arguments[0] == "list":
                    return b'<lists><list><entry kind="dir"><name>1.2.0</name></entry></list></lists>'
                return b""

            with patch.object(svn, "invoke", side_effect=invoke), patch.object(svn, "check_versioned_directory"):
                self.assertEqual(svn.prepare_directory(root / "report.html", state, lambda: None), [])
            self.assertTrue(any(arguments[0] == "update" for arguments in calls))
            self.assertNotIn("svn_owned_directory", state)

    def test_report_root_outside_working_copy_and_existing_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "wc").mkdir()
            (root / "outside").mkdir()
            with self.assertRaises(ReviewError):
                Svn({"working_copy": str(root / "wc"), "report_root": str(root / "outside"), "repository_url": "svn://example.com/reports", "auth": "local-cache"}, {"version": "1.2.0"})
            report_root = root / "wc/client"
            report_root.mkdir()
            (report_root / "1.2.0").write_text("existing file")
            svn = Svn({"working_copy": str(root / "wc"), "report_root": str(report_root), "repository_url": "svn://example.com/reports", "auth": "local-cache"}, {"version": "1.2.0"})
            with self.assertRaises(ReviewError):
                svn.prepare_directory(root / "report.html", {}, lambda: None)

    def test_repository_urls_cannot_embed_credentials_or_remote_commands(self):
        for value in ("https://user:password@example.com/repo", "https://example.com/repo?token=secret", "ext::command", "--upload-pack=command"):
            with self.assertRaises(ReviewError):
                safe_url(value)
        safe_url("git@example.com:team/repo.git")

    def test_svn_preflight_checks_url_and_conflicts_but_allows_unrelated_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "version").mkdir()
            svn = Svn({"working_copy": str(root), "repository_url": "https://svn.example.com/reports", "username": "tester", "auth": "local-cache"}, {"svn_version_dir": "version"})
            import xml.etree.ElementTree as ElementTree

            def info(target):
                entry = ElementTree.Element("entry")
                ElementTree.SubElement(entry, "url").text = svn.config["repository_url"] if target == root else svn.url
                wc_info = ElementTree.SubElement(entry, "wc-info")
                ElementTree.SubElement(wc_info, "wcroot-abspath").text = str(root)
                return entry

            def status(*arguments):
                if arguments[0] == "status" and "--depth" not in arguments:
                    return b'<status><target><entry path="unrelated"><wc-status item="modified" props="none"/></entry></target></status>'
                return b"<status/>"

            with patch.object(svn, "info", side_effect=info), patch.object(svn, "invoke", side_effect=status):
                svn.preflight()
            with patch.object(svn, "info", side_effect=info), patch.object(svn, "invoke", return_value=b'<status><entry><wc-status item="conflicted" props="none"/></entry></status>'):
                with self.assertRaises(ReviewError):
                    svn.preflight()
            wrong = info(root)
            wrong.find("url").text = "https://wrong.example.com/reports"
            with patch.object(svn, "info", return_value=wrong):
                with self.assertRaises(ReviewError):
                    svn.preflight()

    def test_uncertain_message_is_not_resent(self):
        service = FakeFeishu()
        service.uncertain = True
        state = {}
        saved = []
        with self.assertRaises(ReviewError):
            send_once(service, state, lambda: saved.append(copy.deepcopy(state)), "file", "file", {"file_key": "key"})
        service.uncertain = False
        with self.assertRaises(ReviewError):
            send_once(service, state, lambda: None, "file", "file", {"file_key": "key"})
        self.assertTrue(saved[0]["file_pending"])
        self.assertEqual(len(service.calls), 1)

    def test_precise_svn_commit_and_unrelated_files_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "version"
            directory.mkdir()
            report = root / "report.html"
            report.write_text("report", encoding="utf-8")
            unrelated = directory / "unrelated.txt"
            unrelated.write_text("dirty")
            svn = Svn({"working_copy": str(root), "repository_url": "https://svn.example.com/reports", "username": "tester", "auth": "local-cache"}, {"svn_version_dir": "version"})
            calls = []

            def invoke(*arguments):
                calls.append(arguments)
                if arguments[0] == "status":
                    return b'<status><target><entry><wc-status item="unversioned" props="none"/></entry></target></status>'
                if arguments[0] == "proplist":
                    return b"<properties/>"
                return b""

            state = {}
            with patch.object(svn, "preflight"), patch.object(svn, "invoke", side_effect=invoke), patch.object(svn, "remote_revision", return_value="7"):
                self.assertEqual(svn.commit(report, digest(report.read_bytes()), "marker", state, lambda: None), "7")
                svn.commit(report, digest(report.read_bytes()), "marker", state, lambda: None)
            commit_calls = [arguments for arguments in calls if arguments[0] == "commit"]
            self.assertEqual(len(commit_calls), 1)
            self.assertEqual(commit_calls[0][-1], str(directory / report.name) + "@")
            self.assertNotIn(str(root) + "@", commit_calls[0])
            self.assertEqual(unrelated.read_text(), "dirty")

    def test_svn_unknown_commit_only_reconciles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "version").mkdir()
            svn = Svn({"working_copy": str(root), "repository_url": "https://svn.example.com/reports", "username": "tester", "auth": "local-cache"}, {"svn_version_dir": "version"})
            state = {"svn_pending": True}
            with patch.object(svn, "remote_revision", return_value="9"), patch.object(svn, "invoke") as invoke:
                self.assertEqual(svn.commit(root / "report.html", "hash", "marker", state, lambda: None), "9")
                invoke.assert_not_called()
            self.assertNotIn("svn_pending", state)
            state = {"svn_pending": True}
            with patch.object(svn, "remote_revision", side_effect=ReviewError("unknown")), patch.object(svn, "invoke") as invoke:
                with self.assertRaises(ReviewError):
                    svn.commit(root / "report.html", "hash", "marker", state, lambda: None)
                invoke.assert_not_called()

    def test_path_escape_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ("../escape", "/root", "C:/escape", "a/../../escape"):
                with self.assertRaises(ReviewError):
                    contained(root, value)
            with lock(root / ".lock"):
                with self.assertRaises(ReviewError):
                    with lock(root / ".lock"):
                        pass


if __name__ == "__main__":
    unittest.main()
