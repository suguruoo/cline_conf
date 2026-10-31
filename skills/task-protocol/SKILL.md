---
name: task-protocol
description: 非自明な作業（調査レポート、設計、ドキュメント作成、実装など）を spec → plan → progress → result の4段階で進める共通プロトコル。タスクの作成・再開、各段階の書式、ゲート検証(taskctl gate)、人間の承認、plan からの逸脱の扱いが必要なときに使う。/tasks ワークフローから呼ばれる。
---

# task-protocol

状態はすべて `tasks/<task-id>/` のファイルに置く。会話が途切れても、拡張機能 ↔ CLI を行き来しても、ファイルから再開できる。
`taskctl` = `python3 <harness>/skills/task-protocol/scripts/taskctl.py` (作業ディレクトリで実行)。

## 段階と責務

| 段階 | ファイル | 誰が通すか | 内容 |
|---|---|---|---|
| spec | `spec.md` | gate + **人間の承認** | 目的、スコープ/非目標、受け入れ条件 (AC)、前提・制約、未確定事項 |
| plan | `plan.md` | gate + **人間の承認** | 方針、ステップ (各 AC を担当)、リスクと手戻り点 |
| progress | `progress.md` | gate (自動) + 逸脱時のみ人間 | ステップごとの進捗と証拠、逸脱 |
| result | `result.md` | gate + **人間の承認** | 全 AC の判定と証拠、残課題・限界 |

## 書式 (gate が機械的に検査する)

- **AC**: `- AC1: 条件 ｜検証: 確認方法`。検証方法が無い AC は不可。曖昧語 (「適切に」「十分に」) は避け、観測できる条件にする。
- **ステップ**: `- [ ] S1: 内容 (covers: AC1, AC2)`。すべての AC がいずれかのステップに割り当たること。
- **進捗**: `- S1: todo|in-progress|done|blocked | evidence: パス; cmd: コマンド => exit 0`。
  done には証拠が必須。パスは実在するファイル。コマンドは `cmd:` で始める。
- **逸脱**: `### D1: 題名` の下に内容・理由・影響する AC。起票したら **作業を止める**。
- **結果**: 表 `| AC1 | pass | 証拠 |` を全 AC について。判定は pass / fail / waived。fail は承認できない。
- `{{…}}` のプレースホルダが残っていると FAIL。HTML コメント `<!-- -->` は検査対象外。

詳細な書き方と良い例・悪い例は [docs/stage-guide.md](docs/stage-guide.md)。

## 手順

1. 新規: `taskctl new "<タイトル>" --profile <generic|research-report|docs|architecture|coding>`。再開: `taskctl status`。
2. 各段階のファイルを書く → `taskctl gate <stage>` → FAIL なら指摘を直して再実行。
3. spec / plan / result は PASS 後に人間へ承認を依頼して **停止**。承認は人間が `taskctl approve <stage>`。
4. 承認後に本文を変えると承認は失効する (stale)。変えたら再承認を依頼する。
5. 完了: result 承認後 `taskctl done`。

## 守ること

- あなたは `approve` / `reopen` / `active --clear` を実行しない。`approvals.json` と `tasks/.active` を編集しない。
- plan 承認までは `spec.md` `plan.md` `notes.md` `scratch/` 以外に書かない。
- 領域別の基準がある場合は `profile-<領域>` skill に従う (例: `profile-research-report`)。

## Phase 0 確認用 (確認後に削除してよい)

ユーザーが「task-protocol の確認」と言ったら `SKILL-TASK-PROTOCOL-OK` と答える。
