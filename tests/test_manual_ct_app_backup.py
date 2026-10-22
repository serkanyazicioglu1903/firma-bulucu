from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from scripts.manual_ct_app_backup import (
    backup_commands, create_archive, validate_environment,
)


def test_fixed_schema_commands(tmp_path):
    dump, check = backup_commands(tmp_path / "ct.dump")
    assert "--schema=ct_app" in dump
    assert "--no-owner" in dump and "--no-acl" in dump
    assert check[:2] == ["pg_restore", "--list"]
    assert not any("--clean" in arg for arg in dump + check)


def test_remote_connection_requires_tls():
    env = dict(PGHOST="db.example.org", PGDATABASE="postgres",
               PGUSER="operator", PGPASSWORD="test")
    assert not validate_environment(env)
    assert validate_environment({**env, "PGSSLMODE": "require"})


def test_existing_backup_never_overwritten(tmp_path):
    target = tmp_path / "backup.dump"
    target.write_text("original")
    with pytest.raises(ValueError, match="backup_destination_already_exists"):
        create_archive(target, {
            "PGHOST": "localhost", "PGDATABASE": "postgres",
            "PGUSER": "operator", "PGPASSWORD": "test",
        })
    assert target.read_text() == "original"


def test_partial_archive_removed_on_failure(tmp_path):
    target = tmp_path / "backup.dump"
    env = {"PGHOST": "localhost", "PGDATABASE": "postgres",
           "PGUSER": "operator", "PGPASSWORD": "test"}
    def fake_run(command, **kwargs):
        target.write_bytes(b"partial")
        raise RuntimeError("failed")
    with patch("scripts.manual_ct_app_backup.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError):
            create_archive(target, env)
    assert not target.exists()


def test_archive_check_is_not_restore_verification(tmp_path):
    target = tmp_path / "backup.dump"
    env = {"PGHOST": "localhost", "PGDATABASE": "postgres",
           "PGUSER": "operator", "PGPASSWORD": "test"}
    def fake_run(command, **kwargs):
        if command[0] == "pg_dump":
            target.write_bytes(b"archive")
            return Mock()
        return Mock(stdout="TABLE ct_app customers")
    with patch("scripts.manual_ct_app_backup.subprocess.run", side_effect=fake_run):
        result = create_archive(target, env)
    assert result["archive_list_verified"] is True
    assert result["restore_verified"] is False
    assert result["production_migration_approved"] is False
