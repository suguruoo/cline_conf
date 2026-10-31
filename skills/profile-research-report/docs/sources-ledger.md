# 証拠台帳 (ledger)

`tasks/<id>/ledger.json` と `tasks/<id>/sources/N.txt`。レポートが引用する全ソースをここに登録する。

## なぜ必要か

- 引用 (原文のまま) が **本当に原文にあるか** を、モデルの記憶ではなくスクリプトが取得した本文で照合するため。
- 一次/二次、独立性 (origin) をレポートの記述ルールと機械的に突き合わせるため。

## 登録

```
python3 <S>/ledger.py add <task> --url https://… --title "ページタイトル" --site "サイト名" --tier primary
```

- 本文はスクリプトが取得して `sources/N.txt` に保存する。取得できなければ次のどちらか:
  - `--from-file 本文.txt` (ブラウザやツールで得た本文を保存して渡す。PDF は `pdftotext` の出力など)
  - `--unverified --note "理由"` (本文なしで登録。引用の照合ができないため、レポートでは「未検証」と明記する)
- 同じ URL の再登録は `--replace`。一覧は `ledger.py list <task>`。

## tier の定義

| tier | 該当するもの |
|---|---|
| primary | 公式ドキュメント、公式発表・リリースノート、原論文、法令・規格、一次データ (統計の原表、ソースコード、公式 API の応答) |
| secondary | 解説記事、ブログ、ニュース、まとめ、書籍による紹介、他者の引用・翻訳 |

迷ったら secondary にする。一次ソースを引用している二次記事は、元の一次ソースを探して登録する。

## origin (独立性)

- 既定はドメイン名。**同じ情報源に由来するソースは同じ origin にする** (転載・通信社配信・同じ原典の孫引き)。
- 「複数のエビデンス」と数えてよいのは、origin が異なるソースが 2 件以上あるとき。

## ledger.json の項目

`id, url, title, site, tier, origin, retrieved_at, status (verified|unverified), snapshot, sha256, note`
