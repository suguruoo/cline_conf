#!/usr/bin/env python3
"""tasklib: spec -> plan -> progress -> result プロトコルの中核 (標準ライブラリのみ)。

- 状態は <root>/tasks/<task-id>/ に置く (spec.md plan.md progress.md result.md approvals.json ...)
- 承認は approvals.json に「本文の sha256」で記録する。承認後に本文が変わると stale 扱い。
- 人間だけが `taskctl.py approve` を実行する想定 (PreToolUse hook がモデルからの実行を拒否する)。
"""
from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STAGES = ("spec", "plan", "progress", "result")
HUMAN_STAGES = ("spec", "plan", "result")
PROFILES = ("generic", "research-report", "docs", "architecture", "coding")
APPROVALS = "approvals.json"
ACTIVE = ".active"
# 計画承認前に書き込みを許す、タスクディレクトリ内のパス
PRE_APPROVAL_WRITABLE = ("spec.md", "plan.md", "notes.md", "scratch", "handoff.md", "handoff.auto.md")
HANDOFF = "handoff.md"
HANDOFF_AUTO = "handoff.auto.md"
MEMO_MARKER = "## 引き継ぎメモ"
MEMO_SECTIONS = ("直近の判断と理由", "未解決の問い・懸念", "次の一手", "注意")
AUTO_APPROVED_MODULES = {"__future__", "logging", "typing"}  # コーディング規約が使用を義務づけているもの

SCRIPT_DIR = Path(os.path.realpath(__file__)).parent
SKILL_DIR = SCRIPT_DIR.parent
SKILLS_DIR = SKILL_DIR.parent
TASKCTL = f"python3 {SCRIPT_DIR / 'taskctl.py'}"

REQUIRED = {
    "spec": ["目的", "スコープ", "受け入れ条件", "前提・制約", "未確定事項"],
    "plan": ["方針", "ステップ", "リスク"],
    "progress": ["ステップ進捗", "逸脱"],
    "result": ["結果サマリ", "受け入れ条件の検証", "残課題・限界"],
}
PROFILE_REQUIRED = {
    "research-report": {
        "spec": ["検証すべき問い", "依頼文の前提"],
        "plan": ["反証探索", "情報源の方針"],
    },
    "coding": {
        "plan": ["使用モジュール"],
    },
}
PROFILE_STEP_KEYWORDS = {"coding": ["テスト"]}  # plan のステップに含める語

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
AC_RE = re.compile(r"^\s*[-*]\s*(AC\d+)\s*[:：]\s*(.+?)\s*$")
STEP_RE = re.compile(
    r"^\s*[-*]\s*\[[ xX]\]\s*(S\d+)\s*[:：]\s*(.+?)\s*[（(]\s*covers\s*[:：]\s*([^)）]*)[)）]\s*$"
)
PROG_RE = re.compile(
    r"^\s*[-*]\s*(S\d+)\s*[:：]\s*(todo|in-progress|done|blocked)\b(?:\s*[|｜]\s*evidence\s*[:：]\s*(.*))?\s*$",
    re.I,
)
RESULT_ROW_RE = re.compile(r"^\|\s*(AC\d+)\s*\|\s*(pass|fail|waived)\s*\|\s*(.*?)\s*\|?\s*$", re.I)
DEV_HEAD_RE = re.compile(r"^###\s+(D\d+)\b.*$")


# ---------------------------------------------------------------- utilities
class Result:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        out = [f"ERROR: {m}" for m in self.errors]
        out += [f"WARN : {m}" for m in self.warnings]
        out += [f"INFO : {m}" for m in self.info]
        return "\n".join(out)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, text[m.end():]


def doc_hash(p: Path) -> str:
    """frontmatter を除いた本文のハッシュ (status の書き換えで承認が失効しないように)。"""
    _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
    return sha256_text(body.strip())


def strip_comments(t: str) -> str:
    return COMMENT_RE.sub("", t)


def parse_sections(text: str) -> list[tuple[str, list[str]]]:
    """フェンス外の `## ` 見出しでセクション分割する。"""
    sections: list[tuple[str, list[str]]] = []
    fence = None
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = None
            if sections:
                sections[-1][1].append(line)
            continue
        if m:
            fence = m.group(1)
            if sections:
                sections[-1][1].append(line)
            continue
        h = re.match(r"^##\s+(.*?)\s*$", line)
        if h:
            sections.append((h.group(1), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def find_section(sections, key: str):
    for title, lines in sections:
        if title.lstrip("●■ ").startswith(key):
            return title, lines
    return None


# ---------------------------------------------------------------- task model
class Task:
    def __init__(self, root: Path, tid: str) -> None:
        self.root = Path(root)
        self.id = tid
        self.dir = self.root / "tasks" / tid

    @property
    def meta(self) -> dict:
        p = self.dir / "task.json"
        return json.loads(read(p)) if p.exists() else {}

    @property
    def profile(self) -> str:
        return self.meta.get("profile", "generic")

    def path(self, stage: str) -> Path:
        return self.dir / f"{stage}.md"

    def approvals(self) -> dict:
        p = self.dir / APPROVALS
        return json.loads(read(p)) if p.exists() else {}

    def save_approvals(self, d: dict) -> None:
        (self.dir / APPROVALS).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_root(start: Path) -> Path | None:
    p = Path(start).resolve()
    for d in [p, *p.parents]:
        if (d / "tasks").is_dir():
            return d
    return None


def active_task(root: Path) -> Task | None:
    f = Path(root) / "tasks" / ACTIVE
    if not f.exists():
        return None
    tid = read(f).strip()
    if not tid or not (Path(root) / "tasks" / tid / "task.json").exists():
        return None
    return Task(root, tid)


def resolve_task(arg: str | None, root_arg: str | None, cwd: Path) -> Task:
    if arg:
        p = Path(arg).expanduser()
        if p.is_dir() and (p / "task.json").exists():
            return Task(p.resolve().parent.parent, p.resolve().name)
    root = Path(root_arg).resolve() if root_arg else find_root(cwd)
    if root is None:
        raise SystemExit("tasks/ ディレクトリが見つかりません (--root で作業ディレクトリを指定してください)")
    if arg:
        if not (root / "tasks" / arg / "task.json").exists():
            raise SystemExit(f"タスクが見つかりません: {arg}")
        return Task(root, arg)
    t = active_task(root)
    if t is None:
        raise SystemExit("アクティブなタスクがありません (taskctl new / taskctl active <id>)")
    return t


# ---------------------------------------------------------------- approvals
def approval_state(task: Task, stage: str) -> str:
    a = task.approvals().get(stage)
    p = task.path(stage)
    if not a or not p.exists():
        return "none"
    return "approved" if a.get("sha256") == doc_hash(p) else "stale"


def deviation_blocks(task: Task) -> dict[str, str]:
    p = task.path("progress")
    if not p.exists():
        return {}
    blocks: dict[str, list[str]] = {}
    cur = None
    for line in strip_comments(read(p)).splitlines():
        m = DEV_HEAD_RE.match(line)
        if m:
            cur = m.group(1)
            blocks[cur] = [line]
            continue
        if cur and re.match(r"^#{1,3}\s", line):
            cur = None
        if cur:
            blocks[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in blocks.items()}


def deviation_state(task: Task, did: str) -> str:
    blocks = deviation_blocks(task)
    a = task.approvals().get("deviations", {}).get(did)
    if did not in blocks or not a:
        return "none"
    return "approved" if a.get("sha256") == sha256_text(blocks[did]) else "stale"


def writes_open(task: Task) -> tuple[bool, str]:
    """計画承認済みか (= タスク領域外への書き込みを許可してよいか)。"""
    for st in ("spec", "plan"):
        s = approval_state(task, st)
        if s == "none":
            return False, f"{st}.md が未承認です"
        if s == "stale":
            return False, f"{st}.md は承認後に変更されています (再承認が必要)"
    return True, ""


# ---------------------------------------------------------------- gates
def _check_sections(task: Task, stage: str, text: str, res: Result):
    sections = parse_sections(text)
    keys = list(REQUIRED[stage]) + list(PROFILE_REQUIRED.get(task.profile, {}).get(stage, []))
    for key in keys:
        found = find_section(sections, key)
        if not found:
            res.err(f"{stage}.md: 必須セクション '## {key}' がありません")
        elif not any(l.strip() for l in found[1]):
            res.err(f"{stage}.md: セクション '## {key}' が空です")
    return sections


def _common_text(task: Task, stage: str, res: Result) -> str | None:
    p = task.path(stage)
    if not p.exists():
        res.err(f"{stage}.md が存在しません")
        return None
    _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
    text = strip_comments(body)
    for i, line in enumerate(text.splitlines(), 1):
        if PLACEHOLDER_RE.search(line):
            res.err(f"{stage}.md: 未記入のプレースホルダが残っています: {line.strip()[:60]}")
    return text


def parse_acs(task: Task) -> dict[str, str]:
    p = task.path("spec")
    if not p.exists():
        return {}
    _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
    acs = {}
    for line in strip_comments(body).splitlines():
        m = AC_RE.match(line)
        if m:
            acs[m.group(1)] = m.group(2)
    return acs


def parse_steps(task: Task) -> dict[str, tuple[str, list[str]]]:
    p = task.path("plan")
    if not p.exists():
        return {}
    _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
    steps = {}
    for line in strip_comments(body).splitlines():
        m = STEP_RE.match(line)
        if m:
            steps[m.group(1)] = (m.group(2), re.findall(r"AC\d+", m.group(3)))
    return steps


def gate_spec(task: Task, res: Result, **_) -> None:
    text = _common_text(task, "spec", res)
    if text is None:
        return
    _check_sections(task, "spec", text, res)
    acs = {}
    for line in text.splitlines():
        m = AC_RE.match(line)
        if m:
            acs[m.group(1)] = m.group(2)
    if not acs:
        res.err("spec.md: 受け入れ条件が 1 つもありません (形式: - AC1: 条件 ｜検証: 方法)")
    for ac, body in acs.items():
        if len(body) < 8:
            res.err(f"spec.md: {ac} が短すぎます")
        if not re.search(r"検証\s*[:：]\s*\S", body):
            res.err(f"spec.md: {ac} に検証方法がありません (『検証: …』を付ける)")
    sec = find_section(parse_sections(text), "未確定事項")
    if sec and any(re.match(r"^\s*[-*]\s*\[ \]", l) for l in sec[1]):
        res.warn("spec.md: 未確定事項に未解決の項目 (- [ ]) が残っています")


def gate_plan(task: Task, res: Result, **_) -> None:
    if approval_state(task, "spec") != "approved":
        res.err("spec が承認済みではありません (plan の前に spec の承認が必要)")
    text = _common_text(task, "plan", res)
    if text is None:
        return
    _check_sections(task, "plan", text, res)
    acs = parse_acs(task)
    steps = parse_steps(task)
    if not steps:
        res.err("plan.md: ステップがありません (形式: - [ ] S1: 内容 (covers: AC1, AC2))")
    covered = set()
    for sid, (_, cov) in steps.items():
        if not cov:
            res.err(f"plan.md: {sid} に covers がありません")
        for ac in cov:
            if ac not in acs:
                res.err(f"plan.md: {sid} が存在しない受け入れ条件 {ac} を参照しています")
            covered.add(ac)
    for ac in acs:
        if ac not in covered:
            res.err(f"plan.md: 受け入れ条件 {ac} を担当するステップがありません")
    for kw in PROFILE_STEP_KEYWORDS.get(task.profile, []):
        if not any(kw in text for text, _ in steps.values()):
            res.err(f"plan.md: ステップに『{kw}』を含むものがありません ({task.profile} profile の必須事項)")
    if task.profile == "coding":
        for m in module_rows(task, res):
            if not m["reason"] or not m["alternatives"]:
                res.err(f"plan.md: モジュール `{m['name']}` の選定理由と他の選択肢 (却下理由) を両方書いてください")


def _evidence_ok(task: Task, ev: str) -> tuple[bool, str]:
    toks = [t.strip() for t in re.split(r"[;；]", ev or "") if t.strip()]
    if not toks:
        return False, "evidence が空です"
    for t in toks:
        if re.match(r"^(cmd|log)\s*[:：]", t, re.I):
            continue
        if not any(c.exists() for c in (task.dir / t, task.root / t)):
            return False, f"証拠ファイルが存在しません: {t}"
    return True, ""


def gate_progress(task: Task, res: Result, complete: bool = False, **_) -> None:
    if approval_state(task, "plan") != "approved":
        res.err("plan が承認済みではありません")
    text = _common_text(task, "progress", res)
    if text is None:
        return
    _check_sections(task, "progress", text, res)
    steps = parse_steps(task)
    seen = {}
    for line in text.splitlines():
        m = PROG_RE.match(line)
        if not m:
            continue
        sid, status, ev = m.group(1), m.group(2).lower(), m.group(3)
        seen[sid] = status
        if sid not in steps:
            res.err(f"progress.md: {sid} は plan に無いステップです (逸脱: ### D# を起票し承認を得る)")
        if status == "done":
            ok, why = _evidence_ok(task, ev or "")
            if not ok:
                res.err(f"progress.md: {sid} は done ですが {why}")
        if status == "blocked":
            res.warn(f"progress.md: {sid} が blocked です (人間の判断が必要)")
    for did in deviation_blocks(task):
        s = deviation_state(task, did)
        if s != "approved":
            res.err(f"STOP: 逸脱 {did} は人間の承認待ちです ({'承認後に変更あり' if s == 'stale' else '未承認'})。作業を止めて報告してください")
    if complete:
        for sid in steps:
            if seen.get(sid) != "done":
                res.err(f"progress.md: {sid} が done ではありません (現在: {seen.get(sid, '記載なし')})")
    else:
        pending = [s for s in steps if seen.get(s) != "done"]
        if pending:
            res.info.append("未完了ステップ: " + ", ".join(pending))


def check_annotations(task: Task, res: Result) -> None:
    p = task.dir / "annotations.md"
    if not p.exists():
        res.err("annotations.md がありません (アノテーションチェック未実施)")
        return
    text = strip_comments(read(p))
    sections = parse_sections(text)
    for key in ("正確性", "日本語", "帰結"):
        found = find_section(sections, key)
        if not found:
            res.err(f"annotations.md: 観点 '## {key}…' のセクションがありません")
        elif not any(l.strip() for l in found[1]):
            res.err(f"annotations.md: 観点 '## {key}…' が空です (指摘なしなら『指摘なし』と書く)")
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]\s*\[(A-\d+)\]\s*(.*)$", line)
        if not m:
            continue
        aid, body = m.group(1), m.group(2)
        sev = re.search(r"重大度\s*[:：]\s*(high|medium|low)", body)
        st = re.search(r"状態\s*[:：]\s*(open|resolved|wontfix)", body)
        if not sev or not st:
            res.err(f"annotations.md: {aid} は『重大度: high|medium|low』『状態: open|resolved|wontfix』が必要です")
            continue
        if st.group(1) == "open":
            if sev.group(1) in ("high", "medium"):
                res.err(f"annotations.md: {aid} ({sev.group(1)}) が未解決です")
            else:
                res.warn(f"annotations.md: {aid} (low) が未解決です")
        if st.group(1) == "wontfix" and not re.search(r"理由\s*[:：]\s*\S", body):
            res.warn(f"annotations.md: {aid} は wontfix ですが理由がありません")


def module_rows(task: Task, res: Result | None = None) -> list[dict]:
    """plan.md の『使用モジュール』表を読む。列: モジュール | 用途 | 選定理由 | 他の選択肢と却下理由。"""
    p = task.path("plan")
    if not p.exists():
        return []
    _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
    sec = find_section(parse_sections(strip_comments(body)), "使用モジュール")
    rows = []
    for line in (sec[1] if sec else []):
        s = line.strip()
        if not s.startswith("|") or re.match(r"^\|?\s*:?-{3,}", s.lstrip("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("モジュール", "module"):
            continue
        name = cells[0].strip("` ")
        if name in ("", "なし"):
            continue
        rows.append({"name": name, "purpose": cells[1], "reason": cells[2], "alternatives": cells[3]})
    return rows


def coding_result_checks(task: Task, res: Result) -> None:
    scope = task.dir / "scope.txt"
    if not scope.exists() or not [l for l in read(scope).splitlines() if l.strip() and not l.startswith("#")]:
        res.err("scope.txt がありません (検査対象のコードのパスを 1 行ずつ。例: src/foo.py)")
        return
    paths = [l.strip() for l in read(scope).splitlines() if l.strip() and not l.startswith("#")]
    checker = SKILLS_DIR / "profile-coding" / "scripts" / "check_python.py"
    if not checker.exists():
        res.err(f"check_python.py が見つかりません: {checker}")
        return
    py = [p for p in paths if p.endswith(".py") or not Path(p).suffix]
    if any(p.endswith((".ts", ".tsx")) for p in paths):
        res.warn("TypeScript は自動検査の対象外です。ESLint / Prettier の結果を result.md の証拠に書いてください")
    if not py:
        return
    cmd = [sys.executable, str(checker), *py, "--plan", str(task.path("plan")), "--root", str(task.root)]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=str(task.root))
    if cp.returncode != 0:
        tail = "\n".join((cp.stdout + cp.stderr).strip().splitlines()[-40:])
        res.err("check_python.py が失敗しました:\n" + tail)


def profile_result_checks(task: Task, res: Result, offline: bool) -> None:
    if task.profile == "coding":
        coding_result_checks(task, res)
        return
    if task.profile != "research-report":
        return
    rep = task.dir / "deliverables" / "report.md"
    if not rep.exists():
        res.err("deliverables/report.md がありません")
    else:
        lint = SKILLS_DIR / "profile-research-report" / "scripts" / "lint_report.py"
        if not lint.exists():
            res.err(f"lint_report.py が見つかりません: {lint}")
        else:
            cmd = [sys.executable, str(lint), str(rep), "--task-dir", str(task.dir)]
            if offline:
                cmd.append("--offline")
            cp = subprocess.run(cmd, capture_output=True, text=True)
            if cp.returncode != 0:
                tail = "\n".join((cp.stdout + cp.stderr).strip().splitlines()[-40:])
                res.err("lint_report.py が失敗しました:\n" + tail)
    check_annotations(task, res)


def gate_result(task: Task, res: Result, offline: bool = False, **_) -> None:
    sub = Result()
    gate_progress(task, sub, complete=True)
    res.errors += [f"(progress) {m}" for m in sub.errors]
    text = _common_text(task, "result", res)
    if text is None:
        return
    _check_sections(task, "result", text, res)
    acs = parse_acs(task)
    rows = {}
    for line in text.splitlines():
        m = RESULT_ROW_RE.match(line.strip())
        if m:
            rows[m.group(1)] = (m.group(2).lower(), m.group(3))
    for ac in acs:
        if ac not in rows:
            res.err(f"result.md: {ac} の検証行がありません (| {ac} | pass/fail/waived | 証拠 |)")
            continue
        verdict, ev = rows[ac]
        if verdict == "fail":
            res.err(f"result.md: {ac} が fail です")
        elif not ev.strip():
            res.err(f"result.md: {ac} ({verdict}) の証拠/理由が空です")
        elif verdict == "waived":
            res.warn(f"result.md: {ac} は waived です (承認時に確認してください)")
    profile_result_checks(task, res, offline)


GATES = {"spec": gate_spec, "plan": gate_plan, "progress": gate_progress, "result": gate_result}


def gate(task: Task, stage: str, **kw) -> Result:
    res = Result()
    GATES[stage](task, res, **kw)
    return res


def confirm_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- handoff / summary
def _progress_status(task: Task) -> dict[str, str]:
    p = task.path("progress")
    seen: dict[str, str] = {}
    if p.exists():
        _, body = split_frontmatter(read(p).replace("\r\n", "\n"))
        for line in strip_comments(body).splitlines():
            m = PROG_RE.match(line)
            if m:
                seen[m.group(1)] = m.group(2).lower()
    return seen


def next_step(task: Task) -> str:
    steps = parse_steps(task)
    seen = _progress_status(task)
    for sid, (text, _) in steps.items():
        if seen.get(sid) != "done":
            return f"{sid}: {text} (現在: {seen.get(sid, '未着手')})"
    return "全ステップ完了 (result へ)" if steps else "plan 未作成"


def summary_text(task: Task) -> str:
    """handoff.md の自動生成部分と、TaskStart で注入する要約に使う。"""
    lines = [f"- タスク: {task.id} ({task.profile}) {task.meta.get('title', '')}"]
    for st in HUMAN_STAGES:
        lines.append(f"- {st}: {approval_state(task, st) if task.path(st).exists() else '未作成'}")
    seen = _progress_status(task)
    if seen:
        lines.append("- progress: " + ", ".join(f"{k}={v}" for k, v in seen.items()))
    lines.append(f"- 次の作業: {next_step(task)}")
    pend = [d for d in deviation_blocks(task) if deviation_state(task, d) != "approved"]
    if pend:
        lines.append(f"- 承認待ちの逸脱: {', '.join(pend)} (作業を止めて報告する)")
    ok, why = writes_open(task)
    lines.append(f"- タスク領域外への書き込み: {'可' if ok else '不可 (' + why + ')'}")
    return "\n".join(lines)


def write_handoff(task: Task, auto: bool = False) -> Path:
    """引き継ぎファイルを書く。auto=True は handoff.auto.md (スクリプトのみで生成)。
    通常の handoff.md は、既存の『引き継ぎメモ』部分を保持して自動部分だけ更新する。"""
    files = sorted(p.name for p in task.dir.iterdir() if p.is_file() and not p.name.startswith("handoff"))
    head = (
        f"---\ngenerated_by: taskctl handoff{' --auto' if auto else ''}\ngenerated_at: {now_iso()}\n---\n"
        f"# Handoff: {task.meta.get('title', task.id)}\n\n"
        f"## 状態 (自動生成)\n{summary_text(task)}\n"
        f"- 主なファイル: {', '.join(files)}\n\n"
        f"## 再開手順\n"
        f"1. `/tasks.md` を実行する (アクティブなタスク {task.id} が再開される)\n"
        f"2. この handoff.md と progress.md を読む。`taskctl status` で承認状態を確認する\n"
        f"3. coding profile なら skill `profile-coding` を読み込んでからコードを書く\n"
        f"4. 引き継ぎメモの『次の一手』から作業を再開する\n\n"
    )
    memo = (
        f"{MEMO_MARKER}\n<!-- モデルが記入する。経緯ではなく、次の担当が判断を誤らないための情報だけを書く -->\n"
        + "".join(f"### {s}\n{{{{{s}を書く}}}}\n\n" for s in MEMO_SECTIONS)
    )
    target = task.dir / (HANDOFF_AUTO if auto else HANDOFF)
    if not auto and target.exists():
        old = read(target)
        if MEMO_MARKER in old:
            memo = old[old.index(MEMO_MARKER):]
    target.write_text(head + (memo if not auto else ""), encoding="utf-8")
    return target


def check_handoff(task: Task, res: Result) -> None:
    p = task.dir / HANDOFF
    if not p.exists():
        res.err("handoff.md がありません (taskctl handoff で生成して引き継ぎメモを記入)")
        return
    text = read(p)
    if MEMO_MARKER not in text:
        res.err("handoff.md に『引き継ぎメモ』がありません")
        return
    memo = strip_comments(text[text.index(MEMO_MARKER):])
    for line in memo.splitlines():
        if PLACEHOLDER_RE.search(line):
            res.err(f"handoff.md: 引き継ぎメモが未記入です: {line.strip()[:50]}")
    sections = parse_sections("## x\n" + memo.replace("### ", "## "))
    for key in MEMO_SECTIONS:
        found = find_section(sections, key)
        if not found or not any(l.strip() for l in found[1]):
            res.err(f"handoff.md: 『{key}』が空です")
