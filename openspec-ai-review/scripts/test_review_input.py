import json
from pathlib import Path
import tempfile
import unittest

from common import ReviewError, digest_file, load_json, save_json
from review_input import (build_index, index_page, numstat_records, read_evidence,
                          read_window, record_output, usage_summary)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="review-input-test-")
        self.run = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, introduced, heads=None, introduced_stat=None, heads_stat=None, review_scope="csharp-only"):
        if heads is None:
            heads = introduced
        if introduced_stat is None:
            introduced_stat = b"1\t1\tExample.cs\0" if introduced else b""
        if heads_stat is None:
            heads_stat = introduced_stat
        (self.run / "introduced.diff").write_bytes(introduced)
        (self.run / "heads.diff").write_bytes(heads)
        index = build_index(self.run, {"introduced": introduced_stat, "heads": heads_stat}, review_scope)
        save_json(self.run / "context.json", {"review_scope": review_scope, "documents": [], "artifacts": {
            "input-index.json": digest_file(self.run / "input-index.json")}})
        return index

    def patch(self, path="Example.cs", content="-old\n+new\n"):
        return ("diff --git a/" + path + " b/" + path + "\n@@ -1 +1 @@\n" + content).encode("utf-8")

    def test_whole_diff_alias_and_shared_block_deduplication(self):
        patch = self.patch()
        index = self.prepare(patch)
        self.assertEqual(index["entries"][0]["comparisons"], ["introduced", "heads"])
        self.assertEqual(index["summary"]["duplicate_diff_bytes"], len(patch))
        self.assertEqual(index["comparisons"]["heads"]["alias_of"], "introduced")
        extra = self.patch("OnlyHeads.cs")
        index = self.prepare(patch, patch + extra, heads_stat=b"1\t1\tExample.cs\0" + b"1\t1\tOnlyHeads.cs\0")
        self.assertEqual(len(index["entries"]), 2)
        self.assertEqual(index["entries"][0]["comparisons"], ["introduced", "heads"])
        self.assertEqual(index["entries"][1]["comparisons"], ["heads"])
        self.assertIsNone(index["comparisons"]["heads"]["alias_of"])

    def test_same_file_with_different_changes_is_not_merged(self):
        index = self.prepare(self.patch(), self.patch(content="-other\n+new\n"))
        self.assertEqual(len(index["entries"]), 2)
        self.assertEqual(index["summary"]["duplicate_diff_bytes"], 0)

    def test_legacy_all_file_indexes_remain_readable(self):
        names = ["中文 空格.prefab", "Animation.anim", "Font.asset", "删除.cs", "new.unknown", "model.FBX", "only-mode.meta"]
        data = b"".join(self.patch(name) for name in names)
        stats = b"".join(("1\t1\t" + name + "\0").encode("utf-8") for name in names)
        index = self.prepare(data, introduced_stat=stats, review_scope="legacy-all-files")
        self.assertEqual({entry["path"] for entry in index["entries"]}, set(names))
        self.assertEqual(index["summary"]["blocks_by_category"]["unity-resource"], 4)
        page = index_page(self.run, limit=2)
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(index_page(self.run, "other")["entries"][0]["path"], "new.unknown")
        self.assertEqual(index_page(self.run, path_contains="中文")["entries"][0]["path"], names[0])
        records = numstat_records(b"-\t-\tname\twith-tab.FBX\0")
        self.assertIsNone(records[0]["added"])
        self.assertEqual(records[0]["path"], "name\twith-tab.FBX")

    def test_zero_diff_index_is_empty_not_a_review_result(self):
        self.prepare(b"")
        page = index_page(self.run)
        self.assertEqual(page["entries"], [])
        self.assertIsNone(page["next_offset"])
        self.assertNotIn("review_complete", page)

    def test_long_unicode_lines_and_line_limits_resume_without_loss(self):
        data = ("第一行\n" + "中文abc" * 1000 + "\n最后一行\n").encode("utf-8")
        path = self.run / "text"
        path.write_bytes(data)
        offset, pieces, count = 0, [], 0
        while True:
            result = read_window(path, 0, len(data), offset, 127, 1)
            self.assertLessEqual(result["source_bytes"], 127)
            self.assertLessEqual(result["content"].count("\n"), 1)
            self.assertEqual(result["first_line"], data[:offset].count(b"\n") + 1)
            pieces.append(result["content"])
            count += 1
            if result["next_offset"] is None:
                break
            self.assertGreater(result["next_offset"], offset)
            offset = result["next_offset"]
        self.assertGreater(count, 3)
        self.assertEqual("".join(pieces).encode("utf-8"), data)

    def test_reads_only_selected_diff_and_rejects_tampering(self):
        first, second = self.patch(), self.patch("Other.cs")
        self.prepare(first + second, introduced_stat=b"1\t1\tExample.cs\0" + b"1\t1\tOther.cs\0")
        result, _ = read_evidence(self.run, entry_id="D000002")
        self.assertEqual(result["content"].encode(), second)
        self.assertEqual(result["comparisons"], ["introduced", "heads"])
        (self.run / "introduced.diff").write_bytes(b"changed")
        with self.assertRaises(ReviewError):
            read_evidence(self.run, entry_id="D000001")
        with (self.run / "input-index.json").open("a") as stream:
            stream.write(" ")
        with self.assertRaises(ReviewError):
            index_page(self.run)

    def test_binary_and_invalid_bounds_do_not_silently_complete(self):
        path = self.run / "binary"
        path.write_bytes(b"PK\x03\x04more")
        with self.assertRaises(ReviewError):
            read_window(path, 0, path.stat().st_size, 0, 100, 10)
        path.write_bytes(b"line\n")
        for offset, size, lines in ((-1, 10, 10), (6, 10, 10), (0, 32001, 10), (0, 10, 401)):
            with self.assertRaises(ReviewError):
                read_window(path, 0, 5, offset, size, lines)
        with self.assertRaises(ReviewError):
            self.prepare(self.patch(), introduced_stat=b"")

    def test_usage_counts_repeated_ranges_and_never_fabricates_model_tokens(self):
        self.prepare(self.patch())
        result, details = read_evidence(self.run, entry_id="D000001", max_bytes=24)
        output = record_output(self.run, "read", result, details)
        record_output(self.run, "read", result, details)
        summary = usage_summary(self.run)
        self.assertIsNone(summary["model_usage"])
        measured = summary["tool_outputs"]
        self.assertEqual(measured["utf8_bytes"], len((output + "\n").encode()) * 2)
        self.assertEqual(measured["read_source_bytes"], 48)
        self.assertEqual(measured["unique_read_source_bytes"], 24)
        self.assertEqual(measured["repeated_read_source_bytes"], 24)
        record = {"id": "call-1", "source": "fixture runtime", "input_tokens": 100, "output_tokens": 10}
        path = self.run / "actual.json"
        save_json(path, record)
        usage_summary(self.run, path)
        self.assertEqual(usage_summary(self.run, path)["model_usage"], [record])
        record["input_tokens"] = 101
        save_json(path, record)
        with self.assertRaises(ReviewError):
            usage_summary(self.run, path)
        events = (self.run / "input-usage.jsonl").read_text(encoding="utf-8")
        self.assertNotIn('"content"', events)

    def test_document_paths_cannot_escape_or_read_unfrozen_files(self):
        self.prepare(b"")
        (self.run / "documents").mkdir()
        document = self.run / "documents/spec.md"
        document.write_bytes(b"current requirement\n")
        context = load_json(self.run / "context.json")
        context["documents"] = [{"file": "documents/spec.md", "sha256": digest_file(document)}]
        save_json(self.run / "context.json", context)
        result, _ = read_evidence(self.run, source="documents", path="spec.md")
        self.assertEqual(result["content"], "current requirement\n")
        for name in ("../context.json", "C:/outside", "missing.md"):
            with self.assertRaises(ReviewError):
                read_evidence(self.run, source="documents", path=name)

    def test_csharp_methods_can_be_read_by_line_without_dumping_file(self):
        resource = self.patch("Panel.cs", content="+//" + "padding" * 10000 + "\n+void OnClick()\n+{ SendRequest(); }\n")
        self.prepare(resource, introduced_stat=b"3\t0\tPanel.cs\0")
        result, _ = read_evidence(self.run, entry_id="D000001", line_number=4)
        self.assertEqual(result["first_line"], 4)
        self.assertIn("SendRequest", result["content"])
        self.assertIn("OnClick", result["content"])
        self.assertNotIn("padding", result["content"])
        with self.assertRaises(ReviewError):
            read_evidence(self.run, entry_id="D000001", line_number=100)

    def test_csharp_index_rejects_non_csharp_metadata(self):
        with self.assertRaises(ReviewError):
            self.prepare(self.patch("Panel.prefab"), introduced_stat=b"1\t0\tPanel.prefab\0")


if __name__ == "__main__":
    unittest.main()
