"""Offline checks for the meeting recorder. No network or API key required."""
from pathlib import Path
from types import SimpleNamespace

from meeting_core import (
    Speech, compile_report, my_speech_text, parse_transcription,
    timestamp, transcript_text, transcribe_chunks,
)


def test_timestamp():
    assert timestamp(3661.7) == "01:01:01"
    assert timestamp(-30) == "00:00:00"


def test_speaker_identification_is_chunk_scoped():
    response = {"segments": [
        {"speaker": "A", "start": 1, "end": 3, "text": "Merhaba"},
        {"speaker": "BEN", "start": 3, "end": 5, "text": "Hello"},
    ]}
    result = parse_transcription(response, part=2, offset=2700)
    assert result[0] == Speech(2701, 2703, "B2:A", "Merhaba", 2)
    assert result[1].speaker == "BEN"
    assert result[1].start == 2703


def test_transcript_does_not_attribute_others_to_me():
    speeches = [
        Speech(0, 2, "B1:A", "Teklif verelim", 1),
        Speech(3, 5, "BEN", "Gelecek hafta görüşürüz", 1),
    ]
    output = transcript_text(speeches, {"BEN"}, "Serkan")
    assert "B1:A: Teklif verelim" in output
    assert "Serkan (ben): Gelecek hafta görüşürüz" in output
    assert my_speech_text(speeches, {"BEN"}) == "[00:00:03] Gelecek hafta görüşürüz"
    assert "Teklif verelim" not in my_speech_text(speeches, {"BEN"})


def test_known_voice_uses_sdk_extra_body(tmp_path: Path):
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"test")
    calls = []

    class API:
        def create(self, *, file, **kwargs):
            calls.append(kwargs)
            assert file.read() == b"test"
            return {"segments": [
                {"speaker": "BEN", "start": 0, "end": 2, "text": "Tamam"}
            ]}

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=API()))
    result = transcribe_chunks(client, [audio], "data:audio/wav;base64,AAAA")
    assert result[0].speaker == "BEN"
    assert calls[0]["extra_body"]["known_speaker_names"] == ["BEN"]
    assert calls[0]["response_format"] == "diarized_json"
    assert calls[0]["chunking_strategy"] == "auto"


def test_report_contains_metadata_and_raw_transcript():
    result = compile_report(
        {"Konu": "Ürün görüşmesi", "Firma": "Örnek Ltd."},
        "## Kararlar\nKarar yok", "[00:00:00] BEN: Merhaba", "[00:00:00] Merhaba"
    )
    assert "Ürün görüşmesi" in result
    assert "Karar yok" in result
    assert "Tam konuşma dökümü" in result
    assert "BEN: Merhaba" in result
