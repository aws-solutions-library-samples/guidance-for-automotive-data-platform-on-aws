"""Tests for secret-scan.py"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCANNER = Path(__file__).parent / "secret-scan.py"


def make_config(tmp_path, extra_patterns=None, extra_strings=None, scan_exclude=None):
    """Write a minimal YAML config and return its path."""
    patterns = {
        "aws_account_id": {
            "regex": r"\b195026230833\b",
            "severity": "critical",
            "description": "Staging AWS account ID",
        },
        "warning_pattern": {
            "regex": r"\bSECRET_WARN\b",
            "severity": "warning",
            "description": "Warning-level test pattern",
        },
    }
    if extra_patterns:
        patterns.update(extra_patterns)

    strings = ["MMT"]
    if extra_strings:
        strings.extend(extra_strings)

    excludes = list(scan_exclude or [])

    import yaml
    cfg = {
        "forbidden_patterns": patterns,
        "forbidden_strings": strings,
        "scan_exclude": excludes,
    }
    config_path = tmp_path / "scan-config.yml"
    config_path.write_text(yaml.dump(cfg))
    return config_path


def run_scanner(*args):
    """Run the scanner and return (returncode, parsed_json_or_None, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCANNER)] + list(args),
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        data = None
    return result.returncode, data, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clean_tree(tmp_path):
    """Empty/scrubbed tree returns clean=true, exit 0."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("Hello world\n")
    config = make_config(tmp_path)

    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 0
    assert data is not None
    assert data["clean"] is True
    assert data["findings"] == []


def test_dirty_tree_account_id(tmp_path):
    """File containing the account ID triggers a critical finding."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "config.py").write_text("ACCOUNT = '195026230833'\n")
    config = make_config(tmp_path)

    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 1
    assert data is not None
    assert data["clean"] is False
    assert any(f["pattern_name"] == "aws_account_id" for f in data["findings"])


def test_dirty_tree_forbidden_string(tmp_path):
    """File containing 'MMT' triggers a critical finding."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "labels.ts").write_text("const project = 'MMT internal codename';\n")
    config = make_config(tmp_path)

    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 1
    assert data is not None
    assert data["clean"] is False
    assert any("MMT" in f["pattern_name"] for f in data["findings"])


def test_allow_finding_suppresses(tmp_path):
    """--allow-finding suppresses the specific match; result is clean."""
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "config.py"
    target.write_text("ACCOUNT = '195026230833'\n")
    config = make_config(tmp_path)

    # Determine the relative path the scanner will use
    rel = str(target.relative_to(root))
    allow_arg = f"aws_account_id:{rel}:1"

    rc, data, _ = run_scanner(
        "--config", str(config), "--root", str(root),
        "--allow-finding", allow_arg,
    )
    assert rc == 0
    assert data is not None
    assert data["clean"] is True
    assert data["findings"] == []


def test_strict_mode_escalates(tmp_path):
    """Warning-level pattern exits 0 normally but exits 1 with --strict."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "note.txt").write_text("This is a SECRET_WARN value\n")
    config = make_config(tmp_path)

    # Without --strict: exit 0, clean=True
    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 0
    assert data["clean"] is True

    # With --strict: exit 1, clean=False
    rc2, data2, _ = run_scanner("--config", str(config), "--root", str(root), "--strict")
    assert rc2 == 1
    assert data2["clean"] is False


def test_scan_exclude_skips(tmp_path):
    """Files matching scan_exclude glob are not scanned."""
    root = tmp_path / "repo"
    root.mkdir()
    node_modules = root / "node_modules"
    node_modules.mkdir()
    (node_modules / "pkg.js").write_text("var x = '195026230833';\n")
    config = make_config(tmp_path, scan_exclude=["**/node_modules/**"])

    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 0
    assert data["clean"] is True
    assert data["findings"] == []


def test_binary_files_skipped(tmp_path):
    """Binary file (contains NULL byte) is not scanned."""
    root = tmp_path / "repo"
    root.mkdir()
    binary = root / "image.bin"
    binary.write_bytes(b"195026230833\x00binary data here")
    config = make_config(tmp_path)

    rc, data, _ = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 0
    assert data["clean"] is True
    assert data["findings"] == []


def test_large_files_skipped(tmp_path):
    """File >5MB is skipped with a log message (not a finding)."""
    root = tmp_path / "repo"
    root.mkdir()
    large = root / "bundle.cjs"
    # Write just over 5MB
    chunk = b"195026230833 " * 1000
    with open(large, "wb") as f:
        while f.tell() < 5 * 1024 * 1024 + 1:
            f.write(chunk)
    config = make_config(tmp_path)

    rc, data, stderr = run_scanner("--config", str(config), "--root", str(root))
    assert rc == 0
    assert data["clean"] is True
    assert data["findings"] == []
    assert "skipping large file" in stderr
