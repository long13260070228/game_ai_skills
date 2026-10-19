"""Content-addressed text extraction. Extraction is not requirement interpretation."""
import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

from common import ReviewError, contained, digest_file, fingerprint, load_json, lock, require, save_json
from review_input import record_output

PARSER_VERSION = "text-docx-1"
EXTRACTION_RULES = "preserve-paragraphs-tables-deletions-warn-images-fields-1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract(path):
    suffix = path.suffix.lower()
    blocks, warnings = [], []
    if suffix in {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".csv", ".tsv", ".xml"}:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            return {"blocks": [], "warnings": ["Non-UTF-8 document needs manual extraction"], "status": "manual-required"}
        for number, line in enumerate(content.splitlines(), 1):
            blocks.append({"anchor": "line:" + str(number), "text": line})
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                parts = [name for name in archive.namelist() if name == "word/document.xml" or
                         name in ("word/footnotes.xml", "word/endnotes.xml") or
                         (name.startswith(("word/header", "word/footer")) and name.endswith(".xml"))]
                require("word/document.xml" in parts, "DOCX has no document body")
                for name in sorted(parts, key=lambda name: (name != "word/document.xml", name)):
                    require(archive.getinfo(name).file_size <= 64 * 1024 * 1024, "DOCX XML part too large for safe extraction")
                    root = ET.fromstring(archive.read(name))
                    parents = {child: parent for parent in root.iter() for child in parent}
                    # Paragraph order includes table cells; the anchor retains part and position.
                    for number, paragraph in enumerate(root.iter(W + "p"), 1):
                        fragments = []
                        for item in paragraph.iter():
                            if item.tag == W + "t":
                                fragments.append(item.text or "")
                            elif item.tag == W + "delText":
                                fragments.append("[deleted:" + (item.text or "") + "]")
                            elif item.tag in (W + "tab", W + "br", W + "cr"):
                                fragments.append("\t" if item.tag == W + "tab" else "\n")
                        location, current = [], paragraph
                        while current in parents:
                            parent = parents[current]
                            if current.tag in (W + "tbl", W + "tr", W + "tc"):
                                location.append(current.tag.removeprefix(W) + ":" + str(parent.findall(current.tag).index(current) + 1))
                            current = parent
                        blocks.append({"anchor": name + ":p:" + str(number), "text": "".join(fragments),
                                       "table_location": "/".join(reversed(location))})
                    tags = {item.tag for item in root.iter()}
                    if tags & {W + "drawing", W + "pict", W + "object", W + "altChunk"}:
                        warnings.append(name + ": embedded visual/object content requires manual interpretation")
                    if tags & {W + "del", W + "ins", W + "fldChar", W + "numPr"}:
                        warnings.append(name + ": revisions/fields/automatic numbering need source verification")
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            return {"blocks": [], "warnings": ["Invalid DOCX requires manual extraction"], "status": "manual-required"}
    else:
        return {"blocks": [], "warnings": ["Unsupported document type requires manual extraction"], "status": "manual-required"}
    return {"blocks": blocks, "warnings": warnings, "status": "text-extracted"}


def document(run, file):
    context = load_json(run / "context.json")
    record = next((item for item in context["documents"] if item["file"] == file), None)
    require(record is not None, "Document is not frozen in this run")
    source = contained(run, file)
    require(digest_file(source) == record["sha256"], "Frozen document was modified")
    key = fingerprint({"source": record["sha256"], "suffix": source.suffix.lower(),
                       "parser": PARSER_VERSION, "rules": EXTRACTION_RULES})
    directory = run.parent / ".document-cache"
    directory.mkdir(exist_ok=True)
    destination = directory / (key + ".json")
    with lock(directory / (key + ".lock")):
        if destination.exists():
            cached = load_json(destination)
            require(cached.get("key") == key and fingerprint(cached["payload"]) == cached["payload_sha256"],
                    "Parsed document cache corrupted; inspect/remove only this cache entry before retrying")
            return cached["payload"], key, True
        payload = {"source_sha256": record["sha256"], "parser_version": PARSER_VERSION,
                   "extraction_rules": EXTRACTION_RULES, **extract(source)}
        save_json(destination, {"key": key, "payload": payload, "payload_sha256": fingerprint(payload)})
        return payload, key, False


def page(run, file, offset=0, text_offset=0, limit=20, max_chars=6000):
    require(offset >= 0 and text_offset >= 0 and 1 <= limit <= 100 and 1 <= max_chars <= 8000, "Invalid document page bounds")
    payload, key, hit = document(run, file)
    blocks = payload["blocks"]
    require(offset <= len(blocks), "Block offset outside document")
    require(text_offset == 0 or (offset < len(blocks) and text_offset < len(blocks[offset]["text"])), "Text offset outside block")
    result, available, cursor, position = [], max_chars, offset, text_offset
    while cursor < len(blocks) and len(result) < limit and available:
        block = blocks[cursor]
        text = block["text"][position:position + available]
        result.append({"anchor": block["anchor"], "text_offset": position, "text": text,
                       **({"table_location": block["table_location"]} if block.get("table_location") else {})})
        available -= len(text)
        position += len(text)
        if position == len(block["text"]):
            cursor += 1
            position = 0
        else:
            break
    return {"file": file, "cache_key": key, "cache_hit": hit, "status": payload["status"],
            "warnings": payload["warnings"], "total_blocks": len(blocks), "blocks": result,
            "next": {"offset": cursor, "text_offset": position} if cursor < len(blocks) else None,
            "note": "Text extraction preserves anchors, not semantic requirement coverage. Resolve warnings against source before claiming coverage."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--file", required=True, help="Exact documents/... path from context.json")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--text-offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    try:
        run = Path(args.run).resolve()
        result = page(run, args.file, args.offset, args.text_offset, args.limit)
        print(record_output(run, "document", result))
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        print("Document stopped: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
