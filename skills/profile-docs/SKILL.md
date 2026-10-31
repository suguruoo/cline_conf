---
name: profile-docs
description: ドキュメント (設計書・手順書・README 等) を作成するときの手順と検証基準。和英スペース・Markdown 構造・プレースホルダ残留の lint を含む。ドキュメント作成・更新の依頼で使う。task-protocol と併用する。
---

# profile-docs

`taskctl new "<題>" --profile docs` で作ったタスクの中で使う。
`<S>` = `<harness>/skills/profile-docs/scripts`。

## 手順

1. テンプレート (`templates/doc.md`) を `deliverables/<名前>.md` にコピーして書く。
2. lint を実行し **エラー 0** になるまで直す:
   `python3 <S>/lint_doc.py deliverables/<名前>.md`
3. result の証拠に lint の終了コード 0 を記載する。

## lint_doc.py が検査する内容

| ルール ID | 内容 |
|---|---|
| STRUCT-0 | 未記入プレースホルダ `{{...}}` が残っている |
| STRUCT-0 | 閉じられていないコードフェンス |
| SPACE-1 | 日本語と英数字の間に半角スペースがない |
| EMOJI-1 | 絵文字の種類が多すぎる (デフォルト 15 種超) |
| EMOJI-2 | 許可リスト外の絵文字 |

## 規則の要点

- 日本語と英数字の間には半角スペースを入れる (`（）、。` の隣は不要)。
- 絵文字は許可リスト (lint_utils のデフォルト 14 種) のみ。
- `{{...}}` のプレースホルダを残したままコミットしない。
