from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

_ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".html",
    ".sql", ".xml", ".svg",
}
_MAX_FILES = 5
_MAX_FILE_BYTES = 48 * 1024
_MAX_TOTAL_BYTES = 96 * 1024
_MAX_PATH_DEPTH = 4


class ArtifactValidationError(ValueError):
    """Raised when a model-generated artifact violates workspace constraints."""


def workspace_root() -> Path:
    configured = (os.getenv("AGENTHQ_WORKSPACE_DIR") or "").strip()
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "data" / "agenthq-workspace"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def _safe_relative_path(raw_path: Any) -> PurePosixPath:
    if not isinstance(raw_path, str):
        raise ArtifactValidationError("Every artifact must have a string path.")
    value = raw_path.strip()
    if not value or len(value) > 180 or "\x00" in value or "\\" in value or ":" in value:
        raise ArtifactValidationError("Artifact path is empty or invalid.")
    if value.startswith("/") or value.startswith("~"):
        raise ArtifactValidationError("Absolute artifact paths are not allowed.")
    rel = PurePosixPath(value)
    if len(rel.parts) > _MAX_PATH_DEPTH or any(part in {"", ".", ".."} or part.startswith(".") for part in rel.parts):
        raise ArtifactValidationError("Artifact path contains a hidden or traversing path segment.")
    if rel.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ArtifactValidationError("Artifact extension is not allowed.")
    if rel.name.casefold() in {"credentials.json", "secrets.json", ".env", "id_rsa", "id_ed25519"}:
        raise ArtifactValidationError("Sensitive filenames are not allowed.")
    return rel


def _contained_path(base: Path, relative_path: PurePosixPath) -> Path:
    candidate = (base / Path(*relative_path.parts)).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as error:
        raise ArtifactValidationError("Artifact path escaped its assigned workspace.") from error
    return candidate


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    with path.open("xb") as handle:
        handle.write(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def write_draft_artifacts(execution_id: str, files: Any) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", execution_id or ""):
        raise ArtifactValidationError("Execution identifier is invalid.")
    if not isinstance(files, list) or not 1 <= len(files) <= _MAX_FILES:
        raise ArtifactValidationError(f"The agent must return between 1 and {_MAX_FILES} files.")
    root = workspace_root()
    draft_dir = root / "pending" / execution_id
    draft_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        draft_dir.chmod(0o700)
    except OSError:
        pass

    manifest: list[dict[str, Any]] = []
    total_bytes = 0
    seen: set[str] = set()
    try:
        for item in files:
            if not isinstance(item, dict):
                raise ArtifactValidationError("Artifact entries must be objects with path and content.")
            rel = _safe_relative_path(item.get("path"))
            relative = rel.as_posix()
            if relative in seen:
                raise ArtifactValidationError("Duplicate artifact paths are not allowed.")
            seen.add(relative)
            content = item.get("content")
            if not isinstance(content, str):
                raise ArtifactValidationError(f"Artifact '{relative}' must contain text.")
            payload = content.encode("utf-8")
            if not payload or len(payload) > _MAX_FILE_BYTES:
                raise ArtifactValidationError(f"Artifact '{relative}' is empty or exceeds the 48 KB per-file limit.")
            total_bytes += len(payload)
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ArtifactValidationError("The execution exceeds the 96 KB total artifact limit.")

            validation = "text"
            if rel.suffix.lower() == ".py":
                try:
                    ast.parse(content, filename=relative, mode="exec")
                except SyntaxError as error:
                    raise ArtifactValidationError(f"Python syntax validation failed for '{relative}': {error.msg}.") from error
                validation = "python_ast"
            elif rel.suffix.lower() == ".json":
                try:
                    json.loads(content)
                except json.JSONDecodeError as error:
                    raise ArtifactValidationError(f"JSON validation failed for '{relative}' at line {error.lineno}.") from error
                validation = "json"

            output = _contained_path(draft_dir, rel)
            _write_private(output, payload)
            manifest.append({
                "path": relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "validation": validation,
            })
        return manifest
    except Exception:
        shutil.rmtree(draft_dir, ignore_errors=True)
        raise


def publish_approved_artifacts(execution_id: str, manifest: list[dict[str, Any]]) -> Path:
    root = workspace_root()
    source_dir = root / "pending" / execution_id
    target_dir = root / "approved" / execution_id
    if not source_dir.is_dir():
        raise ArtifactValidationError("The private draft workspace is missing.")
    target_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        for item in manifest:
            rel = _safe_relative_path(item.get("path"))
            source = _contained_path(source_dir, rel)
            target = _contained_path(target_dir, rel)
            if not source.is_file() or source.is_symlink():
                raise ArtifactValidationError("A draft artifact is missing or is not a regular file.")
            payload = source.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != item.get("sha256"):
                raise ArtifactValidationError("A draft artifact changed after validation; approval was stopped.")
            _write_private(target, payload)
        return target_dir
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


def resolve_artifact(execution_id: str, artifact_path: str, manifest: list[dict[str, Any]], approved: bool) -> Path:
    rel = _safe_relative_path(artifact_path)
    expected = rel.as_posix()
    if not any(item.get("path") == expected for item in manifest):
        raise FileNotFoundError("Artifact not found.")
    folder = workspace_root() / ("approved" if approved else "pending") / execution_id
    candidate = _contained_path(folder, rel)
    if not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("Artifact not found.")
    return candidate


def remove_approved_workspace(execution_id: str) -> None:
    root = workspace_root()
    target = (root / "approved" / execution_id).resolve()
    try:
        target.relative_to((root / "approved").resolve())
    except ValueError:
        return
    shutil.rmtree(target, ignore_errors=True)
