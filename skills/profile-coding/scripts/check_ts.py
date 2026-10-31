#!/usr/bin/env python3
"""check_ts.py: TypeScript コーディング規約の機械検査 (ESLint + Prettier)。標準ライブラリのみ。

使い方:
  python3 check_ts.py [PATH...] [--root DIR] [--json]

npx が利用可能な場合は ESLint と Prettier を実行する。
利用不可な場合はスキップして警告を出す。
終了コード: エラーが 1 件以上 → 1、なければ 0。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_ts_files(paths: list[Path], root: Path) -> list[Path]:
    """指定パスから TypeScript ファイルを列挙する。

    Args:
        paths: 検索対象のパスリスト (ファイルまたはディレクトリ)。
        root: プロジェクトルートディレクトリ。

    Returns:
        見つかった .ts / .tsx ファイルのリスト。
    """
    result = []
    for p in paths:
        p = root / p if not p.is_absolute() else p
        if p.is_file() and p.suffix in (".ts", ".tsx"):
            result.append(p)
        elif p.is_dir():
            result.extend(p.rglob("*.ts"))
            result.extend(p.rglob("*.tsx"))
    return result


def run_eslint(root: Path, files: list[Path]) -> list[tuple[str, str, int | None, str]]:
    """ESLint を実行して issue を返す。

    Args:
        root: プロジェクトルートディレクトリ (npx 実行場所)。
        files: 検査対象ファイルのリスト。

    Returns:
        (severity, rule_id, line_or_None, message) のリスト。
    """
    issues = []
    rel_files = [str(f.relative_to(root)) for f in files]
    try:
        cp = subprocess.run(
            ["npx", "--yes", "eslint", "--format", "json", *rel_files],
            capture_output=True, text=True, cwd=str(root), timeout=120,
        )
    except subprocess.TimeoutExpired:
        return [("WARN", "TS-ESLINT", None, "ESLint がタイムアウトしました")]
    except FileNotFoundError:
        return [("WARN", "TS-ESLINT", None, "npx が見つかりません。Node.js をインストールしてください")]

    if not cp.stdout.strip():
        if cp.returncode != 0:
            return [("WARN", "TS-ESLINT", None, f"ESLint の出力が空です (exit {cp.returncode})")]
        return []

    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError:
        return [("WARN", "TS-ESLINT", None, f"ESLint の JSON 出力をパースできませんでした: {cp.stdout[:200]}")]

    for file_result in data:
        for msg in file_result.get("messages", []):
            sev = "ERROR" if msg.get("severity") == 2 else "WARN"
            rule = msg.get("ruleId") or "TS-ESLINT"
            line = msg.get("line")
            text = f"{Path(file_result['filePath']).name}: {msg.get('message', '')}"
            issues.append((sev, rule, line, text))
    return issues


def run_prettier(root: Path, files: list[Path]) -> list[tuple[str, str, int | None, str]]:
    """Prettier のフォーマットチェックを実行して issue を返す。

    Args:
        root: プロジェクトルートディレクトリ (npx 実行場所)。
        files: 検査対象ファイルのリスト。

    Returns:
        (severity, rule_id, line_or_None, message) のリスト。
    """
    rel_files = [str(f.relative_to(root)) for f in files]
    try:
        cp = subprocess.run(
            ["npx", "--yes", "prettier", "--check", *rel_files],
            capture_output=True, text=True, cwd=str(root), timeout=120,
        )
    except subprocess.TimeoutExpired:
        return [("WARN", "TS-PRETTIER", None, "Prettier がタイムアウトしました")]
    except FileNotFoundError:
        return []  # ESLint 側で npx なしを報告済み

    issues = []
    if cp.returncode != 0:
        for line in (cp.stdout + cp.stderr).splitlines():
            line = line.strip()
            if line and not line.startswith("Checking"):
                issues.append(("ERROR", "TS-PRETTIER", None, f"フォーマット違反: {line}"))
    return issues


def main() -> int:
    """CLI エントリポイント。

    Returns:
        終了コード (0: エラーなし, 1: エラーあり)。
    """
    ap = argparse.ArgumentParser(description="TypeScript コードの ESLint + Prettier 検査")
    ap.add_argument("paths", nargs="*", default=["."], help="検査対象のパス (デフォルト: .)")
    ap.add_argument("--root", default=".", help="プロジェクトルートディレクトリ")
    ap.add_argument("--json", action="store_true", help="JSON 形式で出力")
    ap.add_argument("--strict", action="store_true", help="警告もエラー扱い")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    input_paths = [Path(p) for p in a.paths]
    files = find_ts_files(input_paths, root)

    if not files:
        if not a.json:
            print("TypeScript ファイルが見つかりません")
        return 0

    if shutil.which("npx") is None:
        msg = "npx が見つかりません。Node.js をインストールしてください (TypeScript 検査をスキップ)"
        if a.json:
            print(json.dumps([{"severity": "WARN", "rule": "TS-SKIP", "line": None, "message": msg}],
                             ensure_ascii=False))
        else:
            print(f"WARN  [TS-SKIP] -     {msg}")
        return 0

    issues = run_eslint(root, files) + run_prettier(root, files)
    issues = sorted(issues, key=lambda x: (x[2] is None, x[2] or 0, x[1]))
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
