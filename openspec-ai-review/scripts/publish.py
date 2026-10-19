import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ElementTree

from common import ReviewError, absolute_path, command, contained, digest, load_config, load_json, lock, report_filename, require, safe_url, save_json, scope_key, version_for, version_name


class ApiRejected(ReviewError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class Feishu:
    def __init__(self, config):
        self.config = config
        self.token = None
        self.opener = build_opener(NoRedirect())
        require(bool(config.get("app_id")), "Feishu app_id is not configured")
        secret = os.environ.get(config["app_secret_env"])
        require(bool(secret), "Feishu app secret environment variable is missing")
        response = self.request("/auth/v3/tenant_access_token/internal", payload={"app_id": config["app_id"], "app_secret": secret})
        self.token = response["tenant_access_token"]
        chat = self.request("/im/v1/chats/" + quote(config["chat_id"], safe=""), method="GET")
        require(chat["data"]["name"] == config["chat_name"] == "客户端开发-U3D", "Feishu chat_id/name does not match the configured destination")

    def request(self, path, payload=None, method="POST", body=None, content_type="application/json; charset=utf-8"):
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request("https://open.feishu.cn/open-apis" + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=90) as response:
                result = json.loads(response.read())
        except Exception:
            raise ReviewError("Feishu network/HTTP/response failure; delivery may be uncertain, inspect saved state") from None
        require(isinstance(result, dict) and "code" in result, "Unrecognized Feishu response; delivery is uncertain")
        if result["code"] != 0:
            raise ApiRejected("Feishu rejected the request; check app permissions, credentials and organization policies")
        return result

    def upload(self, report):
        data = report.read_bytes()
        require(len(data) <= 30 * 1024 * 1024, "HTML exceeds the supported 30 MiB upload limit")
        boundary = "OpenSpecReview" + uuid.uuid4().hex
        fields = []
        for name, value in (("file_type", "stream"), ("file_name", report.name)):
            fields.append(("--" + boundary + '\r\nContent-Disposition: form-data; name="' + name + '"\r\n\r\n' + value + "\r\n").encode("utf-8"))
        fields.append(("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + report.name + '"\r\nContent-Type: text/html\r\n\r\n').encode("utf-8") + data + b"\r\n")
        fields.append(("--" + boundary + "--\r\n").encode("ascii"))
        result = self.request("/im/v1/files", body=b"".join(fields), content_type="multipart/form-data; boundary=" + boundary)
        return result["data"]["file_key"]

    def send(self, message_type, content, request_id):
        result = self.request("/im/v1/messages?receive_id_type=chat_id", payload={"receive_id": self.config["chat_id"], "msg_type": message_type, "content": json.dumps(content, ensure_ascii=False), "uuid": request_id})
        return result["data"]["message_id"]


class Svn:
    def __init__(self, config, version):
        require(config.get("auth") == "local-cache", "SVN must use local authentication cache")
        self.config = config
        self.root = absolute_path(config["working_copy"])
        if config.get("report_root"):
            self.report_root = absolute_path(config["report_root"])
            require(self.report_root.is_relative_to(self.root) and self.report_root != self.root, "SVN report_root must be inside the configured working copy")
            require(self.report_root.is_dir(), "Manually configured SVN report_root does not exist")
            self.directory = contained(self.report_root, version_name(version["version"]))
        else:
            self.report_root = None
            self.directory = contained(self.root, version["svn_version_dir"])
            require(self.directory.is_dir(), "Manually configured SVN version directory does not exist")
        safe_url(config["repository_url"])
        require("://" in config["repository_url"], "SVN repository_url must be a URL")
        self.url = self.path_url(self.directory)

    def path_url(self, path):
        return self.config["repository_url"].rstrip("/") + "/" + quote(path.relative_to(self.root).as_posix(), safe="/")

    def invoke(self, *arguments):
        authentication = ["--username", self.config["username"]] if self.config.get("username") else []
        local_targets = {}
        for index, argument in enumerate(arguments):
            if isinstance(argument, str) and argument.endswith("@") and "://" not in argument:
                target = Path(argument[:-1])
                if target.is_absolute() and target.resolve().is_relative_to(self.root):
                    local_targets[index] = target
        working_directory = None
        rewritten = list(arguments)
        if local_targets:
            working_directory = Path(os.path.commonpath([str(target) for target in local_targets.values()]))
            while not working_directory.is_dir():
                working_directory = working_directory.parent
            for index, target in local_targets.items():
                rewritten[index] = os.path.relpath(target, working_directory) + "@"
        return command([self.config.get("executable", "svn"), *rewritten, "--non-interactive", *authentication], cwd=working_directory, timeout=300)

    def info(self, target):
        return ElementTree.fromstring(self.invoke("info", "--xml", str(target) + "@")).find("entry")

    def preflight(self):
        root_info = self.info(self.root)
        require(root_info is not None and root_info.findtext("url").rstrip("/") == self.config["repository_url"].rstrip("/"), "SVN working copy URL mismatch")
        require(Path(root_info.findtext("wc-info/wcroot-abspath")).resolve() == self.root, "Configure the SVN working-copy root, not a nested directory")
        directory = self.report_root or self.directory
        self.check_versioned_directory(directory)
        status = ElementTree.fromstring(self.invoke("status", "--xml", str(self.root) + "@"))
        for entry in status.findall(".//wc-status"):
            require(entry.get("item") != "conflicted" and entry.get("props") != "conflicted" and entry.get("tree-conflicted") != "true", "SVN working copy has conflicts; resolve them without discarding unrelated work")
        self.invoke("update", "--depth", "empty", str(directory) + "@")
        self.check_versioned_directory(directory)

    def check_versioned_directory(self, directory):
        directory_info = self.info(directory)
        require(directory_info is not None and directory_info.findtext("url").rstrip("/") == self.path_url(directory), "SVN directory is unversioned or switched")
        require(Path(directory_info.findtext("wc-info/wcroot-abspath")).resolve() == self.root, "Nested working copy is not allowed")
        status = ElementTree.fromstring(self.invoke("status", "--xml", "--depth", "empty", str(directory) + "@"))
        for entry in status.findall(".//wc-status"):
            require(entry.get("item") in ("normal", "none") and entry.get("props") in ("normal", "none") and entry.get("switched") != "true" and entry.get("tree-conflicted") != "true", "SVN version directory has local changes, switch or conflicts")

    def prepare_directory(self, report, state, save):
        if self.report_root is None:
            return []
        relative = self.directory.relative_to(self.root).as_posix()
        owned = state.get("svn_owned_directory")
        require(owned is None or owned == relative, "Owned SVN directory does not match the target version")
        if self.directory.exists() and not owned:
            require(self.directory.is_dir(), "Target version path is a file, not a directory")
            self.check_versioned_directory(self.directory)
            return []
        if not owned:
            listing = ElementTree.fromstring(self.invoke("list", "--xml", self.path_url(self.report_root) + "@"))
            remote = [entry for entry in listing.findall(".//entry") if entry.findtext("name") == self.directory.name]
            if remote:
                require(len(remote) == 1 and remote[0].get("kind") == "dir", "Remote version path is not a directory")
                self.invoke("update", "--depth", "empty", str(self.directory) + "@")
                self.check_versioned_directory(self.directory)
                return []
            state["svn_owned_directory"] = relative
            save()
        if not self.directory.exists():
            self.directory.mkdir()
        require(self.directory.is_dir(), "Target version directory is unavailable")
        require(all(item.name == report.name and item.is_file() and not item.is_symlink() for item in self.directory.iterdir()), "New version directory contains files not owned by this publication")
        entries = ElementTree.fromstring(self.invoke("status", "--xml", "--depth", "empty", str(self.directory) + "@")).findall(".//wc-status")
        require(len(entries) == 1 and entries[0].get("item") in ("unversioned", "added") and entries[0].get("props") in ("none", "normal") and entries[0].get("tree-conflicted") != "true", "Owned version directory has unexpected SVN state; reconcile before continuing")
        if entries[0].get("item") == "unversioned":
            self.invoke("add", "--no-auto-props", "--depth", "empty", str(self.directory) + "@")
        properties = ElementTree.fromstring(self.invoke("proplist", "--xml", str(self.directory) + "@"))
        require(not properties.findall(".//property"), "Owned version directory has unrelated properties")
        return [str(self.directory) + "@"]

    def remote_revision(self, filename, expected_hash, marker):
        url = self.url + "/" + quote(filename, safe="")
        info = self.info(url)
        require(info is not None, "Remote report metadata unavailable")
        revision = info.find("commit").get("revision")
        content = self.invoke("cat", "-r", revision, url + "@" + revision)
        require(digest(content) == expected_hash, "Remote report hash mismatch; do not overwrite")
        log = ElementTree.fromstring(self.invoke("log", "--xml", "-r", revision, url + "@" + revision))
        require(any(marker in (entry.findtext("msg") or "") for entry in log.findall("logentry")), "Remote commit marker mismatch")
        return revision

    def commit(self, report, expected_hash, marker, state, save, content=None):
        if state.get("svn_revision"):
            return state["svn_revision"]
        if state.get("svn_pending"):
            revision = self.remote_revision(report.name, expected_hash, marker)
            state["svn_revision"] = revision
            state.pop("svn_pending", None)
            save()
            return revision
        self.preflight()
        directory_targets = self.prepare_directory(report, state, save)
        destination = contained(self.directory, report.name)
        if destination.exists():
            require(digest(destination.read_bytes()) == expected_hash, "Existing local SVN report differs")
        else:
            data = report.read_bytes() if content is None else content
            require(digest(data) == expected_hash, "Sealed HTML was modified")
            with destination.open("xb") as stream:
                stream.write(data)
        entries = ElementTree.fromstring(self.invoke("status", "--xml", str(destination) + "@")).findall(".//wc-status")
        require(len(entries) == 1 and entries[0].get("item") in ("unversioned", "added") and entries[0].get("props") in ("none", "normal"), "Report already versioned or modified; reconcile previous publication")
        if entries[0].get("item") == "unversioned":
            self.invoke("add", "--no-auto-props", "--depth", "empty", str(destination) + "@")
        properties = ElementTree.fromstring(self.invoke("proplist", "--xml", str(destination) + "@"))
        require(not properties.findall(".//property"), "SVN report properties could transform bytes or include unrelated changes")
        require(digest(destination.read_bytes()) == expected_hash, "Report changed before commit")
        state["svn_pending"] = True
        save()
        self.invoke("commit", "--depth", "empty", "-m", marker, *directory_targets, str(destination) + "@")
        revision = self.remote_revision(report.name, expected_hash, marker)
        state["svn_revision"] = revision
        state.pop("svn_pending", None)
        save()
        return revision


def send_once(service, state, save, stage, message_type, content):
    identifier_key = stage + "_message_id"
    pending_key = stage + "_pending"
    if state.get(identifier_key):
        return state[identifier_key]
    require(not state.get(pending_key), "Previous " + stage + " message result is uncertain; reconcile chat history before retrying")
    request_key = stage + "_uuid"
    state.setdefault(request_key, uuid.uuid4().hex)
    state[pending_key] = True
    save()
    try:
        identifier = service.send(message_type, content, state[request_key])
        require(isinstance(identifier, str) and identifier, "Message response missing identifier; reconcile delivery")
    except ApiRejected:
        state.pop(pending_key, None)
        save()
        raise
    state[identifier_key] = identifier
    state.pop(pending_key, None)
    save()
    return identifier


def deliver(service, report, context, manifest, state, save):
    if not state.get("file_key"):
        state["file_key"] = service.upload(report)
        require(isinstance(state["file_key"], str) and state["file_key"], "File upload response lacks file_key")
        save()
    send_once(service, state, save, "file", "file", {"file_key": state["file_key"]})
    summary = "OpenSpec AI Review\n版本：" + context["version"] + "\n目标：" + context["target_branch"] + " @ " + context["target_sha"] + "\n主干：" + context["base_branch"] + " @ " + context["base_sha"]
    summary += "\n" + " / ".join(key + ": " + str(count) for key, count in manifest["counts"].items()) + "（报告问题数量）"
    summary += "\nSVN r" + str(state["svn_revision"]) + "\n" + report.name + "\nrun: " + context["run_id"]
    send_once(service, state, save, "summary", "text", {"text": summary})


def publish(config_path, run_path):
    config = load_config(config_path)
    run = Path(run_path).resolve()
    with lock(run / ".review.lock"):
        context = load_json(run / "context.json")
        manifest = load_json(run / "report-manifest.json")
        version = version_for(config, context["target_branch"], context["base_branch"])
        require(scope_key(config, version) == context["scope_key"], "Version/repository/document configuration changed since collection")
        require(manifest["file"] in (report_filename(context), "ai-review-" + context["run_id"] + ".html"), "Invalid sealed report name")
        require(manifest["schema_version"] in (1, 2), "Unsupported report manifest schema")
        content = manifest["html"].encode("utf-8") if manifest["schema_version"] == 2 else contained(run, manifest["file"]).read_bytes()
        require(digest(content) == manifest["sha256"], "Sealed HTML was modified")
        require(digest((run / "context.json").read_bytes()) == manifest["context_sha256"], "Pinned context was modified")
        require(digest((run / "review.final.json").read_bytes()) == manifest["review_sha256"], "Sealed review data was modified")
        svn = Svn(config["svn"], version)
        report = contained(svn.directory, manifest["file"])
        binding = {"report_sha256": manifest["sha256"], "svn_root": str(svn.root), "svn_url": svn.url, "svn_username": config["svn"].get("username", ""), "app_id": config["feishu"]["app_id"], "chat_id": config["feishu"]["chat_id"]}
        state_path = run / "publish-state.json"
        sentinel = run / ".publication-started"
        if state_path.exists():
            state = load_json(state_path)
            require(state["binding"] == binding, "Publication destination/report changed; do not reuse this state")
        else:
            require(not sentinel.exists(), "Publication state was lost; reconcile SVN and Feishu before resuming")
            state = {"schema_version": 1, "binding": binding, "run_id": context["run_id"]}

        def save():
            state["report_path"] = str(report)
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_json(state_path, state)

        if state.get("summary_message_id") and state.get("file_message_id") and state.get("svn_revision"):
            return state
        require(not state.get("file_pending") and not state.get("summary_pending"), "A previous message is unresolved; reconcile before another send")
        service = Feishu(config["feishu"])
        with lock((svn.report_root or svn.directory) / ".openspec-ai-review.publish.lock"):
            save()
            sentinel.touch(exist_ok=True)
            marker = "OpenSpec AI Review " + context["version"] + " [" + context["run_id"] + "]"
            svn.commit(report, manifest["sha256"], marker, state, save, content=content)
            require(digest(report.read_bytes()) == manifest["sha256"], "HTML changed during publication")
            deliver(service, report, context, manifest, state, save)
        return state


def main():
    parser = argparse.ArgumentParser(description="Publish one sealed review to manually configured SVN and Feishu destinations")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--mode", choices=["review-publish"], required=True)
    args = parser.parse_args()
    try:
        state = publish(args.config, args.run)
        print(json.dumps({key: state.get(key) for key in ("report_path", "svn_revision", "file_message_id", "summary_message_id")}, ensure_ascii=False))
    except (ReviewError, OSError, ValueError, KeyError, TypeError, ElementTree.ParseError) as error:
        print("Publication stopped: " + (str(error) if isinstance(error, ReviewError) else type(error).__name__ + "; inspect configuration/state without exposing credentials"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
