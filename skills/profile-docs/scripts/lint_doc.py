#!/usr/bin/env python3
"""lint_doc.py: ドキュメント (Markdown) の機械検証。標準ライブラリのみ。

使い方:
  python3 lint_doc.py <file.md> [--json] [--strict]

検査内容: プレースホルダ残留・未閉じフェンス・和英スペース・絵文字
終了コード: エラーが 1 件以上 → 1、なければ 0。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent.parent / "shared"
sys.path.insert(0, str(_SHARED))
from lint_utils import (  # noqa: E402
    EMOJI_RANGES,
    TEXT_SYMBOLS,
    check_ja_en_spacing,
    is_emoji,
    mask,
    scan,
)

DEFAULT_EMOJI_ALLOWLIST = ["✅", "❌", "⚠", "💡", "📌", "📊", "🔍", "📝", "🔧", "🚀", "🔒", "💰", "⏱", "🧩"]
DEFAULT_EMOJI_MAX_KINDS = 15


def lint(path: Path, emoji_allowlist: list[str] | None = None,
         emoji_max_kinds: int = DEFAULT_EMOJI_MAX_KINDS) -> list[tuple[str, str, int | None, str]]:
    """Markdown ドキュメントを lint して issue リストを返す。

    Args:
        path: 検査対象の Markdown ファイルパス。
        emoji_allowlist: 許可する絵文字のリスト。None の場合はデフォルトを使用。
        emoji_max_kinds: 許可する絵文字の種類数の上限。

    Returns:
        (severity, rule_id, line_1indexed_or_None, message) のリスト。
    """
    allow = set(emoji_allowlist or DEFAULT_EMOJI_ALLOWLIST)
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    kinds, _ = scan(lines)
    issues: list[tuple[str, str, int | None, str]] = []

    def E(rule: str, i: int | None, msg: str) -> None:
        issues.append(("ERROR", rule, None if i is None else i + 1, msg))

    def W(rule: str, i: int | None, msg: str) -> None:
        issues.append(("WARN", rule, None if i is None else i + 1, msg))

    # STRUCT-0: プレースホルダ残留・未閉じフェンス
    for i, line in enumerate(lines):
        if "{{" in line:
            E("STRUCT-0", i, "未記入のプレースホルダ {{...}} が残っています")
    _, fences = scan(lines)
    for f in fences:
        if f.get("unclosed"):
            E("STRUCT-0", f["start"], "コードフェンスが閉じられていません")

    # SPACE-1: 和英スペース
    for i, msg in check_ja_en_spacing(lines, kinds):
        E("SPACE-1", i, msg)

    # EMOJI-1, EMOJI-2: 絵文字
    emoji_kinds: dict[str, int] = {}
    for i, line in enumerate(lines):
        if kinds[i] != "text":
            continue
        for ch in mask(line):
            if ch in "️‍":
                continue
            if is_emoji(ch):
                emoji_kinds.setdefault(ch, i)
    if len(emoji_kinds) > emoji_max_kinds:
        E("EMOJI-1", None, f"絵文字の種類が多すぎます ({len(emoji_kinds)} 種 > {emoji_max_kinds})")
    for ch, i in emoji_kinds.items():
        if ch not in allow:
            E("EMOJI-2", i, f"許可リスト外の絵文字 '{ch}'")

    return issues


def main() -> int:
    """CLI エントリポイント。

    Returns:
        終了コード (0: エラーなし, 1: エラーあり)。
    """
    ap = argparse.ArgumentParser(description="Markdown ドキュメントの lint")
    ap.add_argument("file", help="検査対象の Markdown ファイル")
    ap.add_argument("--json", action="store_true", help="JSON 形式で出力")
    ap.add_argument("--strict", action="store_true", help="警告もエラー扱い")
    a = ap.parse_args()

    issues = sorted(lint(Path(a.file)), key=lambda x: (x[2] is None, x[2] or 0, x[1]))
    errors = [x for x in issues if x[0] == "ERROR"]
    warns = [x for x in issues if x[0] == "WARN"]

    if a.json:
        print(json.dumps(
            [{"severity": s, "rule": r, "line": ln, "message": m} for s, r, ln, m in issues],
            ensure_ascii=False, indent=2,
        ))
    else:
        for s, r, ln, m in issues:
            print(f"{s:<5} [{r}] {'L' + str(ln) if ln else '-':<5} {m}")
        print(f"\n{len(errors)} errors, {len(warns)} warnings")

    return 1 if errors or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
