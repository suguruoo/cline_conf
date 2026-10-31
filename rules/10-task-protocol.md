# タスクプロトコル

非自明な作業 (調査レポート、設計、ドキュメント作成、複数ファイルにまたがる実装) は、`/tasks.md` ワークフローで
**spec → plan → progress → result** の 4 段階で進める。単発の質問・数行の修正・雑談には適用しない。

- 状態は作業ディレクトリの `tasks/<task-id>/` に置く。`tasks/.active` が現在のタスク。
- spec / plan / result は **人間の承認** が要る。承認は人間が `taskctl approve` で行う。あなたは approve / reopen を実行しない。
  `approvals.json` と `tasks/.active` を直接編集しない。
- 次の段階へ進む前に `taskctl gate <stage>` を実行し、PASS を確認する。FAIL のまま進めない。
- plan が承認されるまで、`tasks/<id>/` の `spec.md` `plan.md` `notes.md` `scratch/` `handoff*.md` 以外には書き込まない (hook が拒否する)。
  /tmp などワークスペース外への出力 (ログ・一時ファイル) は制限しない。
- plan に無い作業や方針変更が必要になったら、**作業を止めて** progress.md に `### D1: …` を起票し、人間の承認を待つ。
- 完了と言う前に、証拠 (ファイル・コマンド結果) を result.md に残す。「できました」だけで済ませない。
- 詳細・書式は skill `task-protocol` を使う。領域別の基準は `profile-*` skill (調査レポートは `profile-research-report`)。
