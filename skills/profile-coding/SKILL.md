---
name: profile-coding
description: コードを書く・修正する・レビューするときに必ず使うコーディング規約と手順。Python (PEP 8 / PEP 257 / Google スタイル、命名、型ヒント、Google スタイル docstring、ログ、テスト AAA)、使用モジュールの事前承認、TypeScript (ESLint + Prettier)、コードレビューのチェックリストを含む。実装・リファクタ・コードレビュー・テスト作成の依頼で使う。
---

# profile-coding

コードを書く前・レビューする前に、この skill を読み込む (読み込まないと、`.py` / `.ts` / `.tsx` への書き込みは hook に拒否される)。
`<S>` = `<harness>/skills/profile-coding/scripts`。タスクは `taskctl new "<題>" --profile coding` で作る。

## 実装の手順

1. [docs/coding-standards.md](docs/coding-standards.md) を読む (規約 1〜28)。
2. **plan.md に『使用モジュール』表を書く**: import する全モジュールについて、用途・選定理由・他の選択肢と却下理由。
   承認 (`taskctl approve plan`) が、そのモジュールの使用許可になる。承認なしに import しない。
3. **テストを先に (または同時に) 作る**: `test_<module>.py`、関数名は `test_[機能]_[条件]_[期待結果]`、AAA コメント。テストのないコードは作らない。
4. 実装する: 型ヒント必須、Google スタイル docstring、`logger = logging.getLogger(__name__)`、`print` 禁止、具体的な例外。
5. 検査対象のパスを `tasks/<id>/scope.txt` に 1 行ずつ書き (例: `src/calc.py`、`tests/test_calc.py`)、実行する:
   `python3 <S>/check_python.py $(cat tasks/<id>/scope.txt) --plan tasks/<id>/plan.md --root .`
   ERROR を 0 にする。WARN は直すか、例外の理由をコメントに残す。
6. 動作確認 (テスト実行) が取れたら **すぐコミット** (rules の git 規則に従う)。
7. `taskctl gate result` は scope.txt の対象に check_python を実行する。TypeScript は ESLint / Prettier の結果を証拠に書く。

## レビューの手順

[docs/review-checklist.md](docs/review-checklist.md) に従う。機械検査 (check_python) → 機械検査できない項目の確認 → 規約の項番つきで重大度順に報告。

## 未承認モジュールが必要になったら

作業を止め、progress.md に `### D1: 使用モジュール <名前> の追加` を起票する (用途・選定理由・他の選択肢と却下理由を書く)。
承認 (`taskctl approve D1`) が出るまで import しない。承認後、plan.md の表にも追記する (plan の再承認が必要になる)。

## 規約が機械検査できる範囲

`check_python.py` は規約 1, 3〜5, 7〜17, 19〜21, 25, 26 を検査する。命名の分かりやすさ・コメントの質・例外選択の妥当性などはレビューで確認する。
作業用の一時スクリプト (`/tmp` など作業ディレクトリ外) は、この規約の対象外。
