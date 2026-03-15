from __future__ import annotations

import re
from typing import Any


KO_PAT = re.compile(r"[가-힣]")
JA_KANA_PAT = re.compile(r"[\u3040-\u30ff]")


def _detect_language(text: str) -> str:
    if KO_PAT.search(text):
        return "ko"
    if JA_KANA_PAT.search(text):
        return "ja"
    if any(token in text for token in ("文書", "家計簿", "管理ツール", "管理")):
        return "ja"
    return "en"


def _replace_tokens(text: str, mapping: list[tuple[str, str]]) -> str:
    out = text
    for src, dst in mapping:
        out = re.sub(src, f" {dst} ", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def normalize_idea(idea: str) -> dict[str, Any]:
    original = str(idea or "").strip()
    if not original:
        return {"original": "", "normalized": "", "language": "en"}

    language = _detect_language(original)
    normalized = original

    if language == "ko":
        ko_map: list[tuple[str, str]] = [
            (r"협업용", "team"),
            (r"작업", "task"),
            (r"협업", "team"),
            (r"가계부", "expenses"),
            (r"문서", "document"),
            (r"업로드", "upload"),
            (r"관리", "management"),
            (r"대시보드", "dashboard"),
            (r"로그인", "login"),
            (r"사용자", "user"),
            (r"첨부", "file upload"),
            (r"배치", "batch"),
            (r"백그라운드", "worker"),
        ]
        normalized = _replace_tokens(normalized, ko_map)
    elif language == "ja":
        ja_map: list[tuple[str, str]] = [
            (r"タスク", "task"),
            (r"チーム", "team"),
            (r"家計簿", "expenses"),
            (r"文書", "document"),
            (r"アップロード", "upload"),
            (r"管理", "admin"),
            (r"ダッシュボード", "dashboard"),
            (r"ログイン", "login"),
            (r"ユーザー", "user"),
            (r"添付", "file upload"),
            (r"バッチ", "batch"),
            (r"バックグラウンド", "worker"),
        ]
        normalized = _replace_tokens(normalized, ja_map)
    else:
        normalized = re.sub(r"\s+", " ", normalized).strip()

    return {
        "original": original,
        "normalized": normalized,
        "language": language,
    }
