#!/usr/bin/env python3
"""ledger.py: 証拠台帳 (<task-dir>/ledger.json + sources/N.txt)。標準ライブラリのみ。

  ledger.py add <task-dir> --url URL --title T --site S --tier primary|secondary \
                [--origin DOMAIN] [--from-file F | --unverified --note TEXT]
  ledger.py list <task-dir>

ページ本文はスクリプト自身が取得して保存する (モデルが書き写さないので、引用照合の根拠になる)。
取得できない場合 (JS 描画 / ペイウォール / PDF) は --from-file で本文テキストを渡すか、--unverified で登録する。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class FetchError(Exception):
    pass


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre",
             "table", "ul", "ol", "blockquote", "header", "footer", "nav", "main", "dd", "dt", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t ]+", " ", text)).strip()


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cline-harness ledger)",
                                               "Accept": "text/html,text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(8_000_000)
            ct = r.headers.get("Content-Type", "")
            enc = r.headers.get_content_charset()
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"{type(e).__name__}: {e}") from e
    if "pdf" in ct.lower():
        raise FetchError("PDF は取得できません (pdftotext 等で変換したテキストを --from-file で渡す)")
    if not enc:
        m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", raw[:4096], re.I)
        enc = m.group(1).decode() if m else "utf-8"
    text = raw.decode(enc, errors="replace")
    if "html" in ct.lower() or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        text = html_to_text(text)
    if len(text.strip()) < 200:
        raise FetchError("本文がほとんど取得できませんでした (JS 描画 / ペイウォールの可能性)")
    return text


def load(td: Path) -> dict:
    p = td / "ledger.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"sources": []}


def save(td: Path, data: dict) -> None:
    (td / "ledger.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_add(a) -> int:
    td = Path(a.task_dir)
    data = load(td)
    if any(s["url"] == a.url for s in data["sources"]) and not a.replace:
        print(f"登録済みの URL です: {a.url} (--replace で更新)", file=sys.stderr)
        return 2
    data["sources"] = [s for s in data["sources"] if s["url"] != a.url]
    sid = max([s["id"] for s in data["sources"]] + [0]) + 1
    entry = {"id": sid, "url": a.url, "title": a.title, "site": a.site, "tier": a.tier,
             "origin": a.origin or urllib.parse.urlsplit(a.url).netloc.removeprefix("www."),
             "retrieved_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "status": "verified", "snapshot": "", "sha256": "", "note": a.note or ""}
    if a.unverified:
        entry["status"] = "unverified"
    else:
        try:
            text = Path(a.from_file).read_text(encoding="utf-8") if a.from_file else fetch(a.url)
        except FetchError as e:
            print(f"取得失敗: {e}\n  → --from-file <本文テキスト> を渡すか、--unverified --note '理由' で登録してください", file=sys.stderr)
            return 3
        (td / "sources").mkdir(exist_ok=True)
        snap = td / "sources" / f"{sid}.txt"
        snap.write_text(text, encoding="utf-8")
        entry["snapshot"] = f"sources/{sid}.txt"
        entry["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    data["sources"].append(entry)
    save(td, data)
    print(json.dumps({k: entry[k] for k in ("id", "url", "tier", "origin", "status", "snapshot")}, ensure_ascii=False))
    return 0


def cmd_list(a) -> int:
    for s in load(Path(a.task_dir))["sources"]:
        print(f"#{s['id']:<3} {s['tier']:<9} {s['status']:<10} {s['origin']:<28} {s['title']}  {s['url']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("task_dir")
    p.add_argument("--url", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--site", required=True)
    p.add_argument("--tier", required=True, choices=["primary", "secondary"])
    p.add_argument("--origin")
    p.add_argument("--from-file")
    p.add_argument("--unverified", action="store_true")
    p.add_argument("--note")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("task_dir")
    a = ap.parse_args()
    return {"add": cmd_add, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
