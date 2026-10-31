# cline-harness

Cline (VS Code 拡張 / CLI) 用の個人向けハーネス。  
**「何を作るか」を決めてから動かす** ための仕組みを、hooks・rules・skills の三層で実現します。

---

## これは何か

Cline にそのまま作業させると、途中で方向転換したり、承認なしに本番ファイルを書き換えたり、コンテキストが溢れても気づかないまま壊れた判断を続けることがあります。

このハーネスは次の 3 つの問題を解決します。

| 問題 | 解決策 |
|---|---|
| 「何を作るか」が曖昧なまま実装が走る | **spec → plan → progress → result** の 4 段階プロトコルで、各段階に人間の承認を挟む |
| 危険な操作を止められない | **hooks** が `rm -rf ~` / 強制 push / ヒアドキュメント / `git add .` などをリアルタイムで拒否する |
| コンテキストが溢れて判断が壊れる | **コンテキスト監視** がトークンを推定し、65% 超で自動的に引き継ぎファイルを生成する |

---

## 全体構成

```
.cline/
├── rules/          Cline が常時読む薄いルール集
├── workflows/      タスク開始・再開・レビューの手順書
├── hooks/          ツール実行前後に走る Python スクリプト
├── skills/         タスク種別ごとの詳細ガイド + lint スクリプト
│   ├── shared/         複数 skill が共有するユーティリティ
│   ├── task-protocol/  共通プロトコル (taskctl CLI)
│   ├── profile-coding/        Python / TypeScript 規約
│   ├── profile-docs/          ドキュメント作成規約
│   ├── profile-research-report/  Web 調査レポート規約
│   └── profile-architecture/  ADR 形式のアーキテクチャ設計規約
├── agents/         サブエージェント定義 (code-reviewer など)
└── tests/          回帰テスト (52 件)
```

---

## 三層のしくみ

### 層 1 — rules (常時ロード)

Cline が毎回読み込む 6 つの薄いルールファイル。

| ファイル | 内容 |
|---|---|
| `00-principles.md` | 日本語応答・根拠明示・破壊的操作の禁止 |
| `10-task-protocol.md` | spec→plan→progress→result の使い方 |
| `20-safety.md` | 削除・本番反映・強制 push の確認必須 |
| `30-shell-and-git.md` | ヒアドキュメント禁止・`git add .` 禁止・コミット単位など |
| `35-context-handoff.md` | コンテキスト 50%/65%/80% 時の引き継ぎ手順 |
| `40-coding.md` | コード編集前に skill `profile-coding` を読む必須ルール |

### 層 2 — hooks (自動ガード)

ツール実行のたびに走る Python スクリプト群。**モデルが意図的に回避しない限り止められます。**

```
PreToolUse ─── ① コンテキスト超過チェック (80% 超 → 引き継ぎ以外を拒否)
               ② シェル規則違反 (heredoc / git add . / git commit -a など)
               ③ 破壊的コマンド (rm -rf ~ / sudo / 強制 push / terraform destroy など)
               ④ タスクプロトコル (plan 承認前はタスク領域外への書き込みを拒否)
               ⑤ コーディング規約 (profile-coding 未読み込みなら .py/.ts/.tsx 書き込みを拒否)

PostToolUse ── コンテキストトークン推定値を加算

PreCompact ─── コンテキスト圧縮前に handoff.auto.md を自動生成

TaskStart ──── タスク開始時にアクティブタスクの要約を Cline のコンテキストに注入
```

**ブロックされる操作の例:**

```bash
# ❌ これらは PreToolUse に拒否される
rm -rf ~
git add .
git push --force origin main
cat << EOF > file.txt    # ヒアドキュメント
sudo apt install xxx
terraform destroy
```

### 層 3 — skills (タスク別ガイド)

`/tasks.md` を実行すると Cline が領域を判定し、対応する skill を読み込みます。

| 起動条件 | skill | 機械検査スクリプト |
|---|---|---|
| Web 調査・リサーチ | `profile-research-report` | `lint_report.py` (引用照合・和英スペース・表 JSON など 20+ ルール) |
| コーディング | `profile-coding` | `check_python.py` (PY-01〜26) / `check_ts.py` (ESLint + Prettier) |
| ドキュメント作成 | `profile-docs` | `lint_doc.py` (プレースホルダ・和英スペース・絵文字) |
| アーキテクチャ設計 | `profile-architecture` | `lint_adr.py` (ADR 必須フィールド検査) |
| その他 | `task-protocol` (共通) | `taskctl gate` (書式・網羅性) |

---

## タスクの流れ

```
Cline で /tasks.md を実行
        │
        ▼
① spec  ── 目的・AC・前提を書く → taskctl gate spec → 人間が承認
        │
        ▼
② plan  ── ステップ・使用モジュール・リスクを書く → taskctl gate plan → 人間が承認
        │   (ここで plan が承認されると、タスク領域外への書き込みが解放される)
        ▼
③ progress ── ステップを実行 → 1 ステップごとに progress.md に証拠を書く
        │      逸脱が必要なら D1 を起票して停止 → 人間が承認
        ▼
④ result ── AC の判定と証拠 → taskctl gate result → 人間が承認 → taskctl done
```

**人間だけが実行するコマンド:**

```bash
taskctl approve spec     # spec の承認
taskctl approve plan     # plan の承認 (= 使用モジュールの承認)
taskctl approve result   # result の承認
taskctl approve D1       # 逸脱の承認
taskctl done             # タスクを閉じる
```

**Cline が実行するコマンド:**

```bash
taskctl status           # 現在のタスクと承認状態を確認
taskctl gate spec        # spec の書式・網羅性を検査
taskctl gate plan        # plan の検査
taskctl gate progress    # progress の検査
taskctl gate result      # result の検査 (lint も実行される)
taskctl handoff          # 引き継ぎファイルを生成
```

---

## セットアップ

```bash
# taskctl を PATH に追加
ln -sf ~/.cline/skills/task-protocol/scripts/taskctl.py /opt/homebrew/bin/taskctl

# hooklib / tasklib を Python から import できるようにする
echo ~/.cline/skills/task-protocol/scripts > \
  ~/Library/Python/3.x/lib/python/site-packages/cline-harness.pth
```

Cline の設定で以下の hooks を登録する (VS Code 設定または Cline の Hooks 設定画面):

| イベント | スクリプト |
|---|---|
| PreToolUse | `~/.cline/hooks/PreToolUse` |
| PostToolUse | `~/.cline/hooks/PostToolUse` |
| PreCompact | `~/.cline/hooks/PreCompact` |
| TaskStart | `~/.cline/hooks/TaskStart` |

---

## 機械検査スクリプト一覧

すべて**標準ライブラリのみ**で動作します。

| スクリプト | 場所 | 主な検査内容 |
|---|---|---|
| `taskctl.py` | `skills/task-protocol/scripts/` | spec/plan/progress/result の書式・網羅性 |
| `check_python.py` | `skills/profile-coding/scripts/` | Python 規約 PY-01〜26 (型ヒント・命名・docstring など) |
| `check_ts.py` | `skills/profile-coding/scripts/` | ESLint + Prettier (npx 経由、未インストールは graceful skip) |
| `lint_report.py` | `skills/profile-research-report/scripts/` | 引用照合・和英スペース・表 JSON・絵文字など 20+ ルール |
| `lint_doc.py` | `skills/profile-docs/scripts/` | プレースホルダ残留・和英スペース・絵文字 |
| `lint_adr.py` | `skills/profile-architecture/scripts/` | ADR 必須フィールド (h1・ステータス・コンテキスト・決定内容・結果) |
| `ledger.py` | `skills/profile-research-report/scripts/` | 調査ソースの台帳登録・スナップショット取得 |
| `lint_utils.py` | `skills/shared/` | 上記 lint が共有するユーティリティ (和英スペース・フェンス解析など) |

---

## テスト

```bash
cd ~/.cline
python3 -m unittest discover -s tests -v
# → 52 tests OK (1 skipped: mmdc 未導入)
```

---

## 設計上の取り決め

- **承認はハッシュで記録する。** 承認後に spec/plan の本文を変えると自動的に失効し、再承認まで書き込みが止まる。frontmatter の `status` 変更は失効しない。
- **hooks は速度制限 + 監査であり、完全な防御ではない。** モデルが任意スクリプトを直接実行した場合は検出できない。
- **コンテキスト使用量は推定値。** 文字数ベースで積算しているため実際の Cline 表示とずれることがある。`~/.cline-harness/context.json` で窓幅・補正係数を調整する。

---

## 限界

- hook の有効化方法 (ファイル配置 / SDK 方式) はバージョンで変わりうる。
- lint は形式と照合のみ。事実の正確性・日本語の自然さ・結論の妥当性はアノテーションチェック (人間の承認) に依存する。
- TypeScript の `check_ts.py` は `npx` が必要。未インストール環境では WARN を出して skip する。

