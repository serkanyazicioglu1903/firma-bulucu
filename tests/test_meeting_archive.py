"""Portable archive security and meeting identity regression tests."""
import base64
from datetime import date

import pytest

from meeting_archive import (
    ArchiveError, HEADER, VOICE_HEADER, check_record, merge_records,
    new_record, pack_archive, unpack_archive, pack_voice, unpack_voice,
)

PASSWORD = "a-strong-private-passphrase!"


def entry(company="Müşteri A"):
    return new_record(company, "Pantur görüşmesi", "2026-10-25",
                      "## Özet\nAnlaşma yok.", "[00:00:01] BEN: Merhaba", "[00:00:01] Merhaba")


def test_archive_round_trip_is_encrypted_and_scoped_by_label():
    one = entry("Ülker")
    two = entry("Sonneveld")
    blob = pack_archive([one, two], PASSWORD)
    assert blob.startswith(HEADER)
    assert b"Pantur" not in blob
    restored = unpack_archive(blob, PASSWORD)
    assert {x["company"] for x in restored} == {"Ülker", "Sonneveld"}
    assert {x["id"] for x in restored} == {one["id"], two["id"]}


def test_wrong_password_and_corruption_fail_closed():
    blob = pack_archive([entry()], PASSWORD)
    with pytest.raises(ArchiveError):
        unpack_archive(blob, "not-the-correct-password")
    with pytest.raises(ArchiveError):
        unpack_archive(b"plain-text", PASSWORD)
    with pytest.raises(ArchiveError):
        unpack_archive(blob[:40], PASSWORD)


def test_no_missing_fields_and_length_constraints():
    value = entry()
    assert check_record(value) == value
    value.pop("company")
    with pytest.raises(ArchiveError):
        check_record(value)
    with pytest.raises(ArchiveError):
        new_record("", "test", date.today().isoformat(), "", "", "")


def test_merging_same_record_is_an_update_not_a_duplicate():
    old = entry()
    changed = dict(old, summary="Güncellendi")
    result = merge_records([old], [changed])
    assert len(result) == 1
    assert result[0]["summary"] == "Güncellendi"


def test_voice_profile_is_encrypted_and_restored_as_wav():
    # Minimal valid WAV header for format validation; SDK speech quality is a separate test.
    wave = b"RIFF" + b"\0\0\0\0" + b"WAVE" + b"\0" * 3500
    reference = "data:audio/wav;base64," + base64.b64encode(wave).decode()
    blob = pack_voice(reference, PASSWORD)
    assert blob.startswith(VOICE_HEADER)
    assert b"RIFF" not in blob
    assert unpack_voice(blob, PASSWORD) == reference
    with pytest.raises(ArchiveError):
        unpack_voice(blob, "incorrect-passphrase!")
