#!/usr/bin/env python3
"""追加要件のテスト: シェル運用規則、コンテキスト監視と引き継ぎ、コーディング規約。

実行: python3 -m unittest discover -s tests -v
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKCTL = ROOT / "skills/task-protocol/scripts/taskctl.py"
CHECK_PY = ROOT / "skills/profile-coding/scripts/check_python.py"

SPEC = """---
stage: spec
---
# Spec

## 目的
テスト用の目的です。

## スコープ / 非目標
- スコープ: a
- 非目標: b

## 受け入れ条件
- AC1: calc.py が規約を満たす ｜検証: check_python.py が終了コード 0

## 前提・制約
- なし

## 未確定事項
- なし
"""
PLAN_CODING = """---
stage: plan
---
# Plan

## 方針
単純に作る。

## 使用モジュール
| モジュール | 用途 | 選定理由 | 他の選択肢と却下理由 |
|---|---|---|---|
| `decimal` | 金額計算 | 誤差が出ない | float: 丸め誤差が出る |

## ステップ
- [ ] S1: テストを作る (covers: AC1)
- [ ] S2: 実装する (covers: AC1)

## リスクと手戻り点
- なし
"""
GOOD_PY = '''"""価格計算モジュール。"""
import logging

logger = logging.getLogger(__name__)

TAX_RATE = 0.1


class PriceCalculator:
    """価格を計算するクラス。"""

    rate: float = 0.1

    def calculate_discount_price(
        self,
        original_price: float,
        discount_rate: float,
    ) -> float:
        """割引後の価格を計算する。

        Args:
            original_price: 元の価格。
            discount_rate: 割引率。

        Returns:
            割引後の価格。

        Raises:
            ValueError: 価格が負数の場合。
        """
        if original_price < 0:
            raise ValueError("negative price")
        logger.info(f"discount: price={original_price}")
        return original_price * (1 - discount_rate)
'''
GOOD_TEST = '''"""calc のテスト。"""
from src.calc import PriceCalculator


def test_calculate_discount_price_valid_input_returns_discounted() -> None:
    """正常な入力で割引後の価格が返る。"""
    # Arrange
    calculator = PriceCalculator()

    # Act
    result = calculator.calculate_discount_price(1000.0, 0.2)

    # Assert
    assert result == 800.0
'''


def run(cmd, **kw):
    return subprocess.run([sys.executable, *map(str, cmd)], capture_output=True, text=True, **kw)


class Env(unittest.TestCase):
    """一時 HOME と一時ワークスペースを持つ共通基盤。"""

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.state = self.home / ".cline-harness"
        self.state.mkdir()
        (self.state / "home").write_text(str(ROOT))
        self.env = dict(os.environ, HOME=str(self.home))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def ctl(self, *args):
        return run([TASKCTL, "--root", self.ws, *args], env=self.env, cwd=self.ws)

    def hook(self, name, payload):
        data = {"hookName": name, "taskId": "task-1", "workspaceRoots": [str(self.ws)]}
        data.update(payload)
        cp = subprocess.run([sys.executable, str(ROOT / "hooks" / name)], input=json.dumps(data),
                            capture_output=True, text=True, env=self.env)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout)

    def pre(self, tool, params, **kw):
        return self.hook("PreToolUse", {"preToolUse": {"toolName": tool, "parameters": params}, **kw})

    def cmd_blocked(self, command, tool="execute_command"):
        return self.pre(tool, {"command": command})["cancel"]

    def new_task(self, profile="generic"):
        cp = self.ctl("new", "テスト", "--profile", profile, "--slug", "t")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return next((self.ws / "tasks").glob("*-t"))


class ShellRuleTests(Env):
    def test_heredoc_variants_blocked(self):
        for c in ["cat << 'EOF' > /tmp/script.sh\necho hi\nEOF",
                  "cat > /tmp/script.sh << 'EOF'\necho hi\nEOF",
                  "cat << EOF > /tmp/script.sh\necho hi\nEOF",
                  "cat > /tmp/script.sh << 'SCRIPTEOF'\necho hi\nSCRIPTEOF",
                  'python3 -c "\nimport os\nprint(1)\n"']:
            self.assertTrue(self.cmd_blocked(c), c)
        for c in ["bash /tmp/script.sh", "python3 -c \"print('ok')\"", "echo 'a<<b'", "python3 -c \"print(1<<3)\""]:
            self.assertFalse(self.cmd_blocked(c), c)

    def test_multiline_arguments_blocked(self):
        for c in ['git commit -m "fix: タイトル\n\n本文"', 'gh pr create --title "t" --body "## 概要\n説明"',
                  "curl -d '{\"key\": \"value\nwith\nnewlines\"}' https://example.com"]:
            self.assertTrue(self.cmd_blocked(c), c)
        for c in ["git commit -F /tmp/commit_msg.txt", 'git commit -m "fix: 変更内容の要約"',
                  'gh pr create --title "t" --body-file /tmp/pr_body.md', 'gh pr create --title "t" --body "1行の説明"']:
            self.assertFalse(self.cmd_blocked(c), c)

    def test_interactive_commands_blocked(self):
        for c in ["docker run -it ubuntu bash", "docker exec -it web sh", "git rebase -i HEAD~3", "git add -p", "vim a.txt",
                  "tail -f app.log", "git log --oneline", "git diff HEAD", "git show abc123", "apt-get install curl",
                  "pip uninstall requests", "npm init", "npx create-react-app app", "rm -i a.txt", "journalctl -u svc", "python3"]:
            self.assertTrue(self.cmd_blocked(c), c)
        for c in ["git --no-pager log --oneline", "git --no-pager diff HEAD", "apt-get install -y curl", "pip uninstall -y requests",
                  "npm init -y", "npx --yes create-react-app app", "docker build -t app .", "docker run -d nginx",
                  "journalctl -u svc --no-pager", "git status", "tail -n 50 app.log", "sed -i 's/a/b/' f.txt"]:
            self.assertFalse(self.cmd_blocked(c), c)

    def test_wait_in_chain_blocked(self):
        for c in ["sleep 5 & wait", "long_cmd & pid=$!; wait $pid", "wait"]:
            self.assertTrue(self.cmd_blocked(c), c)
        for c in ["sleep 5 && ls", "kill %1", "pkill -f server", "kubectl wait --for=condition=ready pod/x", "echo wait"]:
            self.assertFalse(self.cmd_blocked(c), c)

    def test_git_commit_rules(self):
        for c in ["git add .", "git add -A", "git add --all", "git commit -am 'fix: x'", "git commit -a -m 'fix: x'",
                  "git commit -m 'update various files'", "git commit -m 'WIP'"]:
            self.assertTrue(self.cmd_blocked(c), c)
        for c in ["git add src/a.py tests/test_a.py", "git commit -m 'fix: GCE startup script - remove exec redirect'",
                  "git commit -m 'docs: add CLINE.md with operation rules'", "git commit --amend --no-edit",
                  "git commit -m 'feat(api)!: breaking change'"]:
            self.assertFalse(self.cmd_blocked(c), c)

    def test_commit_message_file_checked(self):
        bad = self.ws / "msg_bad.txt"
        bad.write_text("update stuff\n\nbody", encoding="utf-8")
        good = self.ws / "msg_good.txt"
        good.write_text("fix: 要約\n\n本文", encoding="utf-8")
        self.assertTrue(self.cmd_blocked(f"git commit -F {bad}"))
        self.assertFalse(self.cmd_blocked(f"git commit -F {good}"))

    def test_large_commit_blocked(self):
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        for i in range(9):
            (self.ws / f"f{i}.txt").write_text("x")
        subprocess.run(["git", "add", "f0.txt", "f1.txt", "f2.txt", "f3.txt", "f4.txt", "f5.txt", "f6.txt", "f7.txt", "f8.txt"],
                       cwd=self.ws, check=True)
        self.assertTrue(self.cmd_blocked("git commit -m 'feat: many files'"))
        subprocess.run(["git", "reset", "-q", "f3.txt", "f4.txt", "f5.txt", "f6.txt", "f7.txt", "f8.txt"], cwd=self.ws, check=True)
        self.assertFalse(self.cmd_blocked("git commit -m 'feat: few files'"))

    def test_sdk_tool_names_supported(self):
        self.assertTrue(self.pre("run_commands", {"commands": ["cat << EOF > a\nx\nEOF"]})["cancel"])
        self.assertTrue(self.pre("run_commands", {"commands": [{"command": "git add ."}]})["cancel"])
        self.assertFalse(self.pre("run_commands", {"commands": ["ls"]})["cancel"])

    def test_tmp_redirect_allowed_while_gate_closed(self):
        t = self.new_task()
        # 計画未承認でも、ログを /tmp に保存して読む運用 (規則 7) は妨げない
        self.assertFalse(self.cmd_blocked("gcloud iam service-accounts list --project=x > /tmp/out.txt 2>&1; cat /tmp/out.txt"))
        self.assertFalse(self.cmd_blocked("bash /tmp/setup.sh > /tmp/result.txt 2>&1"))
        self.assertTrue(self.cmd_blocked(f"echo x > {self.ws}/src_a.txt"))
        self.assertFalse(self.pre("write_to_file", {"path": "/tmp/script.sh", "content": "echo hi"})["cancel"])
        self.assertFalse(self.pre("editor", {"command": "view", "path": f"{t}/spec.md"})["cancel"])


class ContextTests(Env):
    def setUp(self):
        super().setUp()
        (self.state / "context.json").write_text(json.dumps(
            {"window_tokens": 10000, "baseline_tokens": 0, "factor": 1.0}))

    def post(self, n_ascii_chars):
        return self.hook("PostToolUse", {"postToolUse": {"toolName": "read_file", "parameters": {"path": "x"},
                                                          "result": "a" * n_ascii_chars, "success": True}})

    def test_levels_fire_once_and_hard_stop_enforced(self):
        t = self.new_task()
        r = self.post(1000)
        self.assertNotIn("contextModification", r)
        r = self.post(17500)  # 約 5000 tokens = 50%
        self.assertIn("コンテキスト推定", r["contextModification"])
        self.assertNotIn("handoff.auto.md", r["contextModification"])
        self.assertNotIn("contextModification", self.post(100))  # 同じ段階では繰り返さない
        r = self.post(5250)  # 約 65%
        self.assertIn("引き継ぎ", r["contextModification"])
        self.assertTrue((t / "handoff.auto.md").exists())
        self.assertFalse(self.pre("read_file", {"path": "a.txt"})["cancel"])  # 65% ではまだ止めない
        self.post(5250)  # 約 80%
        blocked = self.pre("read_file", {"path": "a.txt"})
        self.assertTrue(blocked["cancel"])
        self.assertIn("handoff", blocked["errorMessage"])
        self.assertTrue(self.pre("execute_command", {"command": "ls"})["cancel"])
        # 引き継ぎ作業は許可される
        self.assertFalse(self.pre("new_task", {"context": "x"})["cancel"])
        self.assertFalse(self.pre("write_to_file", {"path": f"tasks/{t.name}/handoff.md", "content": "x"})["cancel"])
        self.assertFalse(self.cmd_blocked(f"python3 {TASKCTL} handoff"))
        # 別タスク (引き継ぎ先) は独立に数える
        self.assertFalse(self.pre("read_file", {"path": "a.txt"}, taskId="task-2")["cancel"])
        # ctx-off で解除できる
        (self.state / "ctx-off").write_text("")
        self.assertFalse(self.pre("read_file", {"path": "a.txt"})["cancel"])

    def test_japanese_counts_heavier_than_ascii(self):
        self.hook("PostToolUse", {"postToolUse": {"toolName": "read_file", "parameters": {}, "result": "あ" * 6000}})
        st = json.loads(next((self.state / "ctx").glob("task-1.json")).read_text())
        self.assertGreater(st["tokens"], 4000)

    def test_precompact_writes_checkpoint_and_resets(self):
        t = self.new_task()
        self.post(17500)
        self.post(5250)
        self.post(5250)
        r = self.hook("PreCompact", {"preCompact": {"contextSize": 123}})
        self.assertIn("圧縮", r["contextModification"])
        self.assertTrue((t / "handoff.auto.md").exists())
        self.assertFalse(self.pre("read_file", {"path": "a.txt"})["cancel"])  # 圧縮後は再び作業できる

    def test_taskstart_injects_summary_and_resets(self):
        t = self.new_task("coding")
        self.assertEqual(self.ctl("handoff").returncode, 0)
        r = self.hook("TaskStart", {"taskStart": {}})
        text = r["contextModification"]
        self.assertIn(t.name, text)
        self.assertIn("handoff.md", text)
        self.assertIn("profile-coding", text)
        r = self.hook("TaskStart", {"hookName": "TaskResume"})
        self.assertIn(t.name, r["contextModification"])
        # アクティブなタスクが無ければ何も注入しない
        (self.ws / "tasks/.active").unlink()
        self.assertEqual(self.hook("TaskStart", {}), {"cancel": False})

    def test_handoff_generation_check_and_memo_preserved(self):
        t = self.new_task()
        self.assertEqual(self.ctl("handoff").returncode, 0)
        cp = self.ctl("handoff", "--check")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("未記入", cp.stdout)
        text = (t / "handoff.md").read_text(encoding="utf-8")
        for sec in ("直近の判断と理由", "未解決の問い・懸念", "次の一手", "注意"):
            text = text.replace("{{" + sec + "を書く}}", f"{sec}の内容です。")
        (t / "handoff.md").write_text(text, encoding="utf-8")
        self.assertEqual(self.ctl("handoff", "--check").returncode, 0)
        # 再生成しても、記入済みのメモは保持され、自動部分だけ更新される
        self.assertEqual(self.ctl("handoff").returncode, 0)
        again = (t / "handoff.md").read_text(encoding="utf-8")
        self.assertIn("次の一手の内容です。", again)
        self.assertEqual(self.ctl("handoff", "--check").returncode, 0)
        self.assertIn("次の作業", again)


class CodingTests(Env):
    def make_project(self):
        (self.ws / "src").mkdir()
        (self.ws / "tests").mkdir()
        (self.ws / "src/calc.py").write_text(GOOD_PY, encoding="utf-8")
        (self.ws / "tests/test_calc.py").write_text(GOOD_TEST, encoding="utf-8")
        (self.ws / "plan.md").write_text(PLAN_CODING, encoding="utf-8")

    def check(self, *paths, plan=True):
        args = [CHECK_PY, *paths, "--root", self.ws, "--json"] + (["--plan", self.ws / "plan.md"] if plan else ["--no-modules"])
        cp = run(args, cwd=self.ws)
        return cp.returncode, [i for i in json.loads(cp.stdout or "[]")]

    def rules(self, *paths, **kw):
        _, issues = self.check(*paths, **kw)
        return {i["rule"] for i in issues if i["severity"] == "ERROR"}

    def test_good_code_passes(self):
        self.make_project()
        rc, issues = self.check("src/calc.py", "tests/test_calc.py")
        self.assertEqual(rc, 0, issues)

    def test_each_standard_is_detected(self):
        self.make_project()
        cases = {
            "PY-01": GOOD_PY.replace("import logging", "import logging\nimport json"),
            "PY-03": GOOD_PY.replace("class PriceCalculator", "class price_calculator"),
            "PY-04": GOOD_PY.replace("calculate_discount_price", "calculateDiscountPrice"),
            "PY-05": GOOD_PY.replace("TAX_RATE = 0.1", "tax_rate = 0.1"),
            "PY-08": re.sub(r'(-> float:\n)\s+""".*?"""\n', r"\1", GOOD_PY, flags=re.S),
            "PY-09": GOOD_PY.replace("        Returns:\n            割引後の価格。\n\n", ""),
            "PY-10": GOOD_PY.replace('    """価格を計算するクラス。"""\n\n', ""),
            "PY-11": GOOD_PY + "\n\nif TAX_RATE:\n  VALUE = 1\n",
            "PY-13": GOOD_PY.replace("\n\n\nclass PriceCalculator", "\nclass PriceCalculator"),
            "PY-14": GOOD_PY.replace("import logging\n", "from src.helpers import x\nimport logging\n"),
            "PY-15": GOOD_PY.replace("discount_rate: float,", "discount_rate,"),
            "PY-16": GOOD_PY.replace("rate: float = 0.1", "rate = 0.1"),
            "PY-21": GOOD_PY.replace("logger.info(", "print("),
            "PY-26": GOOD_PY.replace('        logger.info(f"discount: price={original_price}")\n',
                                     "        try:\n            pass\n        except:\n            pass\n"),
        }
        (self.ws / "src/helpers.py").write_text('"""h."""\n', encoding="utf-8")
        for rule, code in cases.items():
            (self.ws / "src/calc.py").write_text(code, encoding="utf-8")
            self.assertIn(rule, self.rules("src/calc.py"), rule)
        (self.ws / "src/calc.py").write_text(GOOD_PY.replace('"""価格計算モジュール。"""\nimport logging\n\nlogger = logging.getLogger(__name__)\n', '"""x."""\nimport logging\n'), encoding="utf-8")
        self.assertIn("PY-21", self.rules("src/calc.py"))  # logger の欠如

    def test_test_conventions(self):
        self.make_project()
        bad = GOOD_TEST.replace("test_calculate_discount_price_valid_input_returns_discounted", "test_discount")
        (self.ws / "tests/test_calc.py").write_text(bad, encoding="utf-8")
        self.assertIn("PY-19", self.rules("tests/test_calc.py"))
        no_aaa = GOOD_TEST.replace("    # Arrange\n", "").replace("    # Act\n", "")
        (self.ws / "tests/test_calc.py").write_text(no_aaa, encoding="utf-8")
        self.assertIn("PY-20", self.rules("tests/test_calc.py"))
        (self.ws / "tests/test_calc.py").unlink()
        self.assertIn("PY-19", self.rules("src/calc.py"))  # テストのないコード

    def test_perf_exception_and_line_length(self):
        self.make_project()
        long_line = "        value = " + " + ".join(["original_price"] * 6) + "  # long line to exceed the seventy-nine limit"
        body = GOOD_PY.replace("        return original_price * (1 - discount_rate)", long_line + "\n        return original_price * (1 - discount_rate)")
        (self.ws / "src/calc.py").write_text(body, encoding="utf-8")
        _, issues = self.check("src/calc.py")
        self.assertTrue(any(i["rule"] == "PY-12" for i in issues))
        noted = body.replace(long_line, "        # PERFORMANCE OPTIMIZATION: 理由\n" + long_line)
        (self.ws / "src/calc.py").write_text(noted, encoding="utf-8")
        _, issues = self.check("src/calc.py")
        self.assertFalse(any(i["rule"] == "PY-12" for i in issues))

    def test_coding_plan_gate_requires_modules_and_test_step(self):
        t = self.new_task("coding")
        self.assertIn("使用モジュール", (t / "plan.md").read_text())
        (t / "spec.md").write_text(SPEC, encoding="utf-8")
        self.assertEqual(self.ctl("approve", "spec", "--yes").returncode, 0)
        no_reason = PLAN_CODING.replace("| 誤差が出ない | float: 丸め誤差が出る |", "| | |")
        (t / "plan.md").write_text(no_reason, encoding="utf-8")
        out = self.ctl("gate", "plan").stdout
        self.assertIn("選定理由", out)
        no_test = PLAN_CODING.replace("テストを作る", "調べる")
        (t / "plan.md").write_text(no_test, encoding="utf-8")
        self.assertIn("テスト", self.ctl("gate", "plan").stdout)
        (t / "plan.md").write_text(PLAN_CODING, encoding="utf-8")
        self.assertEqual(self.ctl("gate", "plan").returncode, 0)

    def test_coding_result_gate_runs_checker(self):
        t = self.new_task("coding")
        self.make_project()
        (t / "spec.md").write_text(SPEC, encoding="utf-8")
        self.assertEqual(self.ctl("approve", "spec", "--yes").returncode, 0)
        (t / "plan.md").write_text(PLAN_CODING, encoding="utf-8")
        self.assertEqual(self.ctl("approve", "plan", "--yes").returncode, 0)
        (t / "progress.md").write_text("# P\n\n## ステップ進捗\n- S1: done | evidence: cmd: pytest => exit 0\n"
                                       "- S2: done | evidence: cmd: pytest => exit 0\n\n## 逸脱\nなし\n", encoding="utf-8")
        (t / "result.md").write_text("# R\n\n## 結果サマリ\n完了\n\n## 受け入れ条件の検証\n| AC | 判定 | 証拠 |\n|---|---|---|\n"
                                     "| AC1 | pass | cmd: check_python => exit 0 |\n\n## 残課題・限界\nなし\n", encoding="utf-8")
        out = self.ctl("gate", "result")
        self.assertEqual(out.returncode, 1)
        self.assertIn("scope.txt", out.stdout)
        (t / "scope.txt").write_text("src/calc.py\ntests/test_calc.py\n", encoding="utf-8")
        shutil.copy(self.ws / "plan.md", self.ws / "plan_unused.md")
        self.assertEqual(self.ctl("gate", "result").returncode, 0, self.ctl("gate", "result").stdout)
        (self.ws / "src/calc.py").write_text(GOOD_PY.replace("logger.info(", "print("), encoding="utf-8")
        bad = self.ctl("gate", "result")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("PY-21", bad.stdout)

    def test_hook_requires_coding_skill_before_writing_code(self):
        blocked = self.pre("write_to_file", {"path": "src/a.py", "content": "x"})
        self.assertTrue(blocked["cancel"])
        self.assertIn("profile-coding", blocked["errorMessage"])
        self.assertTrue(self.pre("write_to_file", {"path": "src/a.ts", "content": "x"})["cancel"])
        self.assertTrue(self.pre("editor", {"command": "create", "path": "src/a.tsx"})["cancel"])
        # 作業ディレクトリ外の一時スクリプトと、コード以外のファイルは対象外
        self.assertFalse(self.pre("write_to_file", {"path": "/tmp/script.py", "content": "x"})["cancel"])
        self.assertFalse(self.pre("write_to_file", {"path": "docs/readme.md", "content": "x"})["cancel"])
        # skill を読み込むと許可される (use_skill でも、SKILL.md の read でもよい)
        self.assertFalse(self.pre("use_skill", {"skill_name": "profile-coding"})["cancel"])
        self.assertFalse(self.pre("write_to_file", {"path": "src/a.py", "content": "x"})["cancel"])
        # 引き継ぎ先 (別 taskId) では、読み込み直しが必要
        self.assertTrue(self.pre("write_to_file", {"path": "src/a.py", "content": "x"}, taskId="task-2")["cancel"])
        self.assertFalse(self.pre("read_file", {"path": str(ROOT / "skills/profile-coding/SKILL.md")}, taskId="task-2")["cancel"])
        self.assertFalse(self.pre("write_to_file", {"path": "src/a.py", "content": "x"}, taskId="task-2")["cancel"])


if __name__ == "__main__":
    unittest.main()
