from __future__ import annotations

from pathlib import Path

from archmind.cli import main


def _write_project_with_missing_import(root: Path) -> None:
    root.joinpath("foo.py").write_text(
        "def make_name():\n"
        "    return Path(\"hello.txt\").name\n",
        encoding="utf-8",
    )
    root.joinpath("test_foo.py").write_text(
        "from foo import make_name\n\n"
        "def test_make_name():\n"
        "    assert make_name() == \"hello.txt\"\n",
        encoding="utf-8",
    )


def test_run_fix_dry_run_outputs_diff(tmp_path: Path, capsys) -> None:
    _write_project_with_missing_import(tmp_path)

    exit_code = main(["run", "--path", str(tmp_path), "--fix", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "--- a/foo.py" in captured.out
    assert "+++ b/foo.py" in captured.out


def test_run_fix_applies_patch_and_passes(tmp_path: Path) -> None:
    _write_project_with_missing_import(tmp_path)

    exit_code = main(["run", "--path", str(tmp_path), "--fix", "--max-iter", "2"])
    assert exit_code == 0

    updated = tmp_path.joinpath("foo.py").read_text(encoding="utf-8")
    assert "from pathlib import Path" in updated
