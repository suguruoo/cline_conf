---
name: profile-architecture
description: アーキテクチャ設計タスクの手順と検証基準。ADR (Architecture Decision Record) 形式での決定記録、C4 モデルによる図、Memory Bank 管理を含む。アーキテクチャ設計・技術選定・システム設計の依頼で使う。task-protocol と併用する。
---

# profile-architecture

`taskctl new "<題>" --profile architecture` で作ったタスクの中で使う。
`<S>` = `<harness>/skills/profile-architecture/scripts`。

## 手順

1. **spec**: 非機能要件 (性能・セキュリティ・スケーラビリティ) と制約を受け入れ条件に含める。
2. **plan**: C4 モデルのどのレベルまで設計するかを明示する。
3. **設計** (progress):
   - Mermaid 図でアーキテクチャを可視化する。
   - 重要な決定は必ず ADR に記録する: `arch-bank/adr/adr-NNN-<題>.md`
4. **ADR lint**: `python3 <S>/lint_adr.py arch-bank/adr/adr-NNN-<題>.md` を **エラー 0** にする。
5. **result**: 全 AC の判定と ADR の一覧を証拠として記載する。

## ADR の必須フィールド

| フィールド | 内容 |
|---|---|
| `# ADR-NNN: タイトル` | 先頭の h1。番号は 3 桁 0 埋め |
| `## ステータス` | `提案中` / `承認済み` / `非推奨` / `置換済み` のいずれか |
| `## コンテキスト` | なぜこの決定が必要か |
| `## 決定内容` | 何を決めたか |
| `## 結果` | ポジティブ・ネガティブな影響 |

## Memory Bank

`arch-bank/` に設計情報を蓄積する。セッションをまたいで再開する際は最初に読み込む。

```
arch-bank/
  systemContext.md    ← システムの目的・制約
  requirements.md     ← 機能・非機能要件
  adr/                ← ADR ファイル
  diagrams.md         ← Mermaid 図のコレクション
  techStack.md        ← 技術スタックと選定理由
  progress.md         ← 現在の進捗
```
