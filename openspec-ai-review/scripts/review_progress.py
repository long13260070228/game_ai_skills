"""Persistent review coverage and conservative, dependency-aware incremental reuse."""
import argparse
import copy
from pathlib import Path
import re
import sys

from common import (ReviewError, command, contained, digest_file, fingerprint, load_json,
                    lock, relative_path, require, save_json)
from review_input import encode_result, record_output

VERSION = 1
RULE_FILES = ("SKILL.md", "references/review-contract.md", "references/input-budget.md",
              "references/incremental-review.md", "scripts/review.py", "scripts/review_input.py",
              "scripts/review_progress.py", "scripts/document_cache.py", "scripts/common.py")
LIST_FIELDS = ("requirements", "findings", "checks", "limitations", "document_gaps", "document_conflicts")


def rules_digest():
    root = Path(__file__).resolve().parent.parent
    return fingerprint({name: digest_file(root / name) for name in RULE_FILES})


def verify_run(run):
    context = load_json(run / "context.json")
    require(context.get("progress_version") == VERSION, "Run predates progress tracking; collect fresh evidence")
    require(context["rules_sha256"] == rules_digest(), "Review rules changed; collect a new run")
    for name, expected in context["artifacts"].items():
        require(digest_file(contained(run, name)) == expected, "Frozen artifact changed: " + name)
    for document in context["documents"]:
        require(digest_file(contained(run, document["file"])) == document["sha256"], "Frozen document changed")
    prefix = [context["git_executable"], "-c", "core.fsmonitor=false", "-C", str(run / "snapshot")]
    require(command(prefix + ["rev-parse", "HEAD"]).decode().strip() == context["target_sha"], "Snapshot HEAD changed")
    command(prefix + ["diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--", context["diff_pathspec"]])
    return context


def matches(path, roots):
    return any(root == "*" or path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def validate_plan(plan, context, index):
    require(plan.get("requirements_complete") is True, "Establish the current effective requirement inventory before starting coverage")
    require(isinstance(plan.get("review_profile"), str) and plan["review_profile"].strip(), "Record review profile/model/extra criteria")
    require(isinstance(plan.get("requirements_basis"), str) and plan["requirements_basis"].strip(), "Record how effective requirements and removals were reconciled")
    modules = plan.get("modules")
    require(isinstance(modules, list) and modules, "Plan must include at least one module")
    ids = set()
    for module in modules:
        identifier = module.get("id")
        require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-]+", identifier), "Module ids must be simple identifiers")
        require(identifier not in ids, "Duplicate module id")
        ids.add(identifier)
        require(isinstance(module.get("paths"), list) and module["paths"], "Module needs C# file paths/directory roots")
        for root in module["paths"]:
            if root != "*":
                relative_path(root)
                require(not any(char in root for char in "*?[]"), "Use literal file/directory roots, or * for all C#")
        require(type(module.get("dependencies_complete")) is bool, "Explicitly assess dependency completeness")
        require(isinstance(module.get("depends_on"), list), "Declare module dependencies")
    for module in modules:
        require(set(module["depends_on"]) <= ids, "Unknown dependency module")
    requirements = plan.get("requirements")
    require(isinstance(requirements, list), "Plan needs a requirement list, even when empty")
    req_ids = set()
    documents = {item["file"] for item in context["documents"]}
    for item in requirements:
        identifier = item.get("id")
        require(isinstance(identifier, str) and identifier.strip() and identifier not in req_ids, "Invalid/duplicate requirement id")
        req_ids.add(identifier)
        require(item.get("module") in ids, "Requirement needs an owning module")
        require(isinstance(item.get("description"), str) and item["description"].strip(), "Requirement description is required")
        require(isinstance(item.get("sources"), list) and item["sources"], "Requirement needs frozen document anchors")
        for source in item["sources"]:
            require(source.get("file") in documents and isinstance(source.get("anchor"), str) and source["anchor"].strip(),
                    "Requirement source must identify a frozen document and original/parsed location")
    missing = [entry["path"] for entry in index["entries"] if not any(matches(entry["path"], module["paths"]) for module in modules)]
    require(not missing, "Plan must cover every C# diff path, including deletions: " + ", ".join(missing[:10]))


def documents_key(context):
    return fingerprint({"documents": [{key: item[key] for key in ("id", "kind", "file", "sha256")} for item in context["documents"]],
                        "gaps": context["document_gaps"]})


def closure(modules, identifier):
    by_id = {module["id"]: module for module in modules}
    found, pending = set(), [identifier]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(by_id[current]["depends_on"])
    return found


def module_keys(plan, inventory, index):
    result = {}
    for module in plan["modules"]:
        related = closure(plan["modules"], module["id"])
        roots = [root for item in plan["modules"] if item["id"] in related for root in item["paths"]]
        result[module["id"]] = fingerprint({
            "code": {path: value for path, value in inventory.items() if matches(path, roots)},
            "diff": [{key: entry[key] for key in ("path", "sha256", "comparisons")}
                     for entry in index["entries"] if matches(entry["path"], roots)]})
    return result


def assemble_state(state):
    require(state.get("schema_version") == VERSION, "Unsupported progress schema")
    records = state["modules"]
    require(all(record["status"] == "complete" and not record["pending"] for record in records.values()),
            "Review coverage is incomplete; finish pending modules before sealing")
    result = {"summary": "\n".join(record["review"]["summary"] for record in records.values())}
    for key in LIST_FIELDS:
        result[key] = [item for record in records.values() for item in record["review"][key]]
    return result


def baseline(run):
    context = load_json(run / "context.json")
    manifest = load_json(run / "report-manifest.json")
    require(context.get("progress_version") == VERSION, "Baseline lacks audited progress")
    for name, key in (("context.json", "context_sha256"), ("review.final.json", "review_sha256"),
                      ("progress.final.json", "progress_sha256")):
        require(digest_file(run / name) == manifest.get(key), "Baseline seal does not match " + name)
    state = load_json(run / "progress.final.json")
    require(state["context_sha256"] == manifest["context_sha256"], "Baseline progress belongs to another context")
    require(fingerprint(state["plan"]) == state["plan_sha256"], "Baseline plan changed")
    require(fingerprint(assemble_state(state)) == fingerprint(load_json(run / "review.final.json")), "Baseline progress and review differ")
    inventory_path = run / "code-inventory.json"
    require(digest_file(inventory_path) == context["artifacts"]["code-inventory.json"], "Baseline code inventory changed")
    return context, state, load_json(inventory_path)


def choose_previous(run, context, explicit=None):
    if explicit:
        candidate = Path(explicit).resolve()
        require(candidate != run and candidate.parent == run.parent, "Baseline must be another run in the same review cache")
        data = baseline(candidate)
        require(data[0]["scope_key"] == context["scope_key"], "Baseline belongs to another repository/version mapping")
        return candidate, data
    for candidate in sorted(run.parent.iterdir(), key=lambda path: path.name, reverse=True):
        if candidate == run or not candidate.is_dir() or candidate.is_symlink() or not (candidate / "progress.final.json").exists():
            continue
        try:
            data = baseline(candidate)
            if data[0]["scope_key"] == context["scope_key"]:
                return candidate, data
        except (ReviewError, OSError, ValueError, KeyError, TypeError):
            continue
    return None, None


def load_progress(run, context):
    state = load_json(run / "progress.json")
    require(state["context_sha256"] == digest_file(run / "context.json"), "Progress belongs to changed evidence")
    require(fingerprint(state["plan"]) == state["plan_sha256"], "Progress plan changed; collect a new run to replan")
    require(state["rules_sha256"] == context["rules_sha256"], "Progress rules changed")
    return state


def start(run, plan=None, mode="incremental", previous=None):
    require(mode in ("full", "incremental"), "Invalid review mode")
    with lock(run / ".review.lock"):
        context = verify_run(run)
        require(not (run / "report-manifest.json").exists(), "Run already sealed; publish/resume publication or collect new evidence")
        if (run / "progress.json").exists():
            state = load_progress(run, context)
            require(plan is None or fingerprint(plan) == state["plan_sha256"], "Cannot replace a started plan; collect a new run")
            return state
        candidate, old = choose_previous(run, context, previous) if mode == "incremental" else (None, None)
        if plan is None:
            require(old is not None and documents_key(old[0]) == documents_key(context),
                    "Provide --plan with the current effective requirements; no matching document baseline")
            plan = copy.deepcopy(old[1]["plan"])
        index = load_json(run / "input-index.json")
        inventory = load_json(run / "code-inventory.json")
        validate_plan(plan, context, index)
        if old:
            current_ids = {module["id"] for module in plan["modules"]}
            require(not any(identifier not in current_ids and any(finding["resolution"] == "open" for finding in record["review"]["findings"])
                            for identifier, record in old[1]["modules"].items()),
                    "Retain modules with previous open findings until those findings are explicitly reconciled")
        keys = module_keys(plan, inventory, index)
        reasons, invalid = [], {}
        if old is None:
            reasons.append("full requested or no complete sealed baseline")
        else:
            old_context, old_state, old_inventory = old
            for key in ("base_sha", "merge_base_sha", "scope_key", "rules_sha256", "review_scope"):
                if old_context[key] != context[key]:
                    reasons.append(key + " changed")
            if documents_key(old_context) != documents_key(context):
                reasons.append("documents or document gaps changed")
            if old_state["plan_sha256"] != fingerprint(plan):
                reasons.append("effective requirements/module/dependency plan changed")
            changed = {path for path in inventory.keys() | old_inventory.keys() if inventory.get(path) != old_inventory.get(path)}
            if changed and not all(module["dependencies_complete"] for module in plan["modules"]):
                reasons.append("C# changed with incomplete dependency knowledge")
            if any(not any(matches(path, module["paths"]) for module in plan["modules"]) for path in changed):
                reasons.append("C# changes outside known module ownership")
            if not reasons:
                for module in plan["modules"]:
                    identifier = module["id"]
                    record = old_state["modules"][identifier]
                    why = []
                    if keys[identifier] != record["input_sha256"]:
                        why.append("module/dependency C# or diff changed")
                    if any(finding["resolution"] == "open" for finding in record["review"]["findings"]):
                        why.append("unresolved findings require fresh verification")
                    if record.get("evidence_kind") != "static" or any(req["verification"] == "已验证" or req["status"] == "无法确认" for req in record["review"]["requirements"]):
                        why.append("runtime or unresolved requirement evidence cannot be reused")
                    if why:
                        invalid[identifier] = why
                # Propagate even non-code invalidation through declared dependencies.
                for module in plan["modules"]:
                    if closure(plan["modules"], module["id"]) & invalid.keys():
                        invalid.setdefault(module["id"], ["dependency needs fresh review"])
        records = {}
        for module in plan["modules"]:
            identifier = module["id"]
            old_record = old[1]["modules"].get(identifier) if old else None
            if old_record and not reasons and identifier not in invalid:
                records[identifier] = {**copy.deepcopy(old_record), "reused_from": candidate.name,
                                       "input_sha256": keys[identifier], "reasons": []}
            else:
                records[identifier] = {"status": "pending", "pending": ["review module"], "notes": "",
                                       "reasons": reasons or invalid.get(identifier, ["new module"]),
                                       "input_sha256": keys[identifier], "reused_from": None,
                                       "previous_review": copy.deepcopy(old_record["review"]) if old_record else None}
        state = {"schema_version": VERSION, "context_sha256": digest_file(run / "context.json"),
                 "rules_sha256": context["rules_sha256"], "plan": plan, "plan_sha256": fingerprint(plan),
                 "requested_mode": mode, "baseline": candidate.name if candidate else None,
                 "fallback_reasons": reasons, "modules": records}
        save_json(run / "progress.json", state)
        return state


def checkpoint(run, submission):
    from review import validate_review
    with lock(run / ".review.lock"):
        context = verify_run(run)
        require(not (run / "report-manifest.json").exists(), "Cannot modify sealed progress")
        state = load_progress(run, context)
        identifier = submission.get("module")
        require(identifier in state["modules"], "Unknown module")
        require(submission.get("status") in ("in_progress", "complete"), "Invalid module status")
        require(isinstance(submission.get("notes"), str) and submission["notes"].strip(), "Record evidence/coverage notes")
        require(isinstance(submission.get("pending"), list) and all(isinstance(item, str) and item.strip() for item in submission["pending"]), "Record pending work")
        record = state["modules"][identifier]
        expected = {req["id"] for req in state["plan"]["requirements"] if req["module"] == identifier}
        if submission["status"] == "in_progress" and "review" in submission:
            validate_review(submission["review"], context, run)
            require({req["id"] for req in submission["review"]["requirements"]} <= expected, "Draft has requirements belonging to another module")
            record["draft_review"] = copy.deepcopy(submission["review"])
        if submission["status"] == "complete":
            require(not submission["pending"], "Complete module cannot have pending work")
            require(submission.get("evidence_kind") in ("static", "runtime"), "Classify evidence for safe reuse")
            review = submission["review"]
            validate_review(review, context, run)
            require({req["id"] for req in review["requirements"]} == expected, "Module review must cover exactly its effective requirements")
            roots = [root for module in state["plan"]["modules"] if module["id"] in closure(state["plan"]["modules"], identifier) for root in module["paths"]]
            require(all(matches(finding["path"], roots) for finding in review["findings"]), "Finding outside module/dependency code scope")
            previous_review = record.get("previous_review") or {}
            reconciled = submission.get("rechecked_findings", {})
            for finding in previous_review.get("findings", []):
                if finding["resolution"] == "open":
                    item = reconciled.get(finding["id"], {})
                    require(item.get("resolution") in ("open", "resolved", "removed", "cancelled", "superseded") and
                            isinstance(item.get("evidence"), str) and item["evidence"].strip(), "Reconcile every previous open finding with current evidence")
                    if item["resolution"] == "open":
                        require(any(new["id"] == finding["id"] and new["resolution"] == "open" for new in review["findings"]), "Still-open finding missing from current review")
            record.update({"review": copy.deepcopy(review), "evidence_kind": submission["evidence_kind"],
                           "rechecked_findings": reconciled, "reviewed_target_sha": context["target_sha"]})
            record.pop("draft_review", None)
        record.update({"status": submission["status"], "notes": submission["notes"],
                       "pending": submission["pending"], "reused_from": None})
        save_json(run / "progress.json", state)
        return state


def assemble(run):
    from review import validate_review
    with lock(run / ".review.lock"):
        context = verify_run(run)
        require(not (run / "report-manifest.json").exists(), "Run already sealed")
        state = load_progress(run, context)
        result = assemble_state(state)
        validate_review(result, context, run)
        save_json(run / "review.json", result)
        return result


def validate_for_seal(run, context, review):
    if context.get("progress_version") != VERSION:
        return None
    verify_run(run)
    require((run / "progress.json").is_file(), "Initialize and complete review progress before sealing")
    state = load_progress(run, context)
    require(fingerprint(assemble_state(state)) == fingerprint(review), "Review must match completed module checkpoints; run assemble")
    return state


def status(state, offset=0, limit=40, module=None):
    require(offset >= 0 and 1 <= limit <= 100, "Invalid progress page bounds")
    if module:
        require(module in state["modules"], "Unknown module")
        return {"module": module, **state["modules"][module]}
    items = list(state["modules"].items())
    return {"baseline": state["baseline"], "fallback_reasons": state["fallback_reasons"],
            "total": len(items), "complete": sum(item["status"] == "complete" for _, item in items),
            "reused": sum(bool(item.get("reused_from")) for _, item in items),
            "modules": [{"id": key, **{field: value[field] for field in ("status", "pending", "reasons", "reused_from")}}
                        for key, value in items[offset:offset + limit]],
            "next_offset": offset + limit if offset + limit < len(items) else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    starting = commands.add_parser("start")
    starting.add_argument("--plan")
    starting.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    starting.add_argument("--previous")
    saving = commands.add_parser("checkpoint")
    saving.add_argument("--file", required=True)
    viewing = commands.add_parser("status")
    viewing.add_argument("--offset", type=int, default=0)
    viewing.add_argument("--limit", type=int, default=40)
    viewing.add_argument("--module")
    assembling = commands.add_parser("assemble")
    for subparser in (starting, saving, viewing, assembling):
        subparser.add_argument("--run", required=True)
    args = parser.parse_args()
    try:
        run = Path(args.run).resolve()
        if args.action == "start":
            result = status(start(run, load_json(args.plan) if args.plan else None, args.mode, args.previous))
        elif args.action == "checkpoint":
            result = status(checkpoint(run, load_json(args.file)))
        elif args.action == "assemble":
            result = {"file": str(run / "review.json"), "findings": len(assemble(run)["findings"])}
        else:
            result = status(load_progress(run, verify_run(run)), args.offset, args.limit, args.module)
        print(record_output(run, "progress-" + args.action, result))
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        print("Progress stopped: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
