# cline-harness (Phase 0 + Phase 1 + 運用規則・コンテキスト引き継ぎ・コーディング)

Cline (VS Code 拡張 / CLI) 用の個人向けハーネス。共通プロトコル **spec → plan → progress → result** に、
領域別プロファイルを差し替える構成。実装済み: 共通プロトコル、**リサーチレポート**、**コーディング** (Python 規約の機械検査)、シェル/Git 運用規則の強制、コンテキスト監視と引き継ぎ。

```
cline-harness/
├── rules/            常時ロード (薄く): 00-principles / 10-task-protocol / 20-safety / 30-shell-and-git / 35-context-handoff / 40-coding
├── workflows/        tasks.md (開始・再開と各段階) / review.md (コードレビュー)
├── skills/
│   ├── task-protocol/    共通プロトコル (taskctl, tasklib, テンプレ, 書き方ガイド)
│   ├── profile-coding/   コーディング (check_python.py, 規約 PY-01〜, レビュー観点, plan テンプレ)
│   └── profile-research-report/  調査レポート (lint_report, ledger, テンプレ, 規則, アノテーションチェック)
├── hooks/            PreToolUse (ゲート強制・シェル規則・コンテキスト上限・コーディング skill 強制)
│                     PostToolUse (コンテキスト推定の加算) / PreCompact (圧縮前の退避) / TaskStart (引き継ぎの注入。TaskResume 兼用)
├── install.sh        ~/Documents/Cline/{Rules,Workflows,Hooks} と ~/.cline/skills に配置
├── docs/PHASE0-smoke-test.md   実機確認の手順 (最初にこれ)
└── tests/            回帰テスト (python3 -m unittest discover -s tests)
```

タスクの状態は作業ディレクトリの `tasks/<task-id>/` に置く:
`spec.md plan.md progress.md result.md approvals.json task.json notes.md scratch/` (+ 調査レポートは `deliverables/ sources/ ledger.json annotations.md`)。

## 使い方

```bash
./install.sh                      # 配置 (既存は上書きしない / --copy / --dry-run / --uninstall)
alias taskctl='python3 ~/cline-harness/skills/task-protocol/scripts/taskctl.py'
```

Cline で `/tasks.md` を実行 → 領域を選ぶ → spec を書かせる → 人間が承認:

```bash
taskctl status                   # 現在のタスクと承認状態
taskctl gate spec                # 機械検査 (Cline も実行する)
taskctl approve spec             # 人間だけが実行 (plan / result / 逸脱 D1 も同様)
taskctl done                     # result 承認後に閉じる
```

## 設計上の取り決め

- **承認は本文のハッシュで記録**する。承認後に spec/plan を変えると失効 (stale) し、再承認まで書き込みが止まる。frontmatter の status 変更では失効しない。
- **progress は自動検査 + 逸脱時のみ人間承認**。done には証拠 (実在パスか `cmd:`)、plan に無いステップは逸脱として起票。
- **ゲートは hook と workflow の二段**: hook = plan 承認までタスク領域外への書き込みを拒否、workflow 内の gate = 書式と網羅性の検証。
- **レポートの引用は台帳で照合**: スクリプトが取得した本文に対して原文引用を検証する。一次/二次・独立性 (origin) も台帳で判定する。
- 規則と lint ID の対応は `skills/profile-research-report/docs/report-rules.md`。許可絵文字などは `scripts/config.json`。

## 運用規則・コンテキスト・コーディング

- **シェル/Git 規則 (rules/30)**: ヒアドキュメント・複数行引数・`python -c` の複数行・対話コマンド・`wait`・`git add .`/`commit -a`・
  形式違反のコミットメッセージ・9 ファイル以上のコミットを PreToolUse が拒否する。ログは `> /tmp/x.txt 2>&1` で保存して読む (/tmp は常に許可)。
- **コンテキスト監視 (rules/35)**: PostToolUse がトークンを **推定** し、50% で警告、65% で `handoff.auto.md` を自動生成して引き継ぎを促し、
  80% を超えると引き継ぎ作業以外を拒否する。閾値・窓幅は `~/.cline-harness/context.json`、解除は `~/.cline-harness/ctx-off`。
  `taskctl handoff` で `handoff.md` を作り「引き継ぎメモ」を記入、`--check` で検査。新規タスクの TaskStart/TaskResume が要約を注入する。
- **コーディング (rules/40)**: コードを書く前に skill `profile-coding` の読み込みを hook が要求する。plan に「使用モジュール」表
  (用途・選定理由・却下した代替) とテスト手順を必須とし、result ゲートで `check_python.py` を実行する。TypeScript は自動検査の対象外 (レビュー観点のみ)。

## 限界 (正直に)

- **コンテキスト使用量は実測ではなく推定** (文字数ベース)。実際の Cline 表示と比べて `context.json` を補正すること。ずれが大きいと早すぎる/遅すぎる停止になる。
- **hook 方式の不確実性**: ここでは従来のスクリプト hook (`PreToolUse` 等のファイル) を前提にしている。使用中のバージョンが SDK/プラグイン方式 (`beforeTool` 等) のみなら、
  各 hook は JSON 入出力の単体スクリプトなので薄いラッパで包めばよい。Phase 0 §5 で確定する。

- hook は **速度制限 + 監査** であり、完全な防御ではない。モデルが任意のスクリプトを実行して書き込む場合は検出できない。
  承認の改ざんは、直接編集とコマンドの両方を拒否しているが、迂回の余地はゼロではない (承認ファイルはハッシュで検証されるため、本文を差し替えた承認は失効する)。
- hook の仕様 (ツール名・パラメータ・命名規則・有効化) は Phase 0 の実機確認で確定する。バージョンで変わりうる。
- lint は形式と照合のみ。事実の正確性・日本語の自然さ・結論の妥当性・図の要否は、アノテーションチェック (LLM + 人間の承認) に依存する。
- Web 検索ツールは、プロバイダが Bedrock の場合に Cline 標準で使えるかが未確認 (Phase 0 §7)。

## 次のフェーズ

| Phase | 内容 |
|---|---|
| 2 | `profile-docs` (和英スペース等の lint を共有)。lint の共通部分を切り出す |
| 3 | `profile-architecture` (ADR 形式)、reviewer サブエージェント、`.cline/agents/` の形式確認 |
| 4 | 代表タスクによる回帰テスト (ハーネス自体のテスト)。`profile-coding` は前倒しで実装済み (TypeScript の自動検査は未実装) |
