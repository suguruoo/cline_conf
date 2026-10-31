# /review — コードレビュー

1. skill `profile-coding` を読み込む (use_skill)。`docs/review-checklist.md` を読む。
2. 対象 (ファイル・ディレクトリ・差分) をユーザーに確認する。差分は `git --no-pager diff` / `git --no-pager show <rev>` で取得する (出力は `> /tmp/review_diff.txt 2>&1` に保存して読む)。
3. Python は機械検査を実行し、結果を /tmp に保存して読む:
   `python3 <harness>/skills/profile-coding/scripts/check_python.py <対象> --no-modules --root . > /tmp/check.txt 2>&1; cat /tmp/check.txt`
   (承認済みの plan.md があるタスクのレビューなら `--plan tasks/<id>/plan.md` を使い、`--no-modules` は付けない)。
4. checklist の「機械検査では分からない項目」を、対象を `read_file` で 1 ファイルずつ読んで確認する。
5. 指摘を、規約の項番・重大度 (high / medium / low)・箇所・問題・根拠・修正案の形で、重大度順に報告する。
6. 修正が必要なら、ユーザーの承認を得て実施する (`/tasks.md` のタスクとして進める)。レビューだけの依頼ではコードを変更しない。
