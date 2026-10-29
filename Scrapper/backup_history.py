"""Publish complete PostgreSQL backups and verify restores in fresh databases."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from uuid import UUID, uuid4


_REFERENCE_COLUMNS = (
    "match_id", "slot_id", "scheduled_time", "kickoff", "run_id", "started_at",
    "completed_at", "outcome_id", "bookmaker", "attempt_number", "attempted_at",
    "source_timestamp", "source_name", "source_url", "status", "error",
    "missing_fields", "field", "value",
)


def _service_conninfo(service, database=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", service):
        raise ValueError("Use a libpq service name containing letters, digits, dots, underscores or hyphens")
    connection = f"service={service}"
    if database is not None:
        # Database overrides are generated internally, never supplied by callers.
        connection += f" dbname={database}"
    return connection


def _run(command, *, service=None, quiet=False):
    environment = os.environ.copy()
    if service is not None:
        environment["PGSERVICE"] = service
    subprocess.run(command, check=True, env=environment, umask=0o077,
                   stdout=subprocess.DEVNULL if quiet else None)


def _history(match_id, connection):
    if __package__:
        from .match_history import read_match_history
    else:
        from match_history import read_match_history
    return read_match_history(match_id, database_url=connection)


def _reference_rows(history):
    import pandas as pd

    # Current names, provisional gaps and incomplete runs may change while a
    # dump is running. Committed outcome records are retained unchanged.
    observations = history[~history["status"].isin(("missed", "incomplete"))]
    result = []
    for _, observation in observations.iterrows():
        row = {}
        for column in _REFERENCE_COLUMNS:
            value = observation[column]
            if column == "missing_fields":
                row[column] = list(value)
            elif pd.isna(value):
                row[column] = None
            elif column == "attempt_number":
                row[column] = int(value)
            elif isinstance(value, datetime):
                row[column] = value.isoformat()
            else:
                row[column] = str(value)
        result.append(row)
    return result


def _checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sync(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_backup(directory, *, source_service, match_id=None):
    """Atomically publish a full custom archive, checksum and optional oracle.

    With a known match ID, capture immutable history before pg_dump starts.
    Concurrent collection can add rows; restore verification must retain every
    captured record, without requiring later observations to be absent.
    """
    connection = _service_conninfo(source_service)
    reference = None
    if match_id is not None:
        match_id = UUID(str(match_id))
        rows = _reference_rows(_history(match_id, connection))
        if not rows:
            raise ValueError("The verification match must have stored bookmaker outcomes")
        reference = {"match_id": str(match_id), "rows": rows}

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=directory))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"history-{stamp}-{uuid4().hex}"
    try:
        archive = staging / "database.dump"
        _run(["pg_dump", "--no-password", "--format=custom", "--file", str(archive)],
             service=source_service)
        os.chmod(archive, 0o600)
        _run(["pg_restore", "--list", str(archive)], quiet=True)
        manifest = {
            "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "sha256": _checksum(archive), "reference": reference,
        }
        metadata = staging / "manifest.json"
        with metadata.open("x", encoding="utf-8") as stream:
            os.chmod(metadata, 0o600)
            json.dump(manifest, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _sync(archive)
        _sync(staging)
        staging.rename(destination)
        _sync(directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def verify_backup(backup, *, restore_service, keep_database=False):
    """Restore into a newly created database and compare known match records.

    No existing database can be selected as a restore target. Only the database
    successfully created by this invocation is eligible for automatic cleanup.
    """
    maintenance = _service_conninfo(restore_service)
    backup = Path(backup).resolve()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1:
        raise ValueError("Unsupported backup manifest version")
    archive = backup / "database.dump"
    if _checksum(archive) != manifest["sha256"]:
        raise ValueError("Backup checksum mismatch; no restore was attempted")
    reference = manifest["reference"]
    if not reference or not reference["rows"]:
        raise ValueError("Create a backup with --match-id to verify stored history")

    database = "agentic_restore_" + uuid4().hex
    target = _service_conninfo(restore_service, database)
    created = False
    print(f"Restore verification database: {database}", flush=True)
    try:
        _run(["createdb", "--no-password", "--maintenance-db", maintenance,
              "--template=template0", database])
        created = True
        _run(["pg_restore", "--no-password", "--exit-on-error", "--no-owner",
              "--no-privileges", "--dbname", target, str(archive)])
        restored = _reference_rows(_history(reference["match_id"], target))
        by_identity = {(row["outcome_id"], row["field"]): row for row in restored}
        for expected in reference["rows"]:
            identity = (expected["outcome_id"], expected["field"])
            if by_identity.get(identity) != expected:
                raise ValueError(f"Restored history differs for outcome/field {identity}")
        return {"database": database, "matched_rows": len(reference["rows"]),
                "kept": keep_database}
    finally:
        if created and not keep_database:
            _run(["dropdb", "--no-password", "--maintenance-db", maintenance, database])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="publish a complete PostgreSQL backup")
    backup.add_argument("--directory", required=True)
    backup.add_argument("--source-service", required=True)
    backup.add_argument("--match-id", type=UUID)
    verify = commands.add_parser("verify", help="restore into a new isolated verification database")
    verify.add_argument("backup")
    verify.add_argument("--restore-service", required=True)
    verify.add_argument("--keep-database", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "backup":
            path = create_backup(arguments.directory, source_service=arguments.source_service,
                                 match_id=arguments.match_id)
            print(f"Backup created: {path}")
        else:
            result = verify_backup(arguments.backup, restore_service=arguments.restore_service,
                                   keep_database=arguments.keep_database)
            print(f"Verified {result['matched_rows']} history rows in {result['database']}; "
                  f"database {'kept' if result['kept'] else 'removed'}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Backup operation failed: {error}\n")


if __name__ == "__main__":
    main()
