# シェル操作と git (必須。違反は hook が拒否する)

1. **heredoc を使わない**: `cat << 'EOF' > f`、`cat > f << EOF` など全て禁止。ファイルは `write_to_file` で作成し、`bash /tmp/script.sh` で実行する。
   複数行の `python3 -c` も禁止 (1 行の短い `python3 -c "…"` は可。長くなるならファイルに書く)。
2. **コマンド引数に改行を含む文字列を渡さない**: `git commit -m "複数行…"`、`gh pr create --body "## …"`、`curl -d '{…改行…}'` は禁止。
   `write_to_file` で /tmp にファイルを作り、`git commit -F /tmp/commit_msg.txt` / `gh pr create --body-file /tmp/pr_body.md` で渡す。
3. **対話コマンドを避ける**: `-it` / `--interactive` が要るもの、`git rebase -i`、`git add -p`、エディタ・ページャー、`tail -f` は使わない。
   ページャーが開くものは `git --no-pager log` のように `--no-pager`。確認が出るものは `-y` / `--yes` (スクリプトの `[y/N]` も `--yes` を付けて実行)。
4. **`wait` をコマンドチェーンに含めない** (`&` と組み合わせると Ctrl+C が効かず固まる)。バックグラウンドのプロセスは `kill %1` / `pkill` で明示的に止め、
   長い処理は `sleep N && 確認コマンド` で待って結果だけ見る。
5. **コミットは小さく、意味のある単位で**: 1 機能・1 修正 = 1 コミット。`git add <ファイル>` で個別に指定 (`git add .` / `-A` / `git commit -a` は禁止)。
   動作確認が取れたら即コミット。無関係な変更を混ぜない。メッセージは `type: 変更内容の要約` (例: `fix: GCE startup script - remove exec redirect`、
   `docs: add CLINE.md with operation rules`。`update various files` は不可)。
6. **障害調査は、必ずサーバー側のログの確認から始める** (Cloud Logging / CloudWatch / サービスのログ / シリアルポート出力など)。
   ログで事実を確認し、記録してから仮説を立てる。クライアント側の推測から始めない。
7. **出力はファイルにリダイレクトして読む** (出力が取得できないことがあるため):
   `gcloud iam service-accounts list --project=xxx > /tmp/out.txt 2>&1; cat /tmp/out.txt`。
   複雑なら `write_to_file` で /tmp/setup.sh を作り、`bash /tmp/setup.sh > /tmp/result.txt 2>&1` → `cat /tmp/result.txt`。
8. **多数のファイルを 1 つのスクリプトで一気に読まない** (長時間 thinking のまま固まる)。ファイルは `read_file` で 1 つずつ読む。
   大きな分析は `use_subagents` (読み取り専用) に委譲するか、スクリプトを小分けにして段階的に実行する。

作業用の一時ファイルは `/tmp` に置く (作業ディレクトリを汚さない)。hook に拒否されたら、回避せず、拒否理由に沿ったやり方に直す。
