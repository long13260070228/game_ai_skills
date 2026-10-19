import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


class ReviewError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def command_to_file(arguments, path, env=None, timeout=900):
    """Keep large Git patches out of subprocess buffers and model output."""
    try:
        with Path(path).open("wb") as output, open(os.devnull, "wb") as errors:
            result = subprocess.run(arguments, env=env, stdout=output, stderr=errors,
                                    timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReviewError("External command unavailable or timed out; inspect local client/authentication (output suppressed)") from None
    require(result.returncode == 0, "External command failed; inspect local client, permissions, refs or connectivity (output suppressed)")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def relative_path(value):
    require(isinstance(value, str) and value and "\\" not in value, "Use a nonempty relative path with forward slashes")
    require(not re.match(r"^[A-Za-z]:", value) and not value.startswith("/"), "Absolute path is not allowed here")
    require(all(part not in ("", ".", "..") for part in value.split("/")), "Unsafe relative path")
    require("\x00" not in value and "\n" not in value and "\r" not in value, "Invalid path")
    return Path(value)


def contained(root, relative):
    root = Path(root).resolve()
    candidate = root / relative_path(relative)
    require(candidate.resolve().is_relative_to(root), "Path or link escapes its root")
    return candidate


def absolute_path(value):
    path = Path(value).expanduser()
    require(path.is_absolute(), "An absolute path must be configured")
    return path.resolve()


def version_name(value):
    require(isinstance(value, str) and bool(value) and value == value.strip(), "Target version is required without surrounding whitespace")
    require(len(value) <= 100 and not re.search(r'[<>:"/\\|?*\x00-\x1f]', value) and not value.endswith("."), "Target version must be a valid single Windows folder/file name")
    require(value not in (".", "..") and value.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", "CLOCK$", *("COM" + str(number) for number in range(1, 10)), *("LPT" + str(number) for number in range(1, 10))}, "Reserved target version name")
    return value


def report_filename(context):
    require(re.fullmatch(r"[A-Za-z0-9_-]+", context["run_id"]), "Invalid run identifier")
    return version_name(context["version"]) + "-ai-review-" + context["run_id"] + ".html"


def safe_url(value):
    require(isinstance(value, str) and value and not value.startswith("-"), "Invalid repository address")
    require(not any(char in value for char in "\r\n\x00"), "Invalid repository address")
    if "://" in value:
        parsed = urlsplit(value)
        require(parsed.scheme in ("https", "ssh", "file", "svn", "svn+ssh"), "Unsupported or insecure repository protocol")
        require(not parsed.password and not parsed.query and not parsed.fragment, "Credentials/query/fragment must not appear in URLs")
        require(parsed.scheme != "https" or not parsed.username, "Configure HTTPS username separately")
    else:
        require(Path(value).is_absolute() or re.fullmatch(r"(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9_.-]+:[A-Za-z0-9_./~-]+", value), "Use an absolute local path or a normal SSH repository address")


def load_config(path):
    config = load_json(path)

    def check_secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                require(key.lower() not in ("password", "token", "secret", "app_secret", "access_token"), "Store credentials in OS providers or environment variables, not configuration")
                check_secrets(item)
        elif isinstance(value, list):
            for item in value:
                check_secrets(item)

    check_secrets(config)
    require(config.get("schema_version") == 1, "Unsupported configuration schema")
    require(config.get("default_mode") in ("review", "review-publish"), "Invalid default_mode")
    require(config["git"].get("auth") == "credential-manager-or-ssh", "Git must use local credential manager or SSH")
    safe_url(config["git"]["url"])
    return config


def version_for(config, target, base):
    matches = [item for item in config["versions"] if item["target_branch"] == target and item["base_branch"] == base]
    require(len(matches) == 1, "Branch pair must match exactly one configured version")
    version_name(matches[0]["version"])
    return matches[0]


def scope_key(config, version):
    return fingerprint({"project": config["project"], "repository": config["git"]["url"], "version": version})


def command(arguments, cwd=None, env=None, timeout=180):
    try:
        result = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReviewError("External command unavailable or timed out; inspect local client/authentication (output suppressed)") from None
    require(result.returncode == 0, "External command failed; inspect local client, permissions, refs or connectivity (output suppressed)")
    return result.stdout


@contextlib.contextmanager
def lock(path):
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ReviewError("Run or destination is locked; confirm previous process/state before recovering") from None
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)
