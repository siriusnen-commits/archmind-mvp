from __future__ import annotations

from pathlib import Path


def test_offline_install_scripts_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    make_wh = repo_root / "scripts" / "make_wheelhouse.sh"
    verify = repo_root / "scripts" / "offline_install_verify.sh"
    assert make_wh.exists()
    assert verify.exists()
    assert make_wh.stat().st_mode & 0o111
    assert verify.stat().st_mode & 0o111
