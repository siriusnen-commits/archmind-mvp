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


def test_offline_install_help_mentions_online(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    make_wh = repo_root / "scripts" / "make_wheelhouse.sh"
    verify = repo_root / "scripts" / "offline_install_verify.sh"

    make_help = make_wh.read_text(encoding="utf-8")
    verify_help = verify.read_text(encoding="utf-8")

    assert "online" in make_help.lower()
    assert "offline" in verify_help.lower() or "online" in verify_help.lower()
