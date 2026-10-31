#!/usr/bin/env python3
"""hooklib: 各 hook スクリプトが共有する処理 (標準ライブラリのみ)。

- 状態ディレクトリ ~/.cline-harness/ (ログ、コンテキスト推定、skill 読み込み記録)
- コンテキスト使用量の推定と段階 (ok / warn / handoff / hard)
- 推定は hook が受け取る tool の入出力サイズの積算であり、実際のコンテキストより小さく出る傾向がある
  (モデルの出力・システムプロンプトは見えない)。baseline と factor で補正し、
  Cline の表示と見比べて ~/.cline-harness/context.json で調整する。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".cline-harness"
CTX_DIR = STATE_DIR / "ctx"

DEFAULT_CTX = {
    "window_tokens": 200000,   # 使用モデルのコンテキスト長に合わせる
    "baseline_tokens": 25000,  # システムプロンプト + rules + skill 一覧の概算
    "factor": 1.25,            # モデルの出力など hook から見えない分の補正
    "ascii_chars_per_token": 3.5,
    "nonascii_chars_per_token": 1.3,
    "warn_pct": 50,
    "handoff_pct": 65,
    "hard_pct": 80,
}
LEVELS = ("ok", "warn", "handoff", "hard")


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


def log(name: str, text: str) -> None:
    try:
        STATE_DIR.mkdir(exist_ok=True)
        with open(STATE_DIR / name, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {text}\n")
    except Exception:
        pass


def debug_on() -> bool:
    return (STATE_DIR / "debug").exists()


def ctx_config() -> dict:
    cfg = dict(DEFAULT_CTX)
    p = STATE_DIR / "context.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def est_tokens(s: str, cfg: dict | None = None) -> int:
    cfg = cfg or ctx_config()
    ascii_n = sum(1 for c in s if ord(c) < 128)
    non = len(s) - ascii_n
    return int(ascii_n / cfg["ascii_chars_per_token"] + non / cfg["nonascii_chars_per_token"])


def _safe(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", task_id or "unknown")


def ctx_load(task_id: str) -> dict:
    p = CTX_DIR / f"{_safe(task_id)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tokens": 0, "level": "ok", "skills": [], "compactions": 0}


def ctx_save(task_id: str, st: dict) -> None:
    try:
        CTX_DIR.mkdir(parents=True, exist_ok=True)
        (CTX_DIR / f"{_safe(task_id)}.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def ctx_pct(st: dict, cfg: dict | None = None) -> float:
    cfg = cfg or ctx_config()
    used = (cfg["baseline_tokens"] + st.get("tokens", 0)) * cfg["factor"]
    return round(100.0 * used / cfg["window_tokens"], 1)


def ctx_level(pct: float, cfg: dict | None = None) -> str:
    cfg = cfg or ctx_config()
    if pct >= cfg["hard_pct"]:
        return "hard"
    if pct >= cfg["handoff_pct"]:
        return "handoff"
    if pct >= cfg["warn_pct"]:
        return "warn"
    return "ok"


def ctx_add(task_id: str, tokens: int) -> tuple[dict, str | None]:
    """積算して状態を保存し、段階が上がったときだけその段階名を返す。"""
    cfg = ctx_config()
    st = ctx_load(task_id)
    st["tokens"] = st.get("tokens", 0) + tokens
    level = ctx_level(ctx_pct(st, cfg), cfg)
    crossed = level if LEVELS.index(level) > LEVELS.index(st.get("level", "ok")) else None
    st["level"] = level
    ctx_save(task_id, st)
    return st, crossed


def skill_mark(task_id: str, name: str) -> None:
    st = ctx_load(task_id)
    if name not in st.setdefault("skills", []):
        st["skills"].append(name)
        ctx_save(task_id, st)


def skill_loaded(task_id: str, name: str) -> bool:
    return name in ctx_load(task_id).get("skills", [])
