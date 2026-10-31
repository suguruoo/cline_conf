#!/usr/bin/env python3
"""taskctl: タスクの作成・状態確認・ゲート検証・承認 (人間用) CLI。

  taskctl.py new "タイトル" --profile research-report [--slug xxx] [--root DIR]
  taskctl.py status
  taskctl.py gate spec|plan|progress|result [--complete] [--offline]
  taskctl.py approve spec|plan|result|D1 [--yes]      # 人間だけが実行する
  taskctl.py reopen spec|plan|result                   # 承認の取り消し (人間用)
  taskctl.py done                                       # result 承認後にタスクを閉じる
  taskctl.py handoff [--auto | --check]                 # コンテキスト引き継ぎファイルの生成 / 検査
  taskctl.py active [ID | --clear]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tasklib as T  # noqa: E402


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "task"


def render(text: str, title: str, tid: str) -> str:
    return (text.replace("{{TITLE}}", title).replace("{{TASK_ID}}", tid)
            .replace("{{CREATED}}", T.now_iso()))


def cmd_new(a) -> int:
    if a.profile not in T.PROFILES:
        print(f"profile は {', '.join(T.PROFILES)} のいずれか", file=sys.stderr)
        return 2
    root = Path(a.root or os.getcwd()).resolve()
    tid = f"{dt.datetime.now():%Y%m%d-%H%M}-{slugify(a.slug or a.title)}"
    d = root / "tasks" / tid
    if d.exists():
        print(f"既に存在します: {d}", file=sys.stderr)
        return 2
    d.mkdir(parents=True)
    prof_tpl = T.SKILLS_DIR / f"profile-{a.profile}" / "templates"
    for stage in T.STAGES:
        src = prof_tpl / f"{stage}.md"
        if not src.exists():
            src = T.SKILL_DIR / "templates" / f"{stage}.md"
        (d / f"{stage}.md").write_text(render(T.read(src), a.title, tid), encoding="utf-8")
    (d / "task.json").write_text(json.dumps(
        {"id": tid, "title": a.title, "profile": a.profile, "created_at": T.now_iso(), "status": "active"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "scratch").mkdir()
    (d / "notes.md").write_text(f"# Notes: {a.title}\n", encoding="utf-8")
    if (prof_tpl / "report.md").exists():
        (d / "deliverables").mkdir()
        (d / "sources").mkdir()
        (d / "deliverables" / "report.md").write_text(
            render(T.read(prof_tpl / "report.md"), a.title, tid), encoding="utf-8")
        (d / "ledger.json").write_text('{"sources": []}\n', encoding="utf-8")
    (root / "tasks" / T.ACTIVE).write_text(tid + "\n", encoding="utf-8")
    print(f"created: {d}\nactive : {tid}\nprofile: {a.profile}")
    return 0


def cmd_status(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    active = T.active_task(t.root)
    print(f"task    : {t.id}  ({t.profile})  {'[active]' if active and active.id == t.id else ''}")
    print(f"title   : {t.meta.get('title', '')}")
    print(f"dir     : {t.dir}")
    print("stage     doc  approval")
    for st in T.STAGES:
        ap = T.approval_state(t, st) if st in T.HUMAN_STAGES else "(auto)"
        print(f"{st:<9} {'yes' if t.path(st).exists() else 'no ':<4} {ap}")
    devs = T.deviation_blocks(t)
    for did in devs:
        print(f"deviation {did}: {T.deviation_state(t, did)}")
    ok, why = T.writes_open(t)
    print(f"writes outside tasks/: {'OPEN' if ok else 'CLOSED - ' + why}")
    hp = t.dir / T.HANDOFF
    print(f"handoff : {'present' if hp.exists() else 'none'}")
    print(f"next    : {T.next_step(t)}")
    return 0


def cmd_gate(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    kw = {}
    if a.stage == "progress":
        kw["complete"] = a.complete
    if a.stage == "result":
        kw["offline"] = a.offline
    res = T.gate(t, a.stage, **kw)
    print(res.render() or "OK")
    print(f"\n[{a.stage}] {'PASS' if res.ok else 'FAIL'} (errors={len(res.errors)}, warnings={len(res.warnings)})")
    return 0 if res.ok else 1


def cmd_approve(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    key = a.target
    ap = t.approvals()
    if key in T.HUMAN_STAGES:
        res = T.gate(t, key, **({"offline": a.offline} if key == "result" else {}))
        print(res.render() or "OK")
        if not res.ok:
            print(f"\nゲートを通過していないため承認できません ({key})", file=sys.stderr)
            return 1
        h = T.doc_hash(t.path(key))
    elif re.fullmatch(r"D\d+", key):
        blocks = T.deviation_blocks(t)
        if key not in blocks:
            print(f"逸脱 {key} が progress.md にありません", file=sys.stderr)
            return 1
        print(blocks[key])
        h = T.sha256_text(blocks[key])
    else:
        print("target は spec|plan|result|D<number>", file=sys.stderr)
        return 2
    if not a.yes:
        if input(f"\n{t.id} の {key} を承認しますか? [y/N] ").strip().lower() != "y":
            print("中止しました")
            return 1
    rec = {"sha256": h, "approved_at": T.now_iso(), "approved_by": T.confirm_user()}
    if key in T.HUMAN_STAGES:
        ap[key] = rec
    else:
        ap.setdefault("deviations", {})[key] = rec
    t.save_approvals(ap)
    print(f"approved: {key}")
    return 0


def cmd_reopen(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    ap = t.approvals()
    idx = T.HUMAN_STAGES.index(a.target)
    for st in T.HUMAN_STAGES[idx:]:
        ap.pop(st, None)
    t.save_approvals(ap)
    print(f"reopened: {', '.join(T.HUMAN_STAGES[idx:])}")
    return 0


def cmd_done(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    if T.approval_state(t, "result") != "approved":
        print("result が承認済みではないため完了できません", file=sys.stderr)
        return 1
    meta = t.meta
    meta.update(status="done", done_at=T.now_iso())
    (t.dir / "task.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    act = T.active_task(t.root)
    if act and act.id == t.id:
        (t.root / "tasks" / T.ACTIVE).unlink()
    print(f"done: {t.id}")
    return 0


def cmd_handoff(a) -> int:
    t = T.resolve_task(a.task, a.root, Path.cwd())
    if a.check:
        res = T.Result()
        T.check_handoff(t, res)
        print(res.render() or "OK")
        print(f"\n[handoff] {'PASS' if res.ok else 'FAIL'}")
        return 0 if res.ok else 1
    p = T.write_handoff(t, auto=a.auto)
    print(f"written: {p}")
    if not a.auto:
        print("次: 『引き継ぎメモ』の {{…}} を全て記入し、`taskctl handoff --check` が PASS になったら新規タスクへ引き継ぐ")
    return 0


def cmd_active(a) -> int:
    root = Path(a.root).resolve() if a.root else T.find_root(Path.cwd())
    if root is None:
        print("tasks/ が見つかりません", file=sys.stderr)
        return 2
    f = root / "tasks" / T.ACTIVE
    if a.clear:
        f.unlink(missing_ok=True)
        print("active cleared")
    elif a.id:
        if not (root / "tasks" / a.id / "task.json").exists():
            print(f"タスクが見つかりません: {a.id}", file=sys.stderr)
            return 2
        f.write_text(a.id + "\n", encoding="utf-8")
        print(f"active: {a.id}")
    else:
        act = T.active_task(root)
        print(act.id if act else "(none)")
        ids = sorted(p.parent.name for p in (root / "tasks").glob("*/task.json"))
        for i in ids:
            print(f"  {i}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="taskctl")
    ap.add_argument("--root")
    ap.add_argument("--task")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("title"); p.add_argument("--profile", default="generic"); p.add_argument("--slug")
    sub.add_parser("status")
    p = sub.add_parser("gate"); p.add_argument("stage", choices=T.STAGES); p.add_argument("--complete", action="store_true"); p.add_argument("--offline", action="store_true")
    p = sub.add_parser("approve"); p.add_argument("target"); p.add_argument("--yes", action="store_true"); p.add_argument("--offline", action="store_true")
    p = sub.add_parser("reopen"); p.add_argument("target", choices=T.HUMAN_STAGES)
    sub.add_parser("done")
    p = sub.add_parser("handoff"); p.add_argument("--auto", action="store_true"); p.add_argument("--check", action="store_true")
    p = sub.add_parser("active"); p.add_argument("id", nargs="?"); p.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    return {"new": cmd_new, "status": cmd_status, "gate": cmd_gate, "approve": cmd_approve,
            "reopen": cmd_reopen, "done": cmd_done, "handoff": cmd_handoff, "active": cmd_active}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
