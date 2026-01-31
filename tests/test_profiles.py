from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from archmind.cli import build_parser, main


def test_profile_option_in_help() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
    )
    run_help = subparsers.choices["run"].format_help()
    assert "--profile" in run_help


def test_generic_shell_runs_commands_in_order(tmp_path: Path) -> None:
    py = shlex.quote(sys.executable)
    cmd1 = f'{py} -c "from pathlib import Path; Path(\\"order.txt\\").open(\\"a\\").write(\\"1\\\\n\\")"'
    cmd2 = f'{py} -c "from pathlib import Path; Path(\\"order.txt\\").open(\\"a\\").write(\\"2\\\\n\\")"'

    exit_code = main(
        [
            "run",
            "--path",
            str(tmp_path),
            "--profile",
            "generic",
            "--cmd",
            cmd1,
            "--cmd",
            cmd2,
        ]
    )
    assert exit_code == 0

    order_path = tmp_path / "order.txt"
    assert order_path.exists()
    assert order_path.read_text(encoding="utf-8") == "1\n2\n"


def test_node_vite_missing_package_json_skips(tmp_path: Path) -> None:
    exit_code = main(["run", "--path", str(tmp_path), "--profile", "node-vite"])
    assert exit_code == 0

    result_path = tmp_path / ".archmind" / "result.json"
    result_txt = tmp_path / ".archmind" / "result.txt"
    assert result_path.exists()
    assert result_txt.exists()

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "SKIP"
    assert payload["profile"] == "node-vite"

    lines = result_txt.read_text(encoding="utf-8").splitlines()
    assert 3 <= len(lines) <= 5
