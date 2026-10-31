#!/usr/bin/env python3
"""lint_utils.py: Markdown lint スクリプト群が共有するユーティリティ。標準ライブラリのみ。

lint_report.py / lint_doc.py / lint_adr.py から import して使う。
"""
from __future__ import annotations

import re
import unicodedata
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# 正規表現定数
# ---------------------------------------------------------------------------

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
LINK_DEST = re.compile(r"(\]\()([^)\s]*(?:\s+\"[^\"]*\")?)(\))")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")

# 和英間スペース検査用
CJK = r"々〇ぁ-ゖゝ-ゟァ-ヺー-ヿ㐀-䶿一-鿿豈-﫿"
SP1 = re.compile(f"([{CJK}])([A-Za-z0-9])")
SP2 = re.compile(f"([A-Za-z0-9])([{CJK}])")

# 絵文字
EMOJI_RANGES = [
    (0x1F1E6, 0x1F1FF), (0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
    (0x2B1B, 0x2B1C), (0x231A, 0x231B), (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x2934, 0x2935),
    (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297), (0x3299, 0x3299),
]
TEXT_SYMBOLS = set("★☆☐✓✗✘✔✖•▪▫◆◇○●◎")  # 文字記号として扱い絵文字に数えない
BOX_CORNERS = set("┌┐┘╔╗╚╝┬┴┼╠╣╦╩╬")
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


# ---------------------------------------------------------------------------
# Markdown パース
# ---------------------------------------------------------------------------

def scan(lines: list[str]) -> tuple[list[str], list[dict]]:
    """Markdown 行リストをスキャンしてコードフェンスを抽出する。

    Args:
        lines: Markdown テキストを行に分割したリスト。

    Returns:
        (kinds, fences) のタプル。
        kinds は各行の種類 ("text" / "open" / "code" / "close")。
        fences はフェンス情報の辞書リスト (start, end, marker, info, lines)。
    """
    kinds, fences, cur = [], [], None
    for i, line in enumerate(lines):
        m = FENCE_RE.match(line)
        if cur is None:
            if m:
                cur = {"start": i, "marker": m.group(1), "info": m.group(2).strip(), "lines": []}
                kinds.append("open")
            else:
                kinds.append("text")
        else:
            if (m and m.group(1)[0] == cur["marker"][0]
                    and len(m.group(1)) >= len(cur["marker"])
                    and not m.group(2).strip()):
                cur["end"] = i
                fences.append(cur)
                cur = None
                kinds.append("close")
            else:
                cur["lines"].append(line)
                kinds.append("code")
    if cur:
        cur["end"] = len(lines) - 1
        cur["unclosed"] = True
        fences.append(cur)
    return kinds, fences


# ---------------------------------------------------------------------------
# テキスト加工
# ---------------------------------------------------------------------------

def mask(line: str) -> str:
    """行内のインラインコード・URL・HTML タグをマスクして和英スペース検査の誤検知を防ぐ。

    Args:
        line: マスク対象の行文字列。

    Returns:
        マスク済みの行文字列。インラインコードは 'A' の連続、URL/HTML は \\x00 の連続に置換。
    """
    line = INLINE_CODE.sub(lambda m: "A" * len(m.group(0)), line)
    line = LINK_DEST.sub(lambda m: m.group(1) + "\x00" * len(m.group(2)) + m.group(3), line)
    line = URL_RE.sub(lambda m: "\x00" * len(m.group(0)), line)
    line = HTML_TAG.sub(lambda m: "\x00" * len(m.group(0)), line)
    return line


def norm_url(u: str) -> str:
    """URL を正規化する (スキーム・ホスト小文字化、末尾スラッシュ除去、フラグメント除去)。

    Args:
        u: 正規化対象の URL 文字列。

    Returns:
        正規化済みの URL 文字列。
    """
    u = u.strip().strip("<>")
    p = urllib.parse.urlsplit(u)
    path = p.path.rstrip("/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def norm_text(s: str) -> str:
    """テキストを NFKC 正規化し、異体字・ゼロ幅文字・空白を除去する。引用照合用。

    Args:
        s: 正規化対象の文字列。

    Returns:
        正規化済みの文字列。
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------------------
# 和英スペース検査
# ---------------------------------------------------------------------------

def check_ja_en_spacing(
    lines: list[str],
    kinds: list[str],
    skip_lines: set[int] | None = None,
) -> list[tuple[int, str]]:
    """日本語と英数字の間に半角スペースがない箇所を検出する。

    Args:
        lines: Markdown テキストの行リスト。
        kinds: scan() が返す各行の種別リスト ("text" / "open" / "code" / "close")。
        skip_lines: スキップする行番号のセット (verbatim 行など)。

    Returns:
        (行番号 0-indexed, メッセージ) のリスト。
    """
    skip = skip_lines or set()
    issues = []
    for i, line in enumerate(lines):
        if kinds[i] != "text" or i in skip:
            continue
        masked = mask(line)
        for pat, label in ((SP1, "日本語→英数字"), (SP2, "英数字→日本語")):
            for m in pat.finditer(masked):
                issues.append((i, f"和英スペース ({label}): 「{line[max(0,m.start()-2):m.end()+2]}」"))
    return issues


# ---------------------------------------------------------------------------
# 絵文字判定
# ---------------------------------------------------------------------------

def is_emoji(ch: str) -> bool:
    """文字が絵文字かどうかを判定する。

    Args:
        ch: 判定対象の 1 文字。

    Returns:
        絵文字なら True、そうでなければ False。
    """
    if ch in TEXT_SYMBOLS:
        return False
    cp = ord(ch)
    if 0x1F3FB <= cp <= 0x1F3FF:  # 肌色修飾子
        return False
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)
