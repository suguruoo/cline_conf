#!/usr/bin/env python3
"""lint_adr.py: ADR (Architecture Decision Record) の必須フィールド検証。標準ライブラリのみ。

使い方:
  python3 lint_adr.py <adr-NNN-title.md> [--json] [--strict]

検査内容: h1 形式・ステータス・必須セクション (コンテキスト・決定内容・結果)・和英スペース
終了コード: エラーが 1 件以上 → 1、なければ 0。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent.parent / "shared"
sys.path.insert(0, str(_SHARED))
from lint_utils import check_ja_en_spacing, scan  # noqa: E402

VALID_STATUSES = {"提案中", "承認済み", "非推奨", "置換済み"}
REQUIRED_H2 = ["ステータス", "コンテキスト", "決定内容", "結果"]
ADR_TITLE_RE = re.compile(r"^# ADR-(\d{3}): \S")


def lint(path: Path) -> list[tuple[str, str, int | None, str]]:
    """ADR ファイルを lint して issue リストを返す。

    Args:
        path: 検査対象の ADR Markdown ファイルパス。

    Returns:
        (severity, rule_id, line_1indexed_or_None, message) のリスト。
    """
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    kinds, _ = scan(lines)
    issues: list[tuple[str, str, int | None, str]] = []

    def E(rule: str, i: int | None, msg: str) -> None:
        issues.append(("ERROR", rule, None if i is None else i + 1, msg))

    def W(rule: str, i: int | None, msg: str) -> None:
        issues.append(("WARN", rule, None if i is None else i + 1, msg))

    # STRUCT-0: プレースホルダ残留
    for i, line in enumerate(lines):
        if "{{" in line:
            E("STRUCT-0", i, "未記入のプレースホルダ {{...}} が残っています")

    # ADR-1: h1 の形式 (# ADR-NNN: タイトル)
    text_lines = [l for l, k in zip(lines, kinds) if k == "text"]
    h1s = [(i, l) for i, (l, k) in enumerate(zip(lines, kinds)) if k == "text" and l.startswith("# ")]
    if not h1s:
        E("ADR-1", None, "h1 (# ADR-NNN: タイトル) が見つかりません")
    else:
        i, h1 = h1s[0]
        if not ADR_TITLE_RE.match(h1):
            E("ADR-1", i, f"h1 は '# ADR-NNN: タイトル' 形式にする (NNN は 3 桁): '{h1}'")

    # ADR-2: 必須 h2 セクションの存在確認
    h2s = {l[3:].strip(): i for i, (l, k) in enumerate(zip(lines, kinds))
           if k == "text" and l.startswith("## ")}
    for section in REQUIRED_H2:
        if section not in h2s:
            E("ADR-2", None, f"必須セクション '## {section}' がありません")

    # ADR-3: ステータスの値が有効か
    if "ステータス" in h2s:
        si = h2s["ステータス"]
        # ステータスセクション直後のテキスト行を探す
        for j in range(si + 1, len(lines)):
            if kinds[j] != "text":
                continue
            val = lines[j].strip().lstrip("-").strip()
            if not val:
                continue
            if val not in VALID_STATUSES:
                E("ADR-3", j, f"ステータスは {'/'.join(sorted(VALID_STATUSES))} のいずれかにする: '{val}'")
            break

    # ADR-4: 必須セクションが空でないか
    for section in ["コンテキスト", "決定内容", "結果"]:
        if section not in h2s:
            continue
        si = h2s[section]
        next_h2 = next(
            (j for j in range(si + 1, len(lines)) if kinds[j] == "text" and lines[j].startswith("## ")),
            len(lines),
        )
        body = " ".join(lines[si + 1:next_h2]).strip()
        if not body:
            E("ADR-4", si, f"'## {section}' セクションが空です")

    # SPACE-1: 和英スペース (コードフェンス外)
    for i, msg in check_ja_en_spacing(lines, kinds):
        W("SPACE-1", i, msg)

    return issues


def main() -> int:
    """CLI エントリポイント。

    Returns:
        終了コード (0: エラーなし, 1: エラーあり)。
    """
    ap = argparse.ArgumentParser(description="ADR (Architecture Decision Record) の lint")
    ap.add_argument("file", help="検査対象の ADR Markdown ファイル")
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
