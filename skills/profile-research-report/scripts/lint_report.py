#!/usr/bin/env python3
"""lint_report.py: リサーチレポート (GitHub Markdown) の機械検証。標準ライブラリのみ。

使い方:
  python3 lint_report.py deliverables/report.md --task-dir . [--offline] [--no-mermaid] [--json] [--strict]

--task-dir を渡すと <task-dir>/ledger.json と sources/ を使って
  一次/二次の判定、原文引用の照合 (QUOTE)、未登録 URL の検出 (LEDGER) を行う。
終了コード: エラーが 1 件以上 → 1、なければ 0。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 共通ユーティリティを import
_SHARED = Path(__file__).resolve().parent.parent.parent / "shared"
sys.path.insert(0, str(_SHARED))
from lint_utils import (  # noqa: E402
    BOX_CORNERS,
    EMOJI_RANGES,
    FENCE_RE,
    IMG_RE,
    SEP_RE,
    SP1,
    SP2,
    TEXT_SYMBOLS,
    is_emoji,
    mask,
    norm_text,
    norm_url,
    scan,
)

HERE = Path(__file__).resolve().parent
DEFAULT_CFG = {
    "emoji_allowlist": ["✅", "❌", "⚠", "💡", "📌", "📊", "🔍", "📝", "🔧", "🚀", "🔒", "💰", "⏱", "🧩"],
    "emoji_max_kinds": 15,
    "uncertainty_keywords": ["不確実", "限界", "留意"],
    "secondary_marker": "（二次）",
    "max_quote_chars": 1500,
}

CITE_CLUSTER = re.compile(r"(?:\[\d+\](?![(:])(?:（二次）)?)+")
CITE_ONE = re.compile(r"\[(\d+)\](?![(:])(（二次）)?")


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    p = HERE / "config.json"
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def cell_norm(s) -> str:
    s = str(s)
    s = re.sub(r"\[(\d+)\](（二次）)?", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    for t in ("**", "__", "`", "~~"):
        s = s.replace(t, "")
    import unicodedata
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


class Linter:
    def __init__(self, path: Path, cfg: dict, task_dir: Path | None, ledger_path: Path | None,
                 offline: bool, mermaid: bool) -> None:
        self.path = path
        self.cfg = cfg
        self.offline = offline
        self.mermaid = mermaid
        self.lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        self.kinds, self.fences = scan(self.lines)
        self.issues: list[tuple[str, str, int | None, str]] = []
        self.verbatim: set[int] = set()
        self.h2: list[tuple[int, str]] = []
        self.ref_range: tuple[int, int] | None = None
        self.refs: dict[int, dict] = {}
        self.clusters: list[tuple[int, list[tuple[int, bool]]]] = []
        self.task_dir = task_dir
        self.ledger: dict[str, dict] | None = None
        lp = ledger_path or (task_dir / "ledger.json" if task_dir else None)
        if lp and lp.exists():
            data = json.loads(lp.read_text(encoding="utf-8"))
            self.ledger = {norm_url(s["url"]): s for s in data.get("sources", [])}
            self.ledger_dir = lp.parent
        elif lp:
            self.W("LEDGER-0", None, f"台帳が見つかりません: {lp}")

    # ---- issue helpers
    def E(self, rule, i, msg):
        self.issues.append(("ERROR", rule, None if i is None else i + 1, msg))

    def W(self, rule, i, msg):
        self.issues.append(("WARN", rule, None if i is None else i + 1, msg))

    def text_lines(self, skip_verbatim=False, skip_refs=False):
        for i, l in enumerate(self.lines):
            if self.kinds[i] != "text":
                continue
            if skip_verbatim and i in self.verbatim:
                continue
            if skip_refs and self.ref_range and self.ref_range[0] <= i < self.ref_range[1]:
                continue
            yield i, l

    # ---- checks
    def run(self):
        for i, l in enumerate(self.lines):
            if "{{" in l:
                self.E("STRUCT-0", i, "未記入のプレースホルダ {{...}} が残っています")
        for f in self.fences:
            if f.get("unclosed"):
                self.E("STRUCT-0", f["start"], "コードフェンスが閉じられていません")
        self.structure()
        self.references()
        self.citations()
        self.tiers_and_quotes()
        self.emoji()
        self.tables()
        self.diagrams()
        self.images()
        self.spacing()
        if self.mermaid:
            self.check_mermaid()
        if not self.offline:
            self.check_urls()
        return self.issues

    def structure(self):
        L, K = self.lines, self.kinds
        first = next((i for i, l in enumerate(L) if l.strip()), None)
        if first is None:
            self.E("STRUCT-1", None, "空のファイルです")
            return
        if not re.match(r"^# ■ \S", L[first]):
            self.E("STRUCT-1", first, "先頭行は '# ■ {レポート名}' にする")
        h1s = [i for i, l in enumerate(L) if K[i] == "text" and re.match(r"^# ", l)]
        if len(h1s) > 1:
            self.E("STRUCT-1", h1s[1], "h1 は 1 つだけにする")
        self.h2 = [(i, l[3:].strip()) for i, l in enumerate(L) if K[i] == "text" and re.match(r"^## ", l)]
        first_h2 = self.h2[0][0] if self.h2 else len(L)
        di = pi = None
        for i in range(first_h2):
            if K[i] != "text":
                continue
            if L[i].startswith("レポート作成日時:") and di is None:
                di = i
            if L[i].startswith("レポート指示プロンプト:") and pi is None:
                pi = i
        if di is None:
            self.E("STRUCT-2", None, "『レポート作成日時:』の行がありません")
        else:
            self.check_date(di)
        if pi is None:
            self.E("STRUCT-2", None, "『レポート指示プロンプト:』の行がありません")
        else:
            if di is not None and pi < di:
                self.E("STRUCT-2", pi, "『レポート作成日時:』の次に『レポート指示プロンプト:』を置く")
            body = L[pi][len("レポート指示プロンプト:"):].strip() + "".join(l.strip() for l in L[pi + 1:first_h2])
            if not body:
                self.E("STRUCT-2", pi, "レポート指示プロンプトの内容が空です")
            self.verbatim.update(range(pi, first_h2))  # 依頼文は原文のまま。和英スペース・絵文字検査の対象外
        for i, t in self.h2:
            if not t.startswith("● "):
                self.E("STRUCT-3", i, "h2 は '## ● ' で始める")
        if not self.h2:
            self.E("STRUCT-3", None, "h2 (## ● …) がありません")
            return
        refs = [(i, t) for i, t in self.h2 if t == "● 参考資料"]
        if len(refs) != 1:
            self.E("STRUCT-4", None, "'## ● 参考資料' がちょうど 1 つ必要です")
        else:
            nxt = next((j for j, _ in self.h2 if j > refs[0][0]), len(L))
            self.ref_range = (refs[0][0], nxt)
        if self.h2[-1][1] != "● 参考資料":
            self.E("STRUCT-4", self.h2[-1][0], "最後の h2 は '## ● 参考資料' にする")
        body_h2 = [t for _, t in self.h2 if t != "● 参考資料"]
        if not body_h2:
            self.E("STRUCT-3", None, "本文の h2 セクションがありません")
        kws = self.cfg["uncertainty_keywords"]
        if not any(any(k in t for k in kws) for t in body_h2):
            self.E("PRINCIPLE-1", None, f"不確実性・限界を述べる h2 が必要です (見出しに {'/'.join(kws)} のいずれかを含める)")

    def check_date(self, i):
        v = self.lines[i][len("レポート作成日時:"):].strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::\d{2})?\s*(?:\(?([A-Z]{2,5}|[+-]\d{2}:?\d{2})\)?)?$", v)
        if not m:
            self.E("DATE-1", i, f"日時の形式が不正です (例: 2026-10-31 21:30 JST): '{v}'")
            return
        try:
            d = dt.datetime(*map(int, m.groups()[:5]))
        except ValueError:
            self.E("DATE-1", i, f"存在しない日時です: '{v}'")
            return
        if d > dt.datetime.now() + dt.timedelta(days=1):
            self.E("DATE-1", i, f"未来の日時です (date コマンドの出力を使うこと): '{v}'")

    def references(self):
        if not self.ref_range:
            return
        L = self.lines
        start, end = self.ref_range
        i = start + 1
        while i < end:
            line = L[i]
            if not line.strip():
                i += 1
                continue
            m = re.match(r"^\[(\d+)\]\s+(.+)$", line)
            if not m:
                self.W("REF-1", i, f"参考資料に想定外の行があります: {line[:50]}")
                i += 1
                continue
            n, head = int(m.group(1)), m.group(2).strip()
            if n in self.refs:
                self.E("REF-2", i, f"参照番号 [{n}] が重複しています")
            if " - " not in head:
                self.E("REF-1", i, f"[{n}] の行は '[n] タイトル - サイト名' 形式にする")
                title, site = head, ""
            else:
                title, site = head.rsplit(" - ", 1)
            j = i + 1
            while j < end and not L[j].strip():
                j += 1
            um = re.match(r"^<?(https?://\S+?)>?$", L[j].strip()) if j < end else None
            if not um:
                self.E("REF-1", i, f"[{n}] の次の行に URL (https://…) が必要です")
                self.refs[n] = {"n": n, "title": title, "site": site, "url": "", "quote": "", "line": i}
                i = j if j > i else i + 1
                continue
            url = um.group(1)
            j += 1
            while j < end and not L[j].strip():
                j += 1
            fm = FENCE_RE.match(L[j]) if j < end else None
            quote = ""
            if not fm:
                self.E("REF-1", i, f"[{n}] の URL の次に原文の引用 (コードフェンス) が必要です")
                nxt = j
            else:
                marker = fm.group(1)
                k = j + 1
                buf = []
                while k < end:
                    cm = FENCE_RE.match(L[k])
                    if cm and cm.group(1)[0] == marker[0] and len(cm.group(1)) >= len(marker) and not cm.group(2).strip():
                        break
                    buf.append(L[k])
                    k += 1
                quote = "\n".join(buf).strip()
                if not quote:
                    self.E("REF-1", i, f"[{n}] の原文引用が空です")
                if len(quote) > self.cfg["max_quote_chars"]:
                    self.W("REF-4", i, f"[{n}] の引用が長すぎます ({len(quote)} 文字)。該当箇所のみにする")
                nxt = k + 1
            self.refs[n] = {"n": n, "title": title, "site": site, "url": url, "quote": quote, "line": i}
            i = max(nxt, i + 1)
        if self.refs and sorted(self.refs) != list(range(1, len(self.refs) + 1)):
            self.W("REF-5", start, "参照番号が 1 からの連番になっていません")

    def citations(self):
        cited = set()
        for i, l in self.text_lines(skip_verbatim=True, skip_refs=True):
            ml = mask(l)
            for m in CITE_CLUSTER.finditer(ml):
                items = [(int(a), bool(b)) for a, b in CITE_ONE.findall(m.group(0))]
                self.clusters.append((i, items))
                cited.update(n for n, _ in items)
                s, e = m.span()
                if ml[:s].strip():
                    if ml[s - 1] != " " or (s >= 2 and ml[s - 2] in " 　"):
                        self.E("CITE-1", i, f"{m.group(0)} の前は半角スペース 1 つにする")
                if ml[e:].strip():
                    if ml[e] != " " or (e + 1 < len(ml) and ml[e + 1] in " 　"):
                        self.E("CITE-1", i, f"{m.group(0)} の後ろは半角スペース 1 つにする")
        for n in sorted(cited):
            if n not in self.refs:
                self.E("CITE-2", None, f"[{n}] が本文で引用されていますが、参考資料に定義がありません")
        for n, r in self.refs.items():
            if n not in cited:
                self.E("CITE-3", r["line"], f"[{n}] は参考資料にありますが、本文で引用されていません")

    def ledger_entry(self, ref):
        if self.ledger is None or not ref.get("url"):
            return None
        return self.ledger.get(norm_url(ref["url"]))

    def tiers_and_quotes(self):
        if self.ledger is None:
            if self.refs:
                self.W("LEDGER-0", None, "台帳なし: 一次/二次の判定と原文引用の照合をスキップしました (--task-dir を指定)")
            return
        marker = self.cfg["secondary_marker"]
        for n, r in self.refs.items():
            led = self.ledger_entry(r)
            r["led"] = led
            if led is None:
                self.E("LEDGER-1", r["line"], f"[{n}] の URL が台帳に未登録です (ledger.py add)")
                continue
            if led.get("tier") not in ("primary", "secondary"):
                self.E("LEDGER-2", r["line"], f"[{n}] の tier は primary か secondary にする")
            self.verify_quote(n, r, led)
        for i, items in self.clusters:
            leds = [(n, mk, self.refs[n].get("led")) for n, mk in items if n in self.refs]
            if not leds or any(l is None for _, _, l in leds):
                continue
            primaries = [n for n, _, l in leds if l.get("tier") == "primary"]
            origins = {l.get("origin") or urllib.parse.urlsplit(l["url"]).netloc for _, _, l in leds}
            needs = not primaries and len(origins) < 2
            for n, mk, l in leds:
                if l.get("tier") == "primary" and mk:
                    self.W("TIER-2", i, f"[{n}] は一次ソースなので {marker} は不要です")
                if l.get("tier") == "secondary" and needs and not mk:
                    self.E("TIER-1", i, f"[{n}] は単一の二次ソースのみに基づく記述です。直後に {marker} を付ける (例: [{n}]{marker})")
                if l.get("status") == "unverified" and "未検証" not in self.lines[i]:
                    self.W("SRC-1", i, f"[{n}] は未検証 (本文を取得できていない) ソースです。『未検証』と明記する")

    def verify_quote(self, n, r, led):
        if led.get("status") == "unverified" or not led.get("snapshot"):
            self.W("QUOTE-0", r["line"], f"[{n}] はスナップショットが無く、引用を照合できません (未検証扱い)")
            return
        sp = self.ledger_dir / led["snapshot"]
        if not sp.exists():
            self.E("QUOTE-1", r["line"], f"[{n}] のスナップショットが見つかりません: {sp}")
            return
        snap = norm_text(sp.read_text(encoding="utf-8", errors="replace"))
        segs = [s for s in re.split(r"\s*(?:\[\.\.\.\]|\[…\]|…|\.\.\.)\s*", r["quote"]) if s.strip()]
        pos = 0
        for seg in segs:
            k = norm_text(seg)
            idx = snap.find(k, pos)
            if idx < 0:
                self.E("QUOTE-1", r["line"], f"[{n}] の引用がスナップショット内に見つかりません (原文のまま書く): 「{seg.strip()[:40]}…」")
                return
            pos = idx + len(k)

    def emoji(self):
        kinds = {}
        for i, l in self.text_lines(skip_verbatim=True):
            for ch in mask(l):
                if ch in "️‍":
                    continue
                if is_emoji(ch):
                    kinds.setdefault(ch, i)
        allow = set(self.cfg["emoji_allowlist"])
        if len(kinds) > self.cfg["emoji_max_kinds"]:
            self.E("EMOJI-1", None, f"絵文字の種類が多すぎます ({len(kinds)} 種 > {self.cfg['emoji_max_kinds']})")
        for ch, i in kinds.items():
            if ch not in allow:
                self.E("EMOJI-2", i, f"許可リスト外の絵文字 '{ch}' (config.json の emoji_allowlist で管理)")

    def tables(self):
        L, K = self.lines, self.kinds
        fence_at = {f["start"]: f for f in self.fences}
        i, count = 0, 0
        while i < len(L):
            if (K[i] == "text" and L[i].lstrip().startswith("|") and i + 1 < len(L) and K[i + 1] == "text"
                    and "|" in L[i + 1] and SEP_RE.match(L[i + 1].strip())):
                header = split_row(L[i])
                j = i + 2
                rows = []
                while j < len(L) and K[j] == "text" and L[j].lstrip().startswith("|"):
                    rows.append(split_row(L[j]))
                    j += 1
                count += 1
                self.check_table_json(i, j - 1, count, header, rows, fence_at)
                i = j
            else:
                i += 1

    def check_table_json(self, start, end, idx, header, rows, fence_at):
        L = self.lines
        k = end + 1
        while k < len(L) and not L[k].strip():
            k += 1
        f = fence_at.get(k) if k < len(L) and self.kinds[k] == "open" else None
        m = re.match(r"^json\s+table\s+(\d+)$", f["info"]) if f else None
        if not f or not m:
            self.E("TABLE-1", start, f"表 {idx} の直下に ```json table {idx} のブロックが必要です")
            return
        if int(m.group(1)) != idx:
            self.E("TABLE-1", f["start"], f"番号が連番ではありません: json table {m.group(1)} (期待値 {idx})")
        try:
            data = json.loads("\n".join(f["lines"]))
        except json.JSONDecodeError as e:
            self.E("TABLE-2", f["start"], f"json table {idx} が JSON として不正です: {e}")
            return
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            data = data["rows"]
        if not (isinstance(data, list) and all(isinstance(r, dict) for r in data)):
            self.E("TABLE-2", f["start"], f"json table {idx} は行オブジェクトの配列 [{{\"列名\": \"値\"}}] にする")
            return
        if len(data) != len(rows):
            self.E("TABLE-3", f["start"], f"json table {idx} の行数 ({len(data)}) が表 ({len(rows)}) と一致しません")
            return
        hn = [cell_norm(h) for h in header]
        for ri, (obj, row) in enumerate(zip(data, rows), 1):
            if [cell_norm(k) for k in obj.keys()] != hn:
                self.E("TABLE-3", f["start"], f"json table {idx} の行 {ri} のキーが表のヘッダと一致しません")
                return
            for hname, cell, val in zip(hn, row + [""] * (len(hn) - len(row)), obj.values()):
                if cell_norm(cell) != cell_norm(val):
                    self.E("TABLE-3", f["start"], f"json table {idx} の行 {ri} 列 '{hname}' が表の内容と一致しません")
                    return

    def diagrams(self):
        for i, l in self.text_lines(skip_verbatim=True):
            if re.search(r"\+-{2,}|-{2,}\+", l):
                self.E("DIAG-1", i, "記号 (+ - | _) による図は禁止です。mermaid か draw.io (.drawio.svg) を使う")
        for f in self.fences:
            if f["info"].split()[:1] in ([], ["text"], ["txt"], ["plain"], ["plaintext"], ["ascii"], ["diagram"]):
                for off, l in enumerate(f["lines"]):
                    if re.search(r"\+-{2,}|-{2,}\+", l) or any(c in BOX_CORNERS for c in l):
                        self.E("DIAG-1", f["start"] + 1 + off, "罫線・記号で描いた図は禁止です。mermaid か draw.io を使う")
                        break

    def images(self):
        for i, l in self.text_lines(skip_verbatim=True):
            for m in IMG_RE.finditer(l):
                alt, src = m.group(1), m.group(2)
                if not alt.strip():
                    self.W("IMG-1", i, "画像の alt テキストが空です")
                if re.match(r"^https?://", src):
                    k = i + 1
                    while k < len(self.lines) and not self.lines[k].strip():
                        k += 1
                    nxt = mask(self.lines[k]) if k < len(self.lines) else ""
                    if not CITE_CLUSTER.search(nxt):
                        self.E("IMG-2", i, "外部画像の直下の行に出典 [n] が必要です")
                else:
                    if src.endswith(".drawio"):
                        self.E("IMG-3", i, ".drawio は md に貼れません。draw.io で .drawio.svg に書き出して参照する")
                        continue
                    if not (self.path.parent / urllib.parse.unquote(src)).exists():
                        self.E("IMG-3", i, f"参照している画像ファイルが存在しません: {src}")
        for d in self.path.parent.rglob("*.drawio"):
            if not (d.with_name(d.name + ".svg").exists() or d.with_name(d.name + ".png").exists()):
                self.W("IMG-4", None, f"{d.name} に対応する .drawio.svg / .drawio.png がありません (draw.io で書き出す)")

    def spacing(self):
        for i, l in self.text_lines(skip_verbatim=True):
            ml = mask(l)
            hits = []
            for rx in (SP1, SP2):
                for m in rx.finditer(ml):
                    s = max(0, m.start() - 4)
                    hits.append(ml[s:m.end() + 4].replace("\x00", ""))
            if hits:
                self.E("SPACE-1", i, "日本語と英数字の間に半角スペースが必要です: " + " / ".join(f"…{h}…" for h in hits[:3]))

    def check_mermaid(self):
        mm = [f for f in self.fences if f["info"].split()[:1] == ["mermaid"]]
        if not mm:
            return
        exe = shutil.which("mmdc")
        if not exe:
            self.W("MERMAID-0", None, "mmdc が無いため mermaid の構文検証をスキップしました (npm i -g @mermaid-js/mermaid-cli)")
            return
        for f in mm:
            code = "\n".join(f["lines"]).strip()
            if not code:
                self.E("MERMAID-1", f["start"], "mermaid ブロックが空です")
                continue
            with tempfile.TemporaryDirectory() as td:
                src, out = Path(td) / "d.mmd", Path(td) / "d.svg"
                src.write_text(code, encoding="utf-8")
                try:
                    cp = subprocess.run([exe, "-i", str(src), "-o", str(out)], capture_output=True, text=True, timeout=90)
                except subprocess.TimeoutExpired:
                    self.W("MERMAID-0", f["start"], "mmdc がタイムアウトしました")
                    continue
                if cp.returncode != 0:
                    msg = (cp.stderr or cp.stdout).strip().splitlines()
                    self.E("MERMAID-1", f["start"], "mermaid の構文エラー: " + (msg[-1] if msg else "不明"))

    def check_urls(self):
        targets = []
        for n, r in self.refs.items():
            if r.get("url"):
                targets.append((r["url"], False, r["line"], f"参考資料 [{n}]"))
        for i, l in self.text_lines(skip_verbatim=True):
            for m in IMG_RE.finditer(l):
                if re.match(r"^https?://", m.group(2)):
                    targets.append((m.group(2), True, i, "画像"))

        def probe(t):
            url, is_img = t[0], t[1]
            for method in ("HEAD", "GET"):
                req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0 (cline-harness lint)"})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        ct = r.headers.get("Content-Type", "")
                        if is_img and not ct.lower().startswith("image/"):
                            return ("ERROR", f"{t[3]} が画像ではありません (Content-Type: {ct})")
                        return None
                except urllib.error.HTTPError as e:
                    if method == "HEAD" and e.code in (400, 403, 405, 501):
                        continue
                    sev = "ERROR" if e.code in (404, 410) else "WARN"
                    return (sev, f"{t[3]} に到達できません (HTTP {e.code}): {url}")
                except Exception as e:  # noqa: BLE001
                    return ("WARN", f"{t[3]} に到達できません ({type(e).__name__}): {url}")
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for t, res in zip(targets, ex.map(probe, targets)):
                if res:
                    self.issues.append((res[0], "URL-1", t[2] + 1, res[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--task-dir")
    ap.add_argument("--ledger")
    ap.add_argument("--offline", action="store_true", help="URL 到達性チェックを行わない")
    ap.add_argument("--no-mermaid", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="警告もエラー扱い")
    a = ap.parse_args()
    lt = Linter(Path(a.report), load_cfg(), Path(a.task_dir) if a.task_dir else None,
                Path(a.ledger) if a.ledger else None, a.offline, not a.no_mermaid)
    issues = sorted(lt.run(), key=lambda x: (x[2] is None, x[2] or 0, x[1]))
    errors = [x for x in issues if x[0] == "ERROR"]
    warns = [x for x in issues if x[0] == "WARN"]
    if a.json:
        print(json.dumps([{"severity": s, "rule": r, "line": ln, "message": m} for s, r, ln, m in issues],
                         ensure_ascii=False, indent=2))
    else:
        for s, r, ln, m in issues:
            print(f"{s:<5} [{r}] {'L' + str(ln) if ln else '-':<5} {m}")
        print(f"\n{len(errors)} errors, {len(warns)} warnings")
    return 1 if errors or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
