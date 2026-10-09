from __future__ import annotations

import base64
import hashlib
import json
import platform as host_platform
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from updates.release_verify import normalize_architecture, select_artifact, validate_manifest


class UpdateVerificationError(RuntimeError):
    pass


def _host_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise UpdateVerificationError(f"unsupported update platform: {sys.platform}")


def _version_key(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", value.strip())
    if not match:
        raise UpdateVerificationError(f"release version is not supported: {value}")
    return tuple(int(part) for part in match.groups())


class SignedUpdater:
    def __init__(
        self,
        public_key_b64: str,
        install_dir: Path,
        *,
        current_version: str | None = None,
        platform_name: str | None = None,
        architecture: str | None = None,
        channel: str = "stable",
    ):
        try:
            key_bytes = base64.b64decode(public_key_b64, validate=True)
            self.public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
        except Exception as exc:
            raise UpdateVerificationError("release public key is invalid") from exc
        self.install_dir = Path(install_dir)
        self.current_version = current_version
        self.platform_name = platform_name or _host_platform()
        try:
            self.architecture = normalize_architecture(architecture or host_platform.machine())
        except ValueError as exc:
            raise UpdateVerificationError(str(exc)) from exc
        if channel not in {"stable", "beta", "dev"}:
            raise UpdateVerificationError("update channel is invalid")
        self.channel = channel

    def verify_manifest(self, manifest_bytes: bytes, signature_b64: str) -> dict:
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            self.public_key.verify(signature, manifest_bytes)
        except Exception as exc:
            raise UpdateVerificationError("manifest signature invalid") from exc
        try:
            value = validate_manifest(json.loads(manifest_bytes))
        except Exception as exc:
            raise UpdateVerificationError(f"manifest structure invalid: {exc}") from exc
        if value["channel"] != self.channel:
            raise UpdateVerificationError("manifest release channel does not match updater channel")
        if self.current_version is not None:
            if _version_key(value["version"]) <= _version_key(self.current_version):
                raise UpdateVerificationError("release is not newer than the installed version")
        return value

    def choose_artifact(self, manifest: dict, package_type: str | None = None) -> dict:
        try:
            return select_artifact(
                manifest,
                platform_name=self.platform_name,
                architecture=self.architecture,
                package_type=package_type,
            )
        except ValueError as exc:
            raise UpdateVerificationError(str(exc)) from exc

    @staticmethod
    def verify_file(path: Path, expected_sha256: str, expected_size: int | None = None) -> None:
        path = Path(path)
        if expected_size is not None and path.stat().st_size != expected_size:
            raise UpdateVerificationError("package size mismatch")
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expected_sha256.lower():
            raise UpdateVerificationError("package hash mismatch")

    def verify_artifact_file(self, path: Path, artifact: dict) -> None:
        if Path(path).name != artifact["name"]:
            raise UpdateVerificationError("downloaded package name does not match signed artifact")
        self.verify_file(Path(path), artifact["sha256"], artifact["size"])

    def stage_zip(self, zip_path: Path, expected_sha256: str, expected_size: int | None = None) -> Path:
        self.verify_file(zip_path, expected_sha256, expected_size)
        stage = Path(tempfile.mkdtemp(prefix="vishnu-update-"))
        root = stage.resolve()
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for info in archive.infolist():
                    destination = (root / info.filename).resolve()
                    if root not in destination.parents and destination != root:
                        raise UpdateVerificationError("unsafe zip path")
                    if info.is_dir():
                        continue
                    if info.external_attr >> 16 & 0o170000 == 0o120000:
                        raise UpdateVerificationError("symbolic links are not allowed in updates")
                archive.extractall(stage)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        return stage

    def install_staged(
        self,
        stage: Path,
        *,
        health_check: Callable[[Path], bool] | None = None,
    ) -> Path:
        stage = Path(stage).resolve()
        if not stage.is_dir():
            raise FileNotFoundError(stage)
        backup = self.install_dir.with_name(self.install_dir.name + ".backup")
        candidate = self.install_dir.with_name(self.install_dir.name + ".update-tmp")
        if backup.exists():
            shutil.rmtree(backup)
        if candidate.exists():
            shutil.rmtree(candidate)
        shutil.copytree(stage, candidate)
        had_previous = self.install_dir.exists()
        try:
            if had_previous:
                self.install_dir.replace(backup)
            candidate.replace(self.install_dir)
            if health_check is not None:
                try:
                    healthy = bool(health_check(self.install_dir))
                except Exception as exc:
                    raise RuntimeError("post-update health check raised an exception") from exc
                if not healthy:
                    raise RuntimeError("post-update health check failed")
        except Exception:
            if self.install_dir.exists():
                shutil.rmtree(self.install_dir)
            if backup.exists():
                backup.replace(self.install_dir)
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
            raise
        return backup

    def apply_signed_zip(
        self,
        manifest_bytes: bytes,
        signature_b64: str,
        zip_path: Path,
        *,
        health_check: Callable[[Path], bool] | None = None,
    ) -> Path:
        manifest = self.verify_manifest(manifest_bytes, signature_b64)
        artifact = self.choose_artifact(manifest, package_type="zip")
        self.verify_artifact_file(zip_path, artifact)
        stage = self.stage_zip(zip_path, artifact["sha256"], artifact["size"])
        try:
            return self.install_staged(stage, health_check=health_check)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def rollback(self, backup: Path) -> Path:
        backup = Path(backup)
        if not backup.exists():
            raise FileNotFoundError("update backup does not exist")
        restore = self.install_dir.with_name(self.install_dir.name + ".restore-tmp")
        if restore.exists():
            shutil.rmtree(restore)
        shutil.copytree(backup, restore)
        if self.install_dir.exists():
            shutil.rmtree(self.install_dir)
        restore.replace(self.install_dir)
        return self.install_dir
