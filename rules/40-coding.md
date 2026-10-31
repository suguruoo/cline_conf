# コーディング (必須)

- **コードを書く・直す・レビューするときは、先に skill `profile-coding` を読み込む** (use_skill)。読み込むまで `.py` / `.ts` / `.tsx` への書き込みは hook に拒否される。
  作業用の一時スクリプト (/tmp など作業ディレクトリ外) は対象外。
- **import するモジュールは勝手に決めない**。用途・選定理由・他の選択肢と却下理由を示し、user の承認を得てから使う
  (plan.md の『使用モジュール』表。承認済みは plan の承認で成立)。標準ライブラリ・テストフレームワークも対象。
- **テストのないコードを生成しない**。コードとテストを同時に作る。
- Python は PEP 8 / PEP 257 / Google Python Style Guide、型ヒント必須、Google スタイル docstring、`print` 禁止 (logger を使う)。
  TypeScript はプロジェクトの ESLint + Prettier 設定を優先する。詳細は skill の docs。
- 完了前に `check_python.py` をエラー 0 にする (手順は skill)。レビューは skill の review-checklist に従い、規約の項番を添えて指摘する。
