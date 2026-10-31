# /tasks — タスクの開始・再開

以降、`taskctl` は `python3 ~/cline-harness/skills/task-protocol/scripts/taskctl.py` を指す (インストール場所が違う場合は `~/.cline-harness/home` の内容を基準にする)。
コマンドは作業ディレクトリ (ワークスペースのルート) で実行する。

## 0. 状態の確認
1. `taskctl active` を実行する。
2. アクティブなタスクがあれば、`tasks/<id>/handoff.md` (無ければ `handoff.auto.md`) と `progress.md` を読み、`taskctl status` を実行する。
   引き継ぎ (コンテキスト切れ) からの再開なら、確認なしでそのタスクを再開する。そうでなければ「再開するか、新規にするか」をユーザーに確認する。
   再開する場合は、該当する段階 (多くは 4) へ進む。coding のタスクなら skill `profile-coding` を読み込み直す。

## 1. 新規タスクの作成
1. 依頼内容から領域を判定する: `research-report` (Web 調査レポート) / `docs` / `architecture` / `coding` / `generic`。迷う場合はユーザーに確認する。
2. `taskctl new "<タイトル>" --profile <領域>` を実行する。
3. skill `task-protocol` と、領域に対応する `profile-<領域>` skill があれば使う。

## 2. spec (Plan モード)
1. `tasks/<id>/spec.md` を書く。依頼文はそのまま保存し、曖昧な点は「未確定事項」に書いてユーザーに質問する。
2. `taskctl gate spec` が PASS になるまで直す。
3. 内容を要約してユーザーに示し、承認を依頼して **停止する**。承認はユーザーが `taskctl approve spec` で行う。

## 3. plan (Plan モード)
1. spec の承認を確認 (`taskctl status`)。`tasks/<id>/plan.md` を書く。全ての AC をいずれかのステップに割り当てる。
2. `taskctl gate plan` が PASS になるまで直す。ユーザーに承認を依頼して **停止する** (`taskctl approve plan`)。

## 4. progress (Act モード)
1. plan が承認済みであることを確認する。plan のステップ順に作業し、1 ステップ終えるごとに `progress.md` を更新する (done には証拠が必須)。
2. 区切りごとに `taskctl gate progress` を実行する。
3. plan に無い作業が必要になったら、作業を止めて `### D1: …` を起票し、ユーザーに承認を依頼する (`taskctl approve D1`)。
4. 全ステップが done になったら `taskctl gate progress --complete`。

## 5. result
1. `result.md` を書く (全 AC の判定と証拠)。領域別の最終検証を行う (調査レポートなら lint とアノテーションチェック)。
2. `taskctl gate result` が PASS になったら、ユーザーに承認を依頼して **停止する** (`taskctl approve result`)。
3. 承認後に `taskctl done` を実行してタスクを閉じる。

## 共通
- gate が FAIL のときは、メッセージの指摘を直して再実行する。同じ指摘で 3 回失敗したら、止めて状況を報告する。
- hook に拒否されたら、回避せず理由をユーザーに伝える。
