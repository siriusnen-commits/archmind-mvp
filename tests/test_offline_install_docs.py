from __future__ import annotations

from pathlib import Path


def test_offline_install_scripts_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "scripts" / "wheelhouse_build.sh").exists()
    assert (repo_root / "scripts" / "offline_install.sh").exists()
