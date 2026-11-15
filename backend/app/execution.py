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


def storage_mode() -> str:
    mode = (os.getenv("AGENTHQ_WORKSPACE_STORAGE") or "local").strip().casefold()
    if mode not in {"local", "s3"}:
        raise ArtifactValidationError("AGENTHQ_WORKSPACE_STORAGE must be 'local' or 's3'.")
    return mode


def workspace_root() -> Path:
    if storage_mode() == "s3":
        raise ArtifactValidationError("Local workspace paths are unavailable while S3 storage is enabled.")
    configured = (os.getenv("AGENTHQ_WORKSPACE_DIR") or "").strip()
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "data" / "agenthq-workspace"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def _s3_config() -> tuple[str, str, str, str, str | None]:
    bucket = (os.getenv("AWS_S3_BUCKET") or "").strip()
    access_key = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
    secret_key = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
    region = (os.getenv("AWS_REGION") or "us-east-1").strip()
    endpoint = (os.getenv("AWS_ENDPOINT_URL_S3") or "").strip() or None
    if not bucket or not access_key or not secret_key:
        raise ArtifactValidationError(
            "S3 artifact storage is enabled but AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY are not configured."
        )
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,63}", bucket):
        raise ArtifactValidationError("AWS_S3_BUCKET contains an invalid bucket name.")
    if endpoint:
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ArtifactValidationError("AWS_ENDPOINT_URL_S3 must be a credential-free HTTPS URL.")
    return bucket, access_key, secret_key, region, endpoint


def _s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise ArtifactValidationError("S3 artifact storage dependency is not installed.") from error

    bucket, access_key, secret_key, region, endpoint = _s3_config()
    addressing_style = "path" if endpoint else "auto"
    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": addressing_style},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    return client, bucket


def _s3_key(stage: str, execution_id: str, relative_path: str = "") -> str:
    suffix = f"/{relative_path}" if relative_path else ""
    return f"agenthq/executions/{stage}/{execution_id}{suffix}"


def _s3_put(client: Any, bucket: str, key: str, payload: bytes, digest: str, validation: str) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentType="text/plain; charset=utf-8",
        Metadata={"sha256": digest, "validation": validation},
    )


def _s3_read(client: Any, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response.get("Body")
    if body is None:
        raise FileNotFoundError("Artifact not found.")
    return body.read()


def _s3_delete_prefix(stage: str, execution_id: str) -> None:
    try:
        client, bucket = _s3_client()
        prefix = _s3_key(stage, execution_id) + "/"
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", []) if item.get("Key")]
            if objects:
                client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
    except Exception:
        # Cleanup is best-effort; access errors must not mask the primary result.
        return


def _safe_relative_path(raw_path: Any) -> PurePosixPath:
    if not isinstance(raw_path, str):
        raise ArtifactValidationError("Every artifact must have a string path.")
    value = raw_path.strip()
    if (
        not value
        or len(value) > 180
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
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


def _validate_artifacts(files: Any) -> list[tuple[str, bytes, str, str]]:
    if not isinstance(files, list) or not 1 <= len(files) <= _MAX_FILES:
        raise ArtifactValidationError(f"The agent must return between 1 and {_MAX_FILES} files.")
    prepared: list[tuple[str, bytes, str, str]] = []
    total_bytes = 0
    seen: set[str] = set()
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
        prepared.append((relative, payload, hashlib.sha256(payload).hexdigest(), validation))
    return prepared


def write_draft_artifacts(execution_id: str, files: Any) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", execution_id or ""):
        raise ArtifactValidationError("Execution identifier is invalid.")
    prepared = _validate_artifacts(files)
    manifest: list[dict[str, Any]] = []

    if storage_mode() == "s3":
        client, bucket = _s3_client()
        uploaded: list[str] = []
        try:
            for relative, payload, digest, validation in prepared:
                key = _s3_key("pending", execution_id, relative)
                _s3_put(client, bucket, key, payload, digest, validation)
                uploaded.append(key)
                manifest.append({
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": digest,
                    "validation": validation,
                })
            return manifest
        except Exception as error:
            if uploaded:
                try:
                    client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": key} for key in uploaded], "Quiet": True},
                    )
                except Exception:
                    pass
            if isinstance(error, ArtifactValidationError):
                raise
            raise ArtifactValidationError("Unable to persist draft artifacts to configured S3 storage.") from error

    root = workspace_root()
    draft_dir = root / "pending" / execution_id
    draft_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        draft_dir.chmod(0o700)
    except OSError:
        pass
    try:
        for relative, payload, digest, validation in prepared:
            rel = PurePosixPath(relative)
            output = _contained_path(draft_dir, rel)
            _write_private(output, payload)
            manifest.append({
                "path": relative,
                "size_bytes": len(payload),
                "sha256": digest,
                "validation": validation,
            })
        return manifest
    except Exception:
        shutil.rmtree(draft_dir, ignore_errors=True)
        raise


def publish_approved_artifacts(execution_id: str, manifest: list[dict[str, Any]]) -> Path | None:
    if storage_mode() == "s3":
        client, bucket = _s3_client()
        uploaded: list[str] = []
        try:
            for item in manifest:
                rel = _safe_relative_path(item.get("path"))
                relative = rel.as_posix()
                source_key = _s3_key("pending", execution_id, relative)
                target_key = _s3_key("approved", execution_id, relative)
                payload = _s3_read(client, bucket, source_key)
                digest = hashlib.sha256(payload).hexdigest()
                if digest != item.get("sha256"):
                    raise ArtifactValidationError("A draft artifact changed after validation; approval was stopped.")
                if len(payload) != int(item.get("size_bytes") or -1):
                    raise ArtifactValidationError("A draft artifact size changed after validation; approval was stopped.")
                _s3_put(client, bucket, target_key, payload, digest, str(item.get("validation") or "text"))
                uploaded.append(target_key)
            return None
        except Exception as error:
            if uploaded:
                try:
                    client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": key} for key in uploaded], "Quiet": True},
                    )
                except Exception:
                    pass
            if isinstance(error, ArtifactValidationError):
                raise
            raise ArtifactValidationError("Unable to publish approved artifacts to configured S3 storage.") from error

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


def read_artifact_bytes(
    execution_id: str,
    artifact_path: str,
    manifest: list[dict[str, Any]],
    approved: bool,
) -> bytes:
    rel = _safe_relative_path(artifact_path)
    expected = rel.as_posix()
    item = next((entry for entry in manifest if entry.get("path") == expected), None)
    if item is None:
        raise FileNotFoundError("Artifact not found.")

    if storage_mode() == "s3":
        stage = "approved" if approved else "pending"
        client, bucket = _s3_client()
        try:
            payload = _s3_read(client, bucket, _s3_key(stage, execution_id, expected))
        except Exception as error:
            raise FileNotFoundError("Artifact not found.") from error
    else:
        folder = workspace_root() / ("approved" if approved else "pending") / execution_id
        candidate = _contained_path(folder, rel)
        if not candidate.is_file() or candidate.is_symlink():
            raise FileNotFoundError("Artifact not found.")
        payload = candidate.read_bytes()

    if hashlib.sha256(payload).hexdigest() != item.get("sha256"):
        raise ArtifactValidationError("Artifact integrity check failed.")
    if len(payload) != int(item.get("size_bytes") or -1):
        raise ArtifactValidationError("Artifact size validation failed.")
    return payload


def resolve_artifact(execution_id: str, artifact_path: str, manifest: list[dict[str, Any]], approved: bool) -> Path:
    """Resolve a local artifact path for local-only integrations and tests."""
    if storage_mode() == "s3":
        raise ArtifactValidationError("Path resolution is unavailable with S3 storage; use read_artifact_bytes().")
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
    if storage_mode() == "s3":
        _s3_delete_prefix("approved", execution_id)
        return
    root = workspace_root()
    target = (root / "approved" / execution_id).resolve()
    try:
        target.relative_to((root / "approved").resolve())
    except ValueError:
        return
    shutil.rmtree(target, ignore_errors=True)


def remove_draft_workspace(execution_id: str) -> None:
    if storage_mode() == "s3":
        _s3_delete_prefix("pending", execution_id)
        return
    root = workspace_root()
    target = (root / "pending" / execution_id).resolve()
    try:
        target.relative_to((root / "pending").resolve())
    except ValueError:
        return
    shutil.rmtree(target, ignore_errors=True)
