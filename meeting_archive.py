"""Encrypted portable archive and speaker profile for the meeting notebook.

There is no server-side archive or raw voice persistence. All persisted data
must be explicitly downloaded by the user and can be imported later.
"""
from __future__ import annotations

import base64
import json
import os
import re
from datetime import date
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HEADER = b"ASMEET-ENC-V1\n"
VOICE_HEADER = b"ASVOICE-ENC-V1\n"
MAX_ARCHIVE = 12 * 1024 * 1024
MAX_VOICE = 1 * 1024 * 1024
MAX_RECORDS = 250
PASS_MIN = 12


class ArchiveError(ValueError):
    """Safe validation/decryption error without exposing meeting contents."""


def _key(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or len(password) < PASS_MIN:
        raise ArchiveError("Arşiv şifresi en az 12 karakter olmalı.")
    derive = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000,
    )
    return base64.urlsafe_b64encode(derive.derive(password.encode("utf-8")))


def _seal(payload: bytes, password: str, header: bytes, max_size: int) -> bytes:
    if len(payload) > max_size:
        raise ArchiveError("Veri güvenli arşiv boyut sınırını aşıyor.")
    salt = os.urandom(16)
    return header + base64.urlsafe_b64encode(salt + Fernet(_key(password, salt)).encrypt(payload))


def _open(blob: bytes, password: str, header: bytes, max_size: int) -> bytes:
    if not isinstance(blob, bytes) or len(blob) > max_size * 2 or not blob.startswith(header):
        raise ArchiveError("Dosya geçerli bir şifreli AS arşivi değil.")
    try:
        raw = base64.b64decode(blob[len(header):], altchars=b"-_", validate=True)
        salt, sealed = raw[:16], raw[16:]
        if len(salt) != 16:
            raise ValueError("No salt")
        content = Fernet(_key(password, salt)).decrypt(sealed)
        if len(content) > max_size:
            raise ValueError("Too large")
        return content
    except (InvalidToken, ValueError, TypeError, OverflowError) as exc:
        raise ArchiveError("Arşiv açılamadı. Şifreyi veya dosyayı kontrol edin.") from exc


def check_record(record: Any) -> dict[str, str]:
    if not isinstance(record, dict):
        raise ArchiveError("Arşivde geçersiz toplantı kaydı var.")
    required = {"id", "company", "title", "date", "summary", "transcript", "mine"}
    if set(record) != required:
        raise ArchiveError("Arşiv kaydı beklenen biçimde değil.")
    limits = {"id": 64, "company": 150, "title": 250, "date": 10,
              "summary": 250_000, "transcript": 1_500_000, "mine": 700_000}
    for key, limit in limits.items():
        if not isinstance(record[key], str) or len(record[key]) > limit:
            raise ArchiveError("Arşiv alanının uzunluğu veya türü geçersiz.")
    if not re.fullmatch(r"[0-9a-f]{32}", record["id"]):
        raise ArchiveError("Toplantı kimliği geçersiz.")
    try:
        date.fromisoformat(record["date"])
    except ValueError as exc:
        raise ArchiveError("Toplantı tarihi geçersiz.") from exc
    if not record["title"].strip() or not record["company"].strip():
        raise ArchiveError("Toplantı konusu ve firma boş bırakılamaz.")
    return dict(record)


def new_record(company: str, title: str, when: str, summary: str, transcript: str, mine: str, record_id: str | None = None) -> dict[str, str]:
    return check_record({"id": record_id or uuid4().hex, "company": company.strip(),
                         "title": title.strip(), "date": when, "summary": summary,
                         "transcript": transcript, "mine": mine})


def merge_records(existing: list[dict], incoming: list[dict]) -> list[dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for item in (*existing, *incoming):
        valid = check_record(item)
        records[valid["id"]] = valid
    if len(records) > MAX_RECORDS:
        raise ArchiveError(f"En fazla {MAX_RECORDS} toplantı saklanabilir.")
    return sorted(records.values(), key=lambda x: (x["date"], x["id"]), reverse=True)


def pack_archive(records: list[dict], password: str) -> bytes:
    validated = merge_records([], records)
    payload = json.dumps({"version": 1, "records": validated},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _seal(payload, password, HEADER, MAX_ARCHIVE)


def unpack_archive(blob: bytes, password: str) -> list[dict[str, str]]:
    try:
        item = json.loads(_open(blob, password, HEADER, MAX_ARCHIVE))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArchiveError("Arşiv içeriği okunamadı.") from exc
    if not isinstance(item, dict) or set(item) != {"version", "records"} or item["version"] != 1:
        raise ArchiveError("Arşiv sürümü desteklenmiyor.")
    if not isinstance(item["records"], list):
        raise ArchiveError("Arşivde geçerli bir toplantı listesi yok.")
    return merge_records([], item["records"])


def pack_voice(reference: str, password: str) -> bytes:
    if not isinstance(reference, str) or not reference.startswith("data:audio/wav;base64,"):
        raise ArchiveError("Ses örneği WAV biçiminde değil.")
    try:
        raw = base64.b64decode(reference.split(",", 1)[1], validate=True)
    except ValueError as exc:
        raise ArchiveError("Ses örneği okunamıyor.") from exc
    if not 2048 < len(raw) < MAX_VOICE:
        raise ArchiveError("Ses örneği boyutu desteklenmiyor.")
    return _seal(reference.encode("ascii"), password, VOICE_HEADER, MAX_VOICE)


def unpack_voice(blob: bytes, password: str) -> str:
    try:
        reference = _open(blob, password, VOICE_HEADER, MAX_VOICE).decode("ascii")
        if not reference.startswith("data:audio/wav;base64,"):
            raise ValueError("Bad voice type")
        raw = base64.b64decode(reference.split(",", 1)[1], validate=True)
        if not 2048 < len(raw) < MAX_VOICE or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            raise ValueError("Bad WAV header")
        return reference
    except (UnicodeError, ValueError) as exc:
        raise ArchiveError("Şifreli ses profili okunamadı.") from exc
