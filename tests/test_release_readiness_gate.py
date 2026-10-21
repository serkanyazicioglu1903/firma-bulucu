import json
from scripts.release_readiness_gate import assess_release, main, REQUIRED_EVIDENCE


def test_release_gate_denies_missing_evidence():
    result = assess_release()
    assert result["release_ready"] is False
    assert result["evidence_complete"] is False
    assert set(result["missing"]) == set(REQUIRED_EVIDENCE)
    assert len(result["companies"]) == 4


def test_release_gate_rejects_truthy_strings():
    result = assess_release({name: "true" for name in REQUIRED_EVIDENCE})
    assert result["evidence_complete"] is False


def test_offline_evidence_never_authorizes_live_release():
    result = assess_release({name: True for name in REQUIRED_EVIDENCE})
    assert result["evidence_complete"] is True
    assert result["release_ready"] is False


def test_cli_exits_nonzero_without_evidence(monkeypatch, capsys):
    monkeypatch.delenv("CT_RELEASE_EVIDENCE_FILE", raising=False)
    assert main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["release_ready"] is False
    assert "password" not in json.dumps(result).lower()
