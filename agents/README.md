# agents/ — サブエージェント定義

`agents/` ディレクトリには、特定の繰り返しタスクを自動実行するサブエージェントの定義ファイルを置く。

## ファイル形式

各エージェントは **Markdown + YAML フロントマター** で定義する。

```
---
name: <エージェント名>
trigger: <起動条件の説明>
tools:
  - <使用するツール名>
inputs:
  - name: <入力変数名>
    description: <説明>
    required: true|false
---

# <エージェント名>

## 役割

<このエージェントが何をするか>

## 手順

1. <ステップ 1>
2. <ステップ 2>

## 出力

<出力の形式と内容>
```

## 命名規則

- ファイル名: `<役割>.md` (例: `reviewer.md`, `summarizer.md`)
- `name` フィールド: kebab-case (例: `code-reviewer`)

## 現在のエージェント

| ファイル | 名前 | 役割 |
|---|---|---|
| `reviewer.md` | code-reviewer | Python/TypeScript コードのレビューを実行する |
