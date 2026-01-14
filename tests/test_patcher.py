from __future__ import annotations

from pathlib import Path

import pytest

from archmind.patcher import apply_unified_diff


def test_patcher_blocks_path_traversal(tmp_path: Path) -> None:
    diff = (
        "--- a/../evil.py\n"
        "+++ b/../evil.py\n"
        "@@ -0,0 +1 @@\n"
        "+print('nope')\n"
    )
    with pytest.raises(ValueError):
        apply_unified_diff(tmp_path, diff)
