#!/usr/bin/env python3
"""check_python.py: Python コーディング規約 (docs/coding-standards.md) の機械検査。標準ライブラリのみ。

  python3 check_python.py PATH... [--plan tasks/<id>/plan.md | --no-modules] [--root DIR] [--json] [--strict]

規約番号 (PY-NN) は coding-standards.md の項番に対応する。
エラーが 1 件以上あれば終了コード 1。警告は規約が『推奨』『例外あり』の項目と、機械判定が曖昧な項目。
検査できないもの (命名の分かりやすさ、コメントが『なぜ』を書いているか、設計の妥当性) はレビューで確認する。
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

AUTO_APPROVED = {"__future__", "logging", "typing"}  # 規約 21 / 15 が使用を義務づけているもの
MAGIC_OK = {0, 1, -1, 2}
BAD_FUNC_NAMES = {"func", "foo", "bar", "baz", "tmp", "temp", "do", "proc", "handle1"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "build", "dist", "site-packages"}
NO_TEST_NEEDED = {"__init__.py", "__main__.py", "conftest.py", "setup.py"}
STDLIB_FALLBACK = set(
    "abc argparse array ast asyncio base64 bisect builtins calendar cmath collections concurrent configparser contextlib "
    "copy csv ctypes dataclasses datetime decimal difflib email enum errno fnmatch fractions functools gc getpass glob "
    "gzip hashlib heapq hmac html http importlib inspect io ipaddress itertools json keyword linecache locale logging "
    "math mimetypes multiprocessing numbers operator os pathlib pickle platform pprint queue random re secrets select "
    "shlex shutil signal smtplib socket sqlite3 ssl stat statistics string struct subprocess sys tempfile textwrap "
    "threading time timeit tokenize traceback types typing unicodedata unittest urllib uuid warnings weakref xml zipfile "
    "zlib zoneinfo __future__".split()
)
STDLIB = set(getattr(sys, "stdlib_module_names", ())) or STDLIB_FALLBACK

PASCAL = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")
SNAKE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
UPPER = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
TEST_NAME = re.compile(r"^test_[a-z0-9]+(_[a-z0-9]+){2,}$")
LITERAL_NODES = (ast.Constant, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.JoinedStr)


class Checker:
    def __init__(self, path: Path, local: set[str], approved: set[str] | None, root: Path) -> None:
        self.path = path
        self.src = path.read_text(encoding="utf-8")
        self.lines = self.src.split("\n")
        self.tree = ast.parse(self.src)
        self.local = local
        self.approved = approved
        self.root = root
        self.is_test = path.name.startswith("test_") or path.name.endswith("_test.py") or \
            any(p in ("tests", "test") for p in path.parts)
        self.issues: list[tuple[str, str, int, str]] = []
        self.parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for ch in ast.iter_child_nodes(node):
                self.parents[ch] = node

    def add(self, sev: str, rule: int, line: int, msg: str) -> None:
        self.issues.append((sev, f"PY-{rule:02d}", line, msg))

    # ------------------------------------------------------------ 1, 14: imports
    def classify(self, mod: str, level: int) -> int:
        if level > 0:
            return 2
        top = mod.split(".")[0]
        if top == "__future__":
            return -1
        if top in STDLIB:
            return 0
        return 2 if top in self.local else 1

    def check_imports(self) -> None:
        prev = -1
        for node in self.tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = node.names[0].name if isinstance(node, ast.Import) else (node.module or "")
                g = self.classify(mod, getattr(node, "level", 0))
                if g < prev:
                    self.add("ERROR", 14, node.lineno, f"import の順序が違います: {mod} (標準 → サードパーティ → ローカル)")
                prev = max(prev, g)
        for node in ast.walk(self.tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for m in mods:
                top = m.split(".")[0]
                if top in self.local or top in AUTO_APPROVED:
                    continue
                if self.approved is None:
                    continue
                if top not in self.approved and m not in self.approved:
                    self.add("ERROR", 1, node.lineno,
                             f"未承認のモジュール `{top}`。plan.md の『使用モジュール』に理由と他の選択肢を書き、承認を得てください")

    # ------------------------------------------------------------ 3-7: naming
    def check_naming(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and not PASCAL.match(node.name):
                self.add("ERROR", 3, node.lineno, f"クラス名は PascalCase: {node.name}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = node.name
                if not (SNAKE.match(n) or re.match(r"^__[a-z0-9_]+__$", n)):
                    self.add("ERROR", 4, node.lineno, f"関数名・メソッド名は snake_case: {n}")
                if not n.startswith("__") and (len(n.strip("_")) < 3 or n in BAD_FUNC_NAMES):
                    self.add("WARN", 7, node.lineno, f"関数名から機能が読み取れません: {n}")
                a = node.args
                for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                    if arg and arg.arg not in ("self", "cls") and not SNAKE.match(arg.arg):
                        self.add("ERROR", 4, node.lineno, f"引数名は snake_case: {arg.arg}")
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id != "_":
                if isinstance(self.parents.get(node), (ast.Assign, ast.AnnAssign, ast.For, ast.comprehension,
                                                       ast.With, ast.AugAssign, ast.Tuple, ast.NamedExpr)):
                    scope = self.scope_of(node)
                    if scope == "function" and not SNAKE.match(node.id):
                        self.add("ERROR", 4, node.lineno, f"変数名は snake_case: {node.id}")
        for node in self.tree.body:
            targets, value = [], None
            if isinstance(node, ast.Assign):
                targets, value = [t for t in node.targets if isinstance(t, ast.Name)], node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets, value = [node.target], node.value
            for t in targets:
                if re.match(r"^__\w+__$", t.id) or t.id == "logger" or value is None:
                    continue
                if isinstance(value, ast.UnaryOp):
                    value = value.operand
                if isinstance(value, LITERAL_NODES):
                    if not UPPER.match(t.id):
                        self.add("ERROR", 5, node.lineno, f"定数は UPPER_SNAKE_CASE: {t.id}")
                elif isinstance(value, ast.Call):
                    fn = ast.unparse(value.func) if hasattr(ast, "unparse") else ""
                    if fn.split(".")[-1] in ("TypeVar", "NewType", "namedtuple", "NamedTuple", "getLogger", "TypedDict"):
                        continue
                    if not UPPER.match(t.id):
                        self.add("WARN", 26, node.lineno, f"グローバル変数 `{t.id}` (原則禁止。例外なら理由をコメントで明記)")
                elif not (UPPER.match(t.id) or PASCAL.match(t.id)):
                    self.add("WARN", 26, node.lineno, f"グローバル変数 `{t.id}` (原則禁止。例外なら理由をコメントで明記)")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Global):
                self.add("ERROR", 26, node.lineno, "global 文は禁止です")

    def scope_of(self, node: ast.AST) -> str:
        cur = self.parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return "function"
            if isinstance(cur, ast.ClassDef):
                return "class"
            cur = self.parents.get(cur)
        return "module"

    # ------------------------------------------------------------ 8-10: docstrings
    def check_docstrings(self) -> None:
        sev = "WARN" if self.is_test else "ERROR"
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    self.add(sev, 10, node.lineno, f"クラス {node.name} に docstring がありません")
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            n = node.name
            if n.startswith("__") and n.endswith("__") and n != "__init__":
                continue
            doc = ast.get_docstring(node)
            if not doc:
                self.add(sev, 8, node.lineno, f"関数 {n} に docstring がありません (概要は全関数で必須)")
                continue
            first = doc.strip().splitlines()[0].strip()
            if not first.endswith(("。", ".", "。)", ".)")):
                self.add("WARN", 8, node.lineno, f"{n}: 1 行目 (概要) は句点で終える (PEP 257)")
            if self.is_test and n.startswith("test"):
                continue
            a = node.args
            params = [x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x]
            params = [p for p in params if p not in ("self", "cls")]
            has = {k: re.search(rf"(?m)^\s*{k}\s*:", doc) is not None for k in ("Args", "Returns", "Raises")}
            if params and not has["Args"]:
                self.add("ERROR", 9, node.lineno, f"{n}: 引数があるので `Args:` が必要です")
            elif params:
                block = doc[doc.index("Args:"):]
                for p in params:
                    if not re.search(rf"\b{re.escape(p)}\b", block):
                        self.add("WARN", 9, node.lineno, f"{n}: Args に引数 `{p}` の説明がありません")
            own = [x for x in ast.walk(node)]
            returns_value = any(isinstance(x, ast.Return) and x.value is not None and
                                not (isinstance(x.value, ast.Constant) and x.value.value is None) for x in own)
            if n != "__init__" and returns_value and not has["Returns"]:
                self.add("ERROR", 9, node.lineno, f"{n}: 値を返すので `Returns:` が必要です")
            if any(isinstance(x, ast.Raise) and x.exc is not None for x in own) and not has["Raises"]:
                self.add("ERROR", 9, node.lineno, f"{n}: 例外を発生させるので `Raises:` が必要です")

    # ------------------------------------------------------------ 11-13: style
    def check_style(self) -> None:
        for i, line in enumerate(self.lines, 1):
            if re.match(r"^\s*\t", line):
                self.add("ERROR", 11, i, "インデントにタブは使えません (スペース 4 つ)")
            if len(line) > 79 and "http://" not in line and "https://" not in line:
                prev = "\n".join(self.lines[max(0, i - 4):i - 1])
                if "PERFORMANCE OPTIMIZATION" not in prev:
                    self.add("WARN", 12, i, f"行が長すぎます ({len(line)} 文字 > 79。推奨)")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.stmt) and node.col_offset % 4 == 0:
                continue
            if isinstance(node, ast.stmt) and not self.lines[node.lineno - 1][:node.col_offset].strip():
                self.add("ERROR", 11, node.lineno, "インデントはスペース 4 つの倍数にしてください")
        self.check_blank_lines(self.tree.body, 2, True)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                self.check_blank_lines(node.body, 1, False)
        run = 0
        for i, line in enumerate(self.lines, 1):
            run = run + 1 if not line.strip() else 0
            if run == 3:
                self.add("WARN", 13, i, "空行が 3 行以上続いています (最大 2 行)")

    def check_blank_lines(self, body: list, need: int, top: bool) -> None:
        for idx, node in enumerate(body):
            if idx == 0 or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if (not top) and idx == 1 and isinstance(body[0], ast.Expr):
                continue  # クラスの docstring 直後
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            j = start - 2
            while j >= 0 and self.lines[j].strip().startswith("#"):
                j -= 1
            blanks = 0
            while j >= 0 and not self.lines[j].strip():
                blanks += 1
                j -= 1
            if blanks < need:
                where = "トップレベルの関数・クラス定義の前は 2 行" if top else "クラス内メソッドの間は 1 行"
                self.add("ERROR", 13, start, f"空行ルール: {where}空けてください (現在 {blanks} 行)")

    # ------------------------------------------------------------ 15-17, 26: types & exceptions
    def check_types_and_exceptions(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                in_class = isinstance(self.parents.get(node), ast.ClassDef)
                args = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
                for k, arg in enumerate([x for x in args if x]):
                    if in_class and k == 0 and arg.arg in ("self", "cls"):
                        continue
                    if arg.annotation is None:
                        self.add("ERROR", 15, node.lineno, f"{node.name}: 引数 `{arg.arg}` に型ヒントがありません")
                if node.returns is None:
                    self.add("ERROR", 15, node.lineno, f"{node.name}: 戻り値の型ヒントがありません (None なら `-> None`)")
            if isinstance(node, ast.ClassDef):
                bases = " ".join(ast.unparse(b) for b in node.bases) if hasattr(ast, "unparse") else ""
                if "Enum" in bases:
                    continue
                for st in node.body:
                    if isinstance(st, ast.Assign) and all(isinstance(t, ast.Name) and not t.id.startswith("__")
                                                          for t in st.targets):
                        self.add("ERROR", 16, st.lineno, "クラス属性には型ヒントが必要です (例: `name: str = ...`)")
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    self.add("ERROR", 26, node.lineno, "bare except は禁止です (具体的な例外クラスを指定)")
                elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
                    self.add("WARN", 17, node.lineno, f"`except {node.type.id}` は広すぎます。具体的な例外クラスを使ってください")
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                if isinstance(exc, ast.Name) and exc.id in ("Exception", "BaseException"):
                    self.add("WARN", 17, node.lineno, f"`raise {exc.id}` は汎用的すぎます。具体的な (カスタム) 例外を使ってください")

    # ------------------------------------------------------------ 19-20: tests
    def check_tests(self) -> None:
        if not self.is_test:
            return
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                if not TEST_NAME.match(node.name):
                    self.add("ERROR", 19, node.lineno, f"テスト名は test_[機能]_[条件]_[期待結果]: {node.name}")
                seg = "\n".join(self.lines[node.lineno - 1:node.end_lineno])
                missing = [w for w in ("Arrange", "Act", "Assert") if not re.search(rf"#\s*{w}", seg, re.I)]
                if missing:
                    self.add("ERROR", 20, node.lineno, f"{node.name}: AAA コメントがありません ({', '.join(missing)})")

    def check_test_exists(self) -> None:
        if self.is_test or self.path.name in NO_TEST_NEEDED:
            return
        stem = self.path.stem
        names = {f"test_{stem}.py", f"{stem}_test.py"}
        dirs = [self.path.parent, self.path.parent / "tests", self.path.parent / "test", self.root / "tests", self.root / "test"]
        for d in dirs:
            if d.is_dir() and any((d / n).exists() for n in names):
                return
        for n in names:
            if any(not (set(p.parts) & SKIP_DIRS) for p in self.root.rglob(n)):
                return
        self.add("ERROR", 19, 1, f"テストがありません。`test_{stem}.py` を作成してください (テストのないコードは生成しない)")

    # ------------------------------------------------------------ 21-26: logging, comments, magic numbers
    def check_logging_comments(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                self.add("ERROR", 21, node.lineno, "print は使えません。logger を使ってください")
        defines = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in self.tree.body)
        if defines and not self.is_test:
            ok = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "logger" for t in n.targets)
                     and "getLogger" in ast.dump(n.value) and "__name__" in ast.dump(n.value) for n in self.tree.body)
            if not ok:
                self.add("ERROR", 21, 1, "`logger = logging.getLogger(__name__)` がありません")
        try:
            for tok in tokenize.generate_tokens(io.StringIO(self.src).readline):
                if tok.type == tokenize.COMMENT and re.search(r"\b(TODO|FIXME|HACK)\b", tok.string):
                    if not re.search(r"\b(TODO|FIXME|HACK)\([^)]+\):", tok.string):
                        self.add("WARN", 25, tok.start[0], "TODO/FIXME/HACK は `TODO(担当者): 内容` の形式にし、期限か Issue 番号を添える")
        except tokenize.TokenError:
            pass
        if self.is_test:
            return
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                if node.value in MAGIC_OK or self.scope_of(node) != "function":
                    continue
                par = self.parents.get(node)
                if isinstance(par, ast.UnaryOp) and isinstance(par.op, ast.USub) and -node.value in MAGIC_OK:
                    continue
                if isinstance(par, ast.arguments):
                    continue
                self.add("WARN", 26, node.lineno, f"マジックナンバー {node.value!r}。名前付き定数にしてください")

    def run(self) -> list:
        self.check_imports()
        self.check_naming()
        self.check_docstrings()
        self.check_style()
        self.check_types_and_exceptions()
        self.check_tests()
        self.check_test_exists()
        self.check_logging_comments()
        return self.issues


def parse_plan_modules(plan: Path) -> set[str]:
    """plan.md の『使用モジュール』表の 1 列目を承認済みモジュールとして読む。"""
    names: set[str] = set()
    in_sec = False
    for line in plan.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_sec = "使用モジュール" in line
            continue
        s = line.strip()
        if in_sec and s.startswith("|") and not re.match(r"^\|?\s*:?-{3,}", s.lstrip("|")):
            cell = s.strip("|").split("|")[0].strip().strip("` ")
            if cell and cell not in ("モジュール", "module", "なし"):
                names.add(cell)
                names.add(cell.split(".")[0])
    return names


def gather(paths: list[str], root: Path) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        q = Path(p)
        q = q if q.is_absolute() else root / q
        if q.is_dir():
            files += [f for f in sorted(q.rglob("*.py")) if not (set(f.parts) & SKIP_DIRS)]
        elif q.suffix == ".py" and q.exists():
            files.append(q)
    return files


def local_names(files: list[Path], root: Path) -> set[str]:
    names: set[str] = set()
    for d in {root, *[f.parent for f in files]}:
        names |= {p.stem for p in d.glob("*.py")}
        for p in d.iterdir():
            if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."):
                if (p / "__init__.py").exists() or any(p.glob("*.py")) or any(p.glob("*/__init__.py")):
                    names.add(p.name)  # 名前空間パッケージ (src/ など) も含める
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--plan")
    ap.add_argument("--no-modules", action="store_true", help="使用モジュールの承認検査を行わない")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    files = gather(a.paths, root)
    if not files:
        print("検査対象の .py ファイルがありません", file=sys.stderr)
        return 2
    approved = None
    if not a.no_modules:
        if not a.plan:
            print("--plan (承認済みの使用モジュール表を含む plan.md) か --no-modules を指定してください", file=sys.stderr)
            return 2
        approved = parse_plan_modules(Path(a.plan))
    local = local_names(files, root)
    all_issues = []
    for f in files:
        try:
            issues = Checker(f, local, approved, root).run()
        except SyntaxError as e:
            issues = [("ERROR", "PY-00", e.lineno or 1, f"構文エラー: {e.msg}")]
        for sev, rule, line, msg in issues:
            all_issues.append((str(f.relative_to(root)) if root in f.parents else str(f), sev, rule, line, msg))
    all_issues.sort(key=lambda x: (x[0], x[3], x[2]))
    errors = [i for i in all_issues if i[1] == "ERROR"]
    warns = [i for i in all_issues if i[1] == "WARN"]
    if a.json:
        print(json.dumps([dict(file=f, severity=s, rule=r, line=ln, message=m) for f, s, r, ln, m in all_issues],
                         ensure_ascii=False, indent=2))
    else:
        for f, s, r, ln, m in all_issues:
            print(f"{s:<5} [{r}] {f}:{ln} {m}")
        print(f"\n{len(files)} files, {len(errors)} errors, {len(warns)} warnings")
    return 1 if errors or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
