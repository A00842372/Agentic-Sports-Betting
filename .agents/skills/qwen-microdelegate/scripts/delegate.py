#!/usr/bin/env python3
"""Request and validate small, exact edits from a local Ollama model."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


MAX_CONTEXT = 12000
MAX_EDITS = 5
MAX_EDIT_CHARS = 4000
SCHEMA_VERSION = 1


class DelegationError(Exception):
    """A proposal is unsafe, stale, or unavailable."""


def repo_root():
    """Find the containing Git workspace from the current directory."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / ".git").exists():
            return directory.resolve()
    raise DelegationError("Run this command from inside a Git repository")


def workspace_path(root, supplied, *, must_exist=False, file_only=False):
    """Return an in-repository path without following symlink components."""
    candidate = Path(supplied)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise DelegationError(f"Path is outside the repository: {supplied}") from error
    if not relative.parts:
        raise DelegationError("A file path is required")
    if ".git" in relative.parts:
        raise DelegationError("Git metadata is not an authorized source or proposal path")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise DelegationError(f"Symlink paths are not allowed: {supplied}")
    if must_exist and not candidate.exists():
        raise DelegationError(f"File does not exist: {supplied}")
    if file_only and candidate.exists() and not candidate.is_file():
        raise DelegationError(f"Not a regular file: {supplied}")
    return candidate, relative.as_posix()


def read_source(path):
    try:
        raw = path.read_bytes()
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DelegationError(f"Source is not UTF-8: {path}") from error
    except OSError as error:
        raise DelegationError(f"Cannot read source: {error}") from error


def source_excerpt(source, start_line, end_line):
    if (start_line is None) != (end_line is None):
        raise DelegationError("Provide both --start-line and --end-line")
    if start_line is None:
        excerpt = source
    else:
        lines = source.splitlines(keepends=True)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            raise DelegationError("Invalid source line range")
        excerpt = "".join(lines[start_line - 1 : end_line])
    if not excerpt or len(excerpt) > MAX_CONTEXT:
        raise DelegationError(
            f"Source excerpt must contain 1 to {MAX_CONTEXT} characters; "
            "select a smaller line range"
        )
    return excerpt


def ollama_endpoint():
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    parsed = urllib.parse.urlsplit(host)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/api/chat"}):
        raise DelegationError("OLLAMA_HOST must be a loopback HTTP Ollama address")
    return host if parsed.path == "/api/chat" else host + "/api/chat"


def request_edits(task, expected, constraints, file_name, excerpt):
    try:
        timeout = float(os.environ.get("QWEN_TIMEOUT", "90"))
    except ValueError as error:
        raise DelegationError("QWEN_TIMEOUT must be a positive number") from error
    if not 0 < timeout <= 600:
        raise DelegationError("QWEN_TIMEOUT must be between 0 and 600 seconds")
    instruction = (
        "Implement only the stated small change in the supplied source excerpt. "
        "Return JSON matching the schema. Use exact, unique old_text from the excerpt. "
        "Make at most five localized replacements. Do not plan, execute commands, "
        "edit other files, or include markdown."
    )
    prompt = (
        f"Target file: {file_name}\nTask: {task}\nExpected behavior: {expected}\n"
        f"Constraints: {constraints or 'Keep unrelated behavior unchanged.'}\n"
        f"Source excerpt:\n{excerpt}"
    )
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "edits": {
                "type": "array", "minItems": 1, "maxItems": MAX_EDITS,
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["old_text", "new_text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "edits"],
        "additionalProperties": False,
    }
    model = os.environ.get("QWEN_MODEL", "qwen2.5-coder:7b")
    if not model.strip() or model.casefold().endswith(":cloud"):
        raise DelegationError("QWEN_MODEL must name a local Ollama model")
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0, "num_predict": 2048},
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        ollama_endpoint(), data=body,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            envelope = json.load(response)
        content = envelope["message"]["content"]
        return json.loads(content)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DelegationError(f"Local Ollama request failed: {error}") from error
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError) as error:
        raise DelegationError("Ollama returned invalid JSON") from error


def validate_edits(result, source, excerpt):
    if not isinstance(result, dict) or set(result) != {"summary", "edits"}:
        raise DelegationError("Model response must contain only summary and edits")
    summary, edits = result["summary"], result["edits"]
    if not isinstance(summary, str) or not summary.strip():
        raise DelegationError("Model response needs a nonempty summary")
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise DelegationError("Model response needs 1 to 5 edits")
    spans = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"old_text", "new_text"}:
            raise DelegationError("Each edit needs only old_text and new_text")
        old, new = edit["old_text"], edit["new_text"]
        if not isinstance(old, str) or not isinstance(new, str) or not old or old == new:
            raise DelegationError("Edits need distinct, nonempty old_text and new_text")
        if len(old) > MAX_EDIT_CHARS or len(new) > MAX_EDIT_CHARS:
            raise DelegationError("An edit exceeds the localized edit size limit")
        if excerpt.count(old) != 1 or source.count(old) != 1:
            raise DelegationError("old_text must match exactly once in excerpt and source")
        start = source.index(old)
        spans.append((start, start + len(old), new))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise DelegationError("Edits overlap")
    cursor = 0
    parts = []
    for start, end, replacement in spans:
        parts.extend((source[cursor:start], replacement))
        cursor = end
    parts.append(source[cursor:])
    return "".join(parts)


def diff_text(before, after, file_name):
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{file_name}", tofile=f"b/{file_name}"
    ))


def load_proposal(root, proposal_argument):
    proposal_path, _ = workspace_path(root, proposal_argument, must_exist=True, file_only=True)
    try:
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DelegationError(f"Cannot read proposal JSON: {error}") from error
    if not isinstance(proposal, dict) or set(proposal) != {
        "schema_version", "task", "file", "base_sha256", "excerpt", "result"
    } or proposal["schema_version"] != SCHEMA_VERSION:
        raise DelegationError("Invalid proposal structure or version")
    if not isinstance(proposal["file"], str) or not isinstance(proposal["excerpt"], str):
        raise DelegationError("Invalid proposal file or excerpt")
    target, relative = workspace_path(root, proposal["file"], must_exist=True, file_only=True)
    if relative != proposal["file"]:
        raise DelegationError("Proposal target must be a repository-relative path")
    raw, source = read_source(target)
    if not isinstance(proposal["base_sha256"], str) or hashlib.sha256(raw).hexdigest() != proposal["base_sha256"]:
        raise DelegationError("Stale proposal: source changed since proposal creation")
    if proposal["excerpt"] not in source:
        raise DelegationError("Stale proposal: source excerpt changed")
    updated = validate_edits(proposal["result"], source, proposal["excerpt"])
    return target, relative, source, updated, raw


def propose(args, root):
    target, relative = workspace_path(root, args.file, must_exist=True, file_only=True)
    output, _ = workspace_path(root, args.output, file_only=True)
    if output.exists():
        raise DelegationError(f"Proposal already exists: {output}")
    if not output.parent.is_dir():
        raise DelegationError("Proposal output directory must already exist")
    raw, source = read_source(target)
    excerpt = source_excerpt(source, args.start_line, args.end_line)
    result = request_edits(args.task, args.expected or args.task, args.constraints,
                           relative, excerpt)
    updated = validate_edits(result, source, excerpt)
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "task": args.task,
        "file": relative,
        "base_sha256": hashlib.sha256(raw).hexdigest(),
        "excerpt": excerpt,
        "result": result,
    }
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(proposal, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except OSError as error:
        raise DelegationError(f"Cannot save proposal: {error}") from error
    print(f"Proposal saved: {output}")
    print(diff_text(source, updated, relative), end="")


def check(args, root):
    _, relative, source, updated, _ = load_proposal(root, args.proposal)
    print(diff_text(source, updated, relative), end="")


def apply(args, root):
    target, relative, source, updated, original = load_proposal(root, args.proposal)
    mode = target.stat().st_mode
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=".qwen-edit-",
                                         delete=False) as stream:
            temp_name = stream.name
            stream.write(updated.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        if target.read_bytes() != original or target.is_symlink():
            raise DelegationError("Stale proposal: source changed before apply")
        os.replace(temp_name, target)
        temp_name = None
    except OSError as error:
        raise DelegationError(f"Cannot apply proposal: {error}") from error
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    print(f"Applied reviewed edits to {relative}")
    print(diff_text(source, updated, relative), end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    propose_parser = commands.add_parser("propose", help="Ask local Qwen for a reviewable edit")
    propose_parser.add_argument("--task", required=True)
    propose_parser.add_argument("--file", required=True)
    propose_parser.add_argument("--output", required=True)
    propose_parser.add_argument("--expected", help="Expected observable behavior; defaults to task")
    propose_parser.add_argument("--constraints", default="")
    propose_parser.add_argument("--start-line", type=int)
    propose_parser.add_argument("--end-line", type=int)
    for name in ("check", "apply"):
        commands.add_parser(name).add_argument("--proposal", required=True)
    args = parser.parse_args(argv)
    try:
        root = repo_root()
        {"propose": propose, "check": check, "apply": apply}[args.command](args, root)
        return 0
    except DelegationError as error:
        print(f"delegate: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
