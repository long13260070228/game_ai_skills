import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from common import ReviewError, absolute_path, command, command_to_file, contained, digest, digest_file, load_config, load_json, lock, relative_path, report_filename, require, save_json, scope_key, version_for
from review_input import build_index
from review_progress import rules_digest, validate_for_seal


PRIORITIES = {"P1": "阻断", "P2": "严重", "P3": "一般", "P4": "建议"}
STATUSES = ("已实现", "部分实现", "未实现", "无法确认", "不适用")
VERIFICATIONS = ("已验证", "静态检查", "未验证", "不适用")
EVIDENCE = ("已复现", "静态证据充分", "待验证")
ORIGINS = ("本次引入", "改动暴露", "历史遗留")
CSHARP_PATHSPEC = ":(top,glob,icase)**/*.cs"


def collect(config_path, target, base):
    config = load_config(config_path)
    version = version_for(config, target, base)
    git_config = config["git"]
    cache = absolute_path(git_config["review_cache"])
    require(not Path.cwd().resolve().is_relative_to(cache), "review_cache cannot be the working project or its ancestor")
    executable = git_config.get("executable", "git")
    if git_config.get("local_path"):
        local_path = absolute_path(git_config["local_path"])
        require(local_path.is_dir(), "Configured local Git project does not exist")
        require(not local_path.is_relative_to(cache) and not cache.is_relative_to(local_path), "review_cache must be outside the configured local Git project")
        actual_root = command([executable, "-C", str(local_path), "rev-parse", "--show-toplevel"]).decode("utf-8").strip()
        require(Path(actual_root).resolve() == local_path, "Configure the local Git project root")
        origin = command([executable, "-C", str(local_path), "remote", "get-url", "origin"]).decode("utf-8").strip()
        require(origin == git_config["url"], "Local Git origin does not match the configured repository URL")
    for branch in (target, base):
        require(isinstance(branch, str) and branch and not branch.startswith("-"), "Invalid branch")
        command([executable, "check-ref-format", "refs/heads/" + branch])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
    run = cache / run_id
    run.mkdir(parents=True, exist_ok=False)
    repository = run / "repository.git"
    environment = os.environ.copy()
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never", "GIT_LFS_SKIP_SMUDGE": "1"})
    for key in list(environment):
        if key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR") or key.startswith("GIT_CONFIG_"):
            environment.pop(key)
    command([executable, "init", "--bare", str(repository)], env=environment)
    prefix = [executable, "-c", "core.hooksPath=" + str(run / "disabled-hooks"), "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false"]
    if git_config.get("username"):
        prefix += ["-c", "credential.username=" + git_config["username"]]

    def git(*arguments):
        return command(prefix + ["--git-dir=" + str(repository), *arguments], env=environment, timeout=900)

    with lock(run / ".review.lock"):
        git("fetch", "--atomic", "--no-tags", "--no-recurse-submodules", "--", git_config["url"], "+refs/heads/" + target + ":refs/review/target", "+refs/heads/" + base + ":refs/review/base")
        target_sha = git("rev-parse", "refs/review/target^{commit}").decode().strip()
        base_sha = git("rev-parse", "refs/review/base^{commit}").decode().strip()
        ancestors = git("merge-base", "--all", target_sha, base_sha).decode().split()
        require(len(ancestors) == 1, "No unique merge-base; resolve ancestry before reviewing")
        git("worktree", "add", "--detach", str(run / "snapshot"), target_sha)
        diff_options = ("--no-ext-diff", "--no-textconv", "--no-renames", "--no-color", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/")
        comparisons = {}
        for name, start in (("introduced", ancestors[0]), ("heads", base_sha)):
            if name == "heads" and base_sha == ancestors[0]:
                # Preserve the raw artifact names and old render/publish contracts.
                shutil.copyfile(run / "introduced.diff", run / "heads.diff")
                comparisons[name] = comparisons["introduced"]
            else:
                command_to_file(prefix + ["--git-dir=" + str(repository), "diff", *diff_options, start, target_sha, "--", CSHARP_PATHSPEC], run / (name + ".diff"), env=environment)
                comparisons[name] = git("diff", *diff_options, "--numstat", "-z", start, target_sha, "--", CSHARP_PATHSPEC)
        (run / "changes.txt").write_bytes(git("diff", "--no-renames", "--name-status", ancestors[0], target_sha, "--", CSHARP_PATHSPEC))
        tracked = {}
        for record in git("ls-tree", "-r", "-z", target_sha).split(b"\0"):
            if record:
                metadata, filename = record.split(b"\t", 1)
                mode, object_type, object_sha = metadata.decode().split()
                tracked[filename.decode("utf-8")] = (mode, object_type, object_sha)
        documents = []
        gaps = []
        specs = list(version.get("documents", []))
        changes = version.get("openspec_changes", [])
        if not changes:
            gaps.append("No OpenSpec changes configured for this version")
        for index, change in enumerate(changes):
            specs.append({"id": "openspec-" + str(index + 1), "kind": "openspec", "source": "target", "path": change})
        identifiers = set()
        for document in specs:
            identifier = document["id"]
            require(re.fullmatch(r"[A-Za-z0-9_-]+", identifier) and identifier not in identifiers, "Document ids must be unique simple identifiers")
            identifiers.add(identifier)
            require(document["kind"] in ("requirements", "api", "design", "openspec"), "Unknown document kind")
            if document["source"] == "target":
                path = relative_path(document["path"]).as_posix()
                matches = [name for name in tracked if name == path or name.startswith(path + "/")]
                if not matches:
                    gaps.append(identifier + ": target document missing: " + path)
                for name in matches:
                    mode, object_type, object_sha = tracked[name]
                    if object_type != "blob" or mode == "120000":
                        gaps.append(identifier + ": linked document is not frozen: " + name)
                        continue
                    data = git("cat-file", "blob", object_sha)
                    destination = contained(run / "documents" / identifier, name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    documents.append({"id": identifier, "kind": document["kind"], "source": "target", "original": name, "file": destination.relative_to(run).as_posix(), "sha256": digest(data)})
            elif document["source"] == "local":
                source = absolute_path(document["path"])
                if not source.is_file():
                    gaps.append(identifier + ": local document unavailable")
                    continue
                data = source.read_bytes()
                destination = run / "documents" / identifier / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                documents.append({"id": identifier, "kind": document["kind"], "source": "local", "original": source.name, "file": destination.relative_to(run).as_posix(), "sha256": digest(data)})
            else:
                raise ReviewError("Document source must be target or local")
        for kind in ("requirements", "api", "design"):
            if not any(document["kind"] == kind for document in documents):
                gaps.append("No frozen readable source configured for document kind: " + kind)
        build_index(run, comparisons)
        save_json(run / "code-inventory.json", {name: {"mode": mode, "type": kind, "object": sha}
                                               for name, (mode, kind, sha) in tracked.items()
                                               if Path(name).suffix.lower() == ".cs"})
        context = {
            "schema_version": 1, "run_id": run_id, "project": config["project"], "version": version["version"], "git_executable": executable,
            "review_scope": "csharp-only", "diff_pathspec": CSHARP_PATHSPEC,
            "progress_version": 1, "rules_sha256": rules_digest(),
            "target_branch": target, "base_branch": base, "target_sha": target_sha, "base_sha": base_sha,
            "merge_base_sha": ancestors[0], "collected_at": datetime.now(timezone.utc).isoformat(),
            "scope_key": scope_key(config, version), "documents": documents, "document_gaps": gaps,
            "limitations": ["Git LFS payloads and submodules are not fetched automatically; runtime/Unity validation requires separately recorded checks."],
            "artifacts": {name: digest_file(run / name) for name in ("introduced.diff", "heads.diff", "changes.txt", "input-index.json", "code-inventory.json")}
        }
        save_json(run / "context.json", context)
    return run


def nonempty_fields(item, names):
    for name in names:
        require(isinstance(item.get(name), str) and item[name].strip(), "Missing nonempty field: " + name)


def validate_review(review, context, run):
    nonempty_fields(review, ("summary",))
    require("不得保留此模板" not in review["summary"], "Replace the review template with actual facts")
    for key in ("requirements", "findings", "checks", "limitations", "document_gaps", "document_conflicts"):
        require(isinstance(review.get(key), list), "Missing list: " + key)
    for key in ("limitations", "document_gaps", "document_conflicts"):
        require(all(isinstance(item, str) and item.strip() for item in review[key]), "Invalid text list: " + key)
    require(review["checks"], "Record actual checks or explicit non-execution")
    requirement_ids = set()
    finding_ids = set()
    for requirement in review["requirements"]:
        nonempty_fields(requirement, ("id", "module", "description", "source", "evidence"))
        require(requirement["id"] not in requirement_ids, "Duplicate requirement id")
        requirement_ids.add(requirement["id"])
        require(requirement.get("status") in STATUSES and requirement.get("verification") in VERIFICATIONS, "Invalid requirement status/verification")
        require(isinstance(requirement.get("finding_ids"), list), "Missing finding_ids")
    for finding in review["findings"]:
        nonempty_fields(finding, ("id", "module", "title", "source", "path", "trigger", "expected", "actual", "impact", "fix", "regression"))
        require(finding["id"] not in finding_ids, "Duplicate finding id")
        finding_ids.add(finding["id"])
        require(finding.get("priority") in PRIORITIES and finding.get("evidence") in EVIDENCE and finding.get("origin") in ORIGINS, "Invalid priority/evidence/origin")
        require(finding.get("scope") in ("client", "backend-integration", "configuration", "visual-layout"), "Classify finding scope explicitly")
        require(finding.get("resolution") in ("open", "resolved", "removed", "cancelled", "superseded"), "Classify finding resolution explicitly")
        require(isinstance(finding.get("requirement_ids"), list), "Missing requirement_ids")
        require(set(finding["requirement_ids"]) <= requirement_ids, "Unknown requirement link")
        source = contained(run / "snapshot", finding["path"])
        if context.get("review_scope") == "csharp-only":
            require(source.suffix.lower() == ".cs", "C# review findings must reference a C# source file")
        require(source.is_file(), "Finding path does not exist in target snapshot")
        require(type(finding.get("line")) is int and 1 <= finding["line"] <= len(source.read_bytes().splitlines()), "Invalid target line number")
    for requirement in review["requirements"]:
        require(set(requirement["finding_ids"]) <= finding_ids, "Unknown finding link")
    for check in review["checks"]:
        nonempty_fields(check, ("name", "evidence"))
        require(check.get("result") in ("通过", "失败", "未执行", "不适用"), "Invalid check result")


def report_findings(review):
    return [item for item in review["findings"] if item.get("scope") == "client" and item.get("resolution") == "open" and item.get("evidence") in ("已复现", "静态证据充分")]


def html_report(review, context):
    def cell(value):
        if isinstance(value, list):
            value = "、".join(str(item) for item in value)
        return escape(str(value))

    def table(headers, rows):
        return "<div class='scroll'><table><thead><tr>" + "".join("<th>" + cell(header) + "</th>" for header in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + cell(value) + "</td>" for value in row) + "</tr>" for row in rows) + "</tbody></table></div>"

    findings = report_findings(review)
    counts = Counter(item["priority"] for item in findings)
    title = cell(context["project"]) + "-" + cell(context["version"])
    body = "<h1>" + title + "</h1><p>项目名称：" + cell(context["project"]) + " · " + cell(context["run_id"]) + "</p>"
    body += table(["等级", "问题数量"], [[key + ": " + label, counts[key]] for key, label in PRIORITIES.items()])
    body += "<h2>审核范围</h2>" + table(["项目", "值"], [[key, context[key]] for key in ("target_branch", "base_branch")])
    modules = sorted({item["module"] for item in findings})
    body += "<h2>问题清单</h2><label>等级 <select id='priority'><option value=''>全部</option>" + "".join("<option value='" + key + "'>" + key + ": " + label + "</option>" for key, label in PRIORITIES.items()) + "</select></label>"
    body += "<label>模块 <select id='module'><option value=''>全部</option>" + "".join("<option>" + cell(module) + "</option>" for module in modules) + "</select></label>"
    for item in findings:
        body += "<article class='finding' data-priority='" + item["priority"] + "' data-module='" + cell(item["module"]) + "'><h3>" + cell(item["id"] + " · " + item["priority"] + ": " + PRIORITIES[item["priority"]] + " · " + item["title"]) + "</h3>"
        body += "<p>" + cell(item["path"] + ":" + str(item["line"]) + " @ " + context["target_sha"]) + "</p>"
        body += table(["字段", "事实"], [[label, item[key]] for key, label in (("module", "模块"), ("trigger", "触发条件"), ("expected", "预期行为"), ("actual", "实际行为"), ("impact", "影响"))]) + "</article>"
    if not findings:
        body += "<p>本次记录的客户端问题数量：0。</p>"
    style = "body{font:16px/1.6 system-ui,sans-serif;max-width:1160px;margin:40px auto;padding:0 24px;color:#172336;background:#f6f8fc}h1,h2{color:#183f74}table{border-collapse:collapse;width:100%;margin:12px 0;background:white}th,td{text-align:left;vertical-align:top;border:1px solid #d9e1ee;padding:9px;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#eaf0fa}.scroll{overflow-x:auto}article{margin:18px 0;padding:16px;background:white;border:1px solid #d9e1ee;border-radius:8px}label{display:inline-block;margin:8px 16px 8px 0}select{padding:7px}article[hidden]{display:none}@media print{select,label{display:none}article[hidden]{display:block}body{margin:0;background:white}}"
    script = "const filters=['priority','module'];function apply(){document.querySelectorAll('.finding').forEach(row=>{row.hidden=filters.some(key=>{const value=document.getElementById(key).value;return value&&row.dataset[key]!==value;});});}document.querySelectorAll('select').forEach(control=>control.addEventListener('change',apply));"
    return "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + title + "</title><style>" + style + "</style></head><body>" + body + "<script>" + script + "</script></body></html>"


def render(run_path, review_path):
    run = Path(run_path).resolve()
    with lock(run / ".review.lock"):
        require(not (run / "report-manifest.json").exists(), "Report is sealed; create a new review run for revisions")
        context = load_json(run / "context.json")
        review = load_json(review_path)
        snapshot = run / "snapshot"
        git_executable = context["git_executable"]
        current_sha = command([git_executable, "-C", str(snapshot), "rev-parse", "HEAD"]).decode().strip()
        require(current_sha == context["target_sha"], "Snapshot HEAD changed after collection")
        command([git_executable, "-C", str(snapshot), "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--"]
                + ([CSHARP_PATHSPEC] if context.get("review_scope") == "csharp-only" else []))
        for document in context["documents"]:
            require(digest(contained(run, document["file"]).read_bytes()) == document["sha256"], "Frozen document was modified")
        for filename, expected in context["artifacts"].items():
            require(digest_file(contained(run, filename)) == expected, "Frozen diff artifact was modified")
        validate_review(review, context, run)
        progress = validate_for_seal(run, context, review)
        report = run / report_filename(context)
        require(not report.exists(), "HTML already exists; inspect interrupted rendering before retrying")
        save_json(run / "review.final.json", review)
        html = html_report(review, context)
        counts = {key: sum(item["priority"] == key for item in report_findings(review)) for key in PRIORITIES}
        manifest = {"schema_version": 2, "run_id": context["run_id"], "file": report.name, "html": html, "sha256": digest(html.encode("utf-8")), "context_sha256": digest((run / "context.json").read_bytes()), "review_sha256": digest((run / "review.final.json").read_bytes()), "counts": counts}
        if progress is not None:
            save_json(run / "progress.final.json", progress)
            manifest["progress_sha256"] = digest_file(run / "progress.final.json")
        save_json(run / "report-manifest.json", manifest)
    return run / "report-manifest.json"


def main():
    parser = argparse.ArgumentParser(description="Collect evidence or seal HTML in internal state; publish writes the report only to SVN")
    commands = parser.add_subparsers(dest="action", required=True)
    collect_parser = commands.add_parser("collect")
    for name in ("config", "target", "base"):
        collect_parser.add_argument("--" + name, required=True)
    render_parser = commands.add_parser("render")
    for name in ("run", "review"):
        render_parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        result = collect(args.config, args.target, args.base) if args.action == "collect" else render(args.run, args.review)
        print(str(result) if args.action == "collect" else "Review sealed. Run publish.py to write the HTML only to SVN and send it to Feishu.")
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        print("Review stopped: " + (str(error) if isinstance(error, ReviewError) else type(error).__name__ + "; check configuration/input files"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
