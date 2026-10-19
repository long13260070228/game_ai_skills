"""Bounded evidence access. Byte/character measurements are not model usage."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from common import ReviewError, command, contained, digest_file, load_json, lock, require, save_json


INDEX_NAME = "input-index.json"
DEFAULT_BYTES = 24000
MAX_BYTES = 32000
CATEGORIES = {
    "code": {".cs", ".lua", ".js", ".ts", ".cpp", ".c", ".h", ".shader", ".cginc", ".hlsl"},
    "unity-resource": {".prefab", ".asset", ".anim", ".controller", ".overridecontroller", ".mat", ".meta", ".unity", ".playable", ".mask"},
    "document": {".md", ".txt", ".docx", ".pdf", ".rst"},
    "data": {".json", ".xml", ".yaml", ".yml", ".csv", ".tsv", ".asmdef", ".asmref"},
    "binary": {".png", ".jpg", ".jpeg", ".fbx", ".ttf", ".otf", ".dll", ".so", ".aar", ".zip", ".mp3", ".wav"},
}


def category(path):
    suffix = Path(path).suffix.lower()
    return next((name for name, extensions in CATEGORIES.items() if suffix in extensions), "other")


def numstat_records(data):
    records = []
    for record in data.split(b"\0"):
        if not record:
            continue
        added, deleted, path = record.split(b"\t", 2)
        records.append({"path": path.decode("utf-8"),
                        "added": None if added == b"-" else int(added),
                        "deleted": None if deleted == b"-" else int(deleted)})
    return records


def patch_sections(path):
    """Stream section boundaries; never parse Git's quoted display filenames."""
    with path.open("rb") as stream:
        start = position = 0
        hasher = None
        for line in stream:
            if line.startswith(b"diff --git "):
                if hasher is not None:
                    yield start, position, hasher.hexdigest()
                start = position
                hasher = hashlib.sha256()
            require(hasher is not None, "Unexpected patch preamble")
            hasher.update(line)
            position += len(line)
        if hasher is not None:
            yield start, position, hasher.hexdigest()


def build_index(run, comparisons, review_scope="csharp-only"):
    """Exact whole-patch and file-block deduplication; raw evidence stays intact."""
    entries, by_hash, whole, dimensions = [], {}, {}, {}
    raw_bytes = 0
    for name, metadata in comparisons.items():
        filename = name + ".diff"
        path = run / filename
        stat = path.stat()
        sha = digest_file(path)
        raw_bytes += stat.st_size
        info = {"file": filename, "sha256": sha, "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "alias_of": whole.get(sha)}
        dimensions[name] = info
        records = numstat_records(metadata)
        if review_scope == "csharp-only":
            require(all(Path(record["path"]).suffix.lower() == ".cs" for record in records),
                    "C# input index cannot include non-C# differences")
        if sha in whole:
            original = whole[sha]
            for entry in entries:
                if original in entry["comparisons"]:
                    entry["comparisons"].append(name)
            continue
        whole[sha] = name
        count = 0
        for count, (start, end, block_sha) in enumerate(patch_sections(path), 1):
            require(count <= len(records), "Patch/numstat entry count mismatch")
            record = records[count - 1]
            key = (record["path"], block_sha)
            if key in by_hash:
                by_hash[key]["comparisons"].append(name)
                continue
            entry = {"id": "D" + str(len(entries) + 1).zfill(6), **record,
                     "category": category(record["path"]), "sha256": block_sha,
                     "comparisons": [name], "file": filename, "start": start,
                     "end": end, "bytes": end - start}
            entries.append(entry)
            by_hash[key] = entry
        require(count == len(records), "Patch/numstat entry count mismatch")
    unique_bytes = sum(entry["bytes"] for entry in entries)
    index = {"schema_version": 1, "review_scope": review_scope, "comparisons": dimensions, "entries": entries,
             "summary": {"raw_diff_bytes": raw_bytes, "unique_diff_bytes": unique_bytes,
                         "duplicate_diff_bytes": raw_bytes - unique_bytes,
                         "unique_blocks": len(entries),
                         "changed_paths": len({entry["path"] for entry in entries}),
                         "blocks_by_category": dict(Counter(entry["category"] for entry in entries))}}
    save_json(run / INDEX_NAME, index)
    return index


def open_index(run):
    context = load_json(run / "context.json")
    expected = context["artifacts"].get(INDEX_NAME)
    require(expected, "This run predates indexed input; use a new collection for indexed review")
    require(digest_file(run / INDEX_NAME) == expected, "Frozen input index was modified")
    index = load_json(run / INDEX_NAME)
    require(index["schema_version"] == 1, "Unsupported input index schema")
    return context, index


def index_page(run, selected_category=None, path_contains=None, offset=0, limit=40):
    require(type(offset) is int and offset >= 0 and 1 <= limit <= 100, "Invalid index page bounds")
    context, index = open_index(run)
    entries = [entry for entry in index["entries"]
               if (not selected_category or entry["category"] == selected_category)
               and (not path_contains or path_contains.casefold() in entry["path"].casefold())]
    page = []
    size = 0
    for entry in entries[offset:offset + limit]:
        item = {key: entry[key] for key in ("id", "path", "category", "added", "deleted", "bytes", "comparisons")}
        item_size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if page and size + item_size > MAX_BYTES:
            break
        page.append(item)
        size += item_size
    next_offset = offset + len(page)
    return {"summary": index["summary"], "comparisons": index["comparisons"],
            "documents": len(context["documents"]), "matched_blocks": len(entries),
            "entries": page, "next_offset": next_offset if next_offset < len(entries) else None,
            "review_scope": index.get("review_scope", "legacy-all-files"),
            "coverage_note": "New reviews compare C# only. Check requirements against target C# implementation even with zero diff; resource differences are excluded, not verified."}


def read_window(path, start, length, offset, max_bytes, max_lines):
    require(type(offset) is int and 0 <= offset <= length, "Offset outside evidence")
    require(4 <= max_bytes <= MAX_BYTES and 1 <= max_lines <= 400, "Read bounds exceed allowed limits")
    with path.open("rb") as stream:
        stream.seek(start)
        prefix = stream.read(min(4096, length))
        require(b"\0" not in prefix and not prefix.startswith((b"PK\x03\x04", b"%PDF")),
                "Binary/document container: parse with an appropriate tool; do not treat it as reviewed")
        # Count actual lines without loading the preceding source into memory.
        stream.seek(start)
        remaining, newlines, previous = offset, 0, b""
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            require(block, "Evidence shortened during read")
            remaining -= len(block)
            newlines += block.count(b"\n")
            previous = block[-1:]
        data = stream.read(min(max_bytes, length - offset))
    newline = -1
    for _ in range(max_lines):
        found = data.find(b"\n", newline + 1)
        if found < 0:
            break
        newline = found
    else:
        data = data[:newline + 1]
    # Retain complete UTF-8 codepoints; next_offset resumes every omitted byte.
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as error:
        if error.reason == "unexpected end of data" and offset + len(data) < length:
            data = data[:error.start]
            content = data.decode("utf-8")
        else:
            raise ReviewError("Evidence is not UTF-8 text or offset splits a character; use the returned cursor or an appropriate parser") from None
    require(b"\0" not in data, "Binary evidence requires an appropriate parser")
    require(data or offset == length, "Read made no progress")
    end = offset + len(data)
    return {"offset": offset, "end_offset": end, "next_offset": end if end < length else None,
            "complete": end == length, "first_line": newlines + 1,
            "starts_mid_line": bool(offset and previous != b"\n"),
            "ends_mid_line": bool(data and not data.endswith(b"\n") and end < length),
            "source_bytes": len(data), "content": content}


def line_offset(path, start, length, line_number):
    require(type(line_number) is int and line_number >= 1, "Line number must be positive")
    with path.open("rb") as stream:
        stream.seek(start)
        offset, line = 0, 1
        while offset < length and line < line_number:
            block = stream.readline(min(1024 * 1024, length - offset))
            require(block, "Evidence shortened during line lookup")
            offset += len(block)
            line += block.endswith(b"\n")
    require(line == line_number, "Line outside evidence")
    return offset


def read_evidence(run, entry_id=None, source=None, path=None, offset=0,
                  max_bytes=DEFAULT_BYTES, max_lines=200, line_number=None):
    context, index = open_index(run)
    if entry_id:
        require(not source and not path, "Use either a diff id or a source/path")
        entry = next((item for item in index["entries"] if item["id"] == entry_id), None)
        require(entry is not None, "Unknown diff id")
        if context.get("review_scope") == "csharp-only":
            require(Path(entry["path"]).suffix.lower() == ".cs", "Only C# differences are in scope")
        evidence = contained(run, entry["file"])
        stat = evidence.stat()
        recorded = index["comparisons"][entry["comparisons"][0]]
        require(stat.st_size == recorded["bytes"] and stat.st_mtime_ns == recorded["mtime_ns"],
                "Diff changed since indexing; collect fresh evidence")
        start, length = entry["start"], entry["bytes"]
        identity = "diff:" + entry["sha256"]
        label = {"id": entry_id, "path": entry["path"], "comparisons": entry["comparisons"],
                 "line_basis": "diff section; use @@ headers for source lines"}
    else:
        require(source in ("snapshot", "documents") and path, "Specify --id or --source and --path")
        evidence = contained(run / source, path)
        require(evidence.is_file() and not evidence.is_symlink(), "Evidence file missing or linked")
        if source == "documents":
            record = next((item for item in context["documents"] if item["file"] == "documents/" + path), None)
            require(record is not None, "Document is not frozen in this run")
            sha = digest_file(evidence)
            require(sha == record["sha256"], "Frozen document was modified")
        else:
            if context.get("review_scope") == "csharp-only":
                require(evidence.suffix.lower() == ".cs", "Only C# snapshot sources are in scope; read frozen requirements through documents")
            tracked = command([context["git_executable"], "-C", str(run / "snapshot"),
                               "ls-files", "--stage", "-z", "--", ":(literal)" + path])
            require(tracked and not tracked.startswith((b"120000 ", b"160000 ")),
                    "Source must be a tracked regular file")
            sha = digest_file(evidence)
        start, length = 0, evidence.stat().st_size
        identity = source + ":" + path + ":" + sha
        label = {"source": source, "path": path, "line_basis": "file"}
    if line_number is not None:
        require(offset == 0, "Use either --line or --offset")
        offset = line_offset(evidence, start, length, line_number)
    result = read_window(evidence, start, length, offset, max_bytes, max_lines)
    return {**label, **result}, {"resource": identity, "start": offset, "end": result["end_offset"]}


def encode_result(result):
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def record_output(run, action, result, details=None):
    output = encode_result(result)
    size = len((output + "\n").encode("utf-8"))
    event = {"action": action, "at": datetime.now(timezone.utc).isoformat(),
             "output_utf8_bytes": size, "output_characters": len(output) + 1,
             "estimated_tokens_utf8_div4": (size + 3) // 4, **(details or {})}
    with lock(run / ".input-usage.lock"):
        with (run / "input-usage.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encode_result(event) + "\n")
    return output


def usage_summary(run, model_usage_path=None):
    open_index(run)
    with lock(run / ".input-usage.lock"):
        model_path = run / "model-usage.json"
        records = load_json(model_path) if model_path.exists() else []
        if model_usage_path:
            record = load_json(model_usage_path)
            require(isinstance(record, dict), "Model usage must be an object")
            required = {"id", "source", "input_tokens", "output_tokens"}
            require(required <= record.keys() and record.keys() <= required | {"cached_input_tokens", "reasoning_tokens"},
                    "Unexpected model usage fields")
            require(all(isinstance(record[key], str) and record[key].strip() for key in ("id", "source")), "Usage id/source required")
            require(all(type(value) is int and value >= 0 for key, value in record.items() if key not in ("id", "source")), "Invalid usage counts")
            old = next((item for item in records if item["id"] == record["id"]), None)
            require(old is None or old == record, "Usage id already has different counts")
            if old is None:
                records.append(record)
                save_json(model_path, records)
        events_path = run / "input-usage.jsonl"
        events = []
        if events_path.exists():
            with events_path.open(encoding="utf-8") as stream:
                events = [json.loads(line) for line in stream if line.strip()]
    ranges, requested, unique = {}, 0, 0
    for event in events:
        if "resource" in event:
            ranges.setdefault(event["resource"], []).append((event["start"], event["end"]))
            requested += event["end"] - event["start"]
    for intervals in ranges.values():
        last = 0
        for start, end in sorted(intervals):
            unique += max(0, end - max(last, start))
            last = max(last, end)
    return {"tool_outputs": {"calls": len(events),
                             "utf8_bytes": sum(item["output_utf8_bytes"] for item in events),
                             "characters": sum(item["output_characters"] for item in events),
                             "estimated_tokens_utf8_div4": sum(item["estimated_tokens_utf8_div4"] for item in events),
                             "read_source_bytes": requested, "unique_read_source_bytes": unique,
                             "repeated_read_source_bytes": requested - unique},
            "model_usage": records or None,
            "measurement_note": "Only instrumented index/read/document/progress outputs are measured, not other tools, conversation or reasoning. Source-range deduplication covers index/read evidence only. UTF-8 bytes/4 is a rough estimate, not billed tokens. Model usage is externally supplied per non-overlapping call/batch; never infer it from file size."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    listing = commands.add_parser("index")
    listing.add_argument("--category", choices=[*CATEGORIES, "other"])
    listing.add_argument("--path-contains")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=40)
    reading = commands.add_parser("read")
    reading.add_argument("--id")
    reading.add_argument("--source", choices=["snapshot", "documents"])
    reading.add_argument("--path")
    reading.add_argument("--offset", type=int, default=0)
    reading.add_argument("--line", type=int)
    reading.add_argument("--max-bytes", type=int, default=DEFAULT_BYTES)
    reading.add_argument("--max-lines", type=int, default=200)
    usage = commands.add_parser("usage")
    usage.add_argument("--model-usage")
    for subparser in (listing, reading, usage):
        subparser.add_argument("--run", required=True)
    args = parser.parse_args()
    try:
        run = Path(args.run).resolve()
        if args.action == "index":
            result = index_page(run, args.category, args.path_contains, args.offset, args.limit)
            output = record_output(run, args.action, result)
        elif args.action == "read":
            result, details = read_evidence(run, args.id, args.source, args.path, args.offset, args.max_bytes, args.max_lines, args.line)
            output = record_output(run, args.action, result, details)
        else:
            output = encode_result(usage_summary(run, args.model_usage))
        print(output)
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        print("Input stopped: " + (str(error) if isinstance(error, ReviewError) else type(error).__name__ + "; inspect input/run"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
