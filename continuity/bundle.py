from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .models import ContinuityCheckpoint, TransferGrant


BUNDLE_MAGIC = b"VISHNUCONT1\n"
BUNDLE_VERSION = 1
BUNDLE_TAG_BYTES = 16
BUNDLE_HEADER_MAX = 128 * 1024
BUNDLE_CHUNK = 1024 * 1024
BUNDLE_INFO = b"vishnu-cross-host-continuity-v1"


class ContinuityBundleError(RuntimeError):
    pass


class PortableContinuityBundleCodec:
    """One-time authenticated transport for a checkpoint payload.

    The transfer grant token is used only as HKDF input and is never persisted in
    the bundle. The owner root key remains host-local and is never exported.
    """

    @staticmethod
    def _derive_key(token: str, salt: bytes) -> bytes:
        raw = str(token or "").encode("utf-8")
        if len(raw) < 32:
            raise ContinuityBundleError("transfer credential is invalid")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=BUNDLE_INFO,
        ).derive(raw)

    @staticmethod
    def _header_bytes(header: dict) -> bytes:
        return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def encrypt_payload(
        self,
        payload: str | Path,
        target: str | Path,
        *,
        checkpoint: ContinuityCheckpoint,
        grant: TransferGrant,
    ) -> Path:
        source = Path(payload)
        destination = Path(target)
        if not source.is_file():
            raise FileNotFoundError(source)
        if grant.checkpoint_id != checkpoint.id:
            raise ValueError("grant does not match checkpoint")
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        header = {
            "version": BUNDLE_VERSION,
            "cipher": "AES-256-GCM",
            "kdf": "HKDF-SHA256",
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "grant_id": grant.id,
            "source_host_id": grant.source_host_id,
            "target_host_id": grant.target_host_id,
            "source_epoch": grant.source_epoch,
            "checkpoint": checkpoint.to_dict(),
        }
        encoded = self._header_bytes(header)
        if len(encoded) > BUNDLE_HEADER_MAX:
            raise ContinuityBundleError("continuity bundle header is too large")
        raw_len = struct.pack(">I", len(encoded))
        aad = BUNDLE_MAGIC + raw_len + encoded
        key = self._derive_key(grant.token, salt)
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(aad)

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
        try:
            with source.open("rb") as src, temporary.open("wb") as dst:
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                dst.write(aad)
                for chunk in iter(lambda: src.read(BUNDLE_CHUNK), b""):
                    dst.write(encryptor.update(chunk))
                dst.write(encryptor.finalize())
                dst.write(encryptor.tag)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temporary, destination)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def decrypt_payload(self, bundle: str | Path, *, token: str) -> tuple[Path, dict]:
        source = Path(bundle)
        handle = tempfile.NamedTemporaryFile(
            prefix="vishnu-continuity-payload-", suffix=".zip", delete=False
        )
        target = Path(handle.name)
        handle.close()
        try:
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            with source.open("rb") as src:
                if src.read(len(BUNDLE_MAGIC)) != BUNDLE_MAGIC:
                    raise ContinuityBundleError("unsupported continuity bundle")
                raw_len = src.read(4)
                if len(raw_len) != 4:
                    raise ContinuityBundleError("continuity bundle header is truncated")
                size = struct.unpack(">I", raw_len)[0]
                if size <= 0 or size > BUNDLE_HEADER_MAX:
                    raise ContinuityBundleError("continuity bundle header is invalid")
                encoded = src.read(size)
                if len(encoded) != size:
                    raise ContinuityBundleError("continuity bundle header is truncated")
                try:
                    header = json.loads(encoded)
                    if (
                        int(header.get("version", 0)) != BUNDLE_VERSION
                        or header.get("cipher") != "AES-256-GCM"
                        or header.get("kdf") != "HKDF-SHA256"
                    ):
                        raise ValueError("unsupported continuity header")
                    salt = base64.b64decode(header["salt"], validate=True)
                    nonce = base64.b64decode(header["nonce"], validate=True)
                except Exception as exc:
                    raise ContinuityBundleError("continuity bundle header is invalid") from exc
                if len(salt) != 16 or len(nonce) != 12:
                    raise ContinuityBundleError("continuity bundle header is invalid")

                ciphertext_start = src.tell()
                total = source.stat().st_size
                ciphertext_size = total - ciphertext_start - BUNDLE_TAG_BYTES
                if ciphertext_size < 0:
                    raise ContinuityBundleError("continuity bundle ciphertext is truncated")
                src.seek(total - BUNDLE_TAG_BYTES)
                tag = src.read(BUNDLE_TAG_BYTES)
                if len(tag) != BUNDLE_TAG_BYTES:
                    raise ContinuityBundleError("continuity bundle authentication tag is missing")
                src.seek(ciphertext_start)

                aad = BUNDLE_MAGIC + raw_len + encoded
                key = self._derive_key(token, salt)
                decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(aad)
                remaining = ciphertext_size
                with target.open("wb") as dst:
                    while remaining:
                        chunk = src.read(min(BUNDLE_CHUNK, remaining))
                        if not chunk:
                            raise ContinuityBundleError("continuity bundle ciphertext is truncated")
                        remaining -= len(chunk)
                        dst.write(decryptor.update(chunk))
                    try:
                        dst.write(decryptor.finalize())
                    except InvalidTag as exc:
                        raise ContinuityBundleError("continuity bundle authentication failed") from exc
                    dst.flush()
                    os.fsync(dst.fileno())
            # Only authenticated header data is returned.
            ContinuityCheckpoint.from_dict(dict(header["checkpoint"]))
            return target, header
        except Exception:
            target.unlink(missing_ok=True)
            raise
