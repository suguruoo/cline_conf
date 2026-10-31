# コーディング規約

コード作成・レビューのたびに参照する。番号はユーザー定義の項番。`PY-NN` は `scripts/check_python.py` が機械検査する項目
(ERROR = 違反、WARN = 推奨・例外あり)。「レビュー」は機械検査できず、レビューで確認する項目。

## 1. 使用モジュールの承認 (PY-01)
- import する・使用するモジュールは **勝手に決めない**。使う理由を示し、他の選択肢を検討したうえで、必ず user の承認を得る。
- 手順: plan.md の『使用モジュール』表に、モジュールごとに「用途 / 選定理由 / 他の選択肢と却下理由」を書く → plan の承認が、そのモジュールの承認になる。
- 承認不要: `logging` / `typing` / `__future__` (規約 15・21 が使用を義務づけているため)、プロジェクト内のローカルモジュール。
- 標準ライブラリ・テストフレームワーク (unittest / pytest) も承認が必要。実装中に未承認のモジュールが必要になったら、作業を止めて逸脱 (`### D#`) を起票する。

## 2. 準拠する規約
- **Python**: PEP 8 / PEP 257 / Google Python Style Guide。
- **TypeScript**: プロジェクトの ESLint + Prettier 設定を優先する。`npx --yes eslint .` / `npx --yes prettier --check .` の結果を result.md の証拠にする (自動検査の対象外)。

## 3〜7. 命名
| 対象 | 規則 | 検査 |
|---|---|---|
| クラス・構造体 | PascalCase (PEP 8) | PY-03 |
| 変数・関数・メソッド・引数 | snake_case。標準ライブラリ (`len()` `str()` `dict()`) と揃え、単語をアンダースコアで区切る | PY-04 |
| 定数 | UPPER_SNAKE_CASE。定数と一目で分かり、再代入の誤りを減らし、グローバルの値と区別できる | PY-05 |
| プライベート | 先頭アンダースコア。`_balance` (内部)、`__account_id` (name mangling、強いプライベート)、`_internal_helper()` | レビュー |
| 分かりやすさ | **機能が明示的に理解できる名前** にする。複雑な名前より理解しやすさを優先する | PY-07 (WARN) + レビュー |

```python
class BankAccount:
    def __init__(self) -> None:
        self._balance = 0  # プライベート変数
        self.__account_id = None  # Name mangling (強いプライベート)

    def _internal_helper(self) -> None:  # プライベートメソッド
        pass
```

## 8〜10. docstring (Google スタイル)
- 全関数・メソッド・クラスに書く。PEP 257 準拠。`help()`・IDE のホバー・Sphinx Napoleon で使える形にする。
- 1 行目 (概要) は関数の目的を簡潔に。句点で終える。

| セクション | 必須/任意 | 条件 | 検査 |
|---|---|---|---|
| 概要 (1 行目) | 必須 | 全関数・メソッド | PY-08 |
| Args | 必須 | 引数がある場合 (各引数の意味・制約) | PY-09 |
| Returns | 必須 | 戻り値がある場合 (None のみは省略可) | PY-09 |
| Raises | 必須 | 例外を発生させる場合 | PY-09 |
| Note / Warning | 任意 | 使用上の注意・重要な警告がある場合 | - |
| Example | 推奨 | 公開 API (doctest として実行可能に) | - |
| See Also | 任意 | 関連する関数・クラスがある場合 | - |

```python
def calculate_discount_price(
    original_price: float,
    discount_rate: float,
    tax_rate: float = 0.1,
) -> float:
    """割引後の税込価格を計算する。

    元の価格に割引率を適用し、税率を加算して最終価格を算出する。
    計算式: (original_price × (1 - discount_rate)) × (1 + tax_rate)

    Args:
        original_price: 元の価格（税抜）。0 以上の数値。
        discount_rate: 割引率（0.0〜1.0）。0.2 = 20% 割引。
        tax_rate: 税率。デフォルト 0.1（10%）。

    Returns:
        割引後の税込価格。小数点第 2 位で四捨五入。

    Raises:
        ValueError: original_price が負数の場合。
        ValueError: discount_rate が 0.0〜1.0 の範囲外の場合。

    Note:
        - discount_rate は 0.0〜1.0 の範囲で指定する

    Warning:
        - 通貨計算では Decimal 型の使用を推奨

    See Also:
        calculate_tax: 税額計算関数。

    Example:
        >>> calculate_discount_price(1000, 0.2, 0.1)
        880.0
    """
```

クラスも同様 (PY-10): 概要と属性の説明を書く。

## 11〜14. スタイル
- インデント: スペース 4 つ (PY-11)。
- 行の長さ: **最大 79 文字 (推奨)** (PY-12 WARN)。パフォーマンス最適化などで逸脱する場合は規約 28 の形式でコメントを残す。
- 空行 (PY-13): トップレベルの関数・クラスの前後は 2 行、クラス内メソッドの間は 1 行。
- import 順序 (PY-14): ① 標準ライブラリ ② サードパーティ ③ ローカル。グループ間は 1 行空ける。`from __future__` は最初。

## 15〜16. 型ヒント (PY-15, PY-16)
- 関数の型ヒント: **必須** (引数・戻り値。`self` / `cls` は除く。戻り値なしは `-> None`)。
- クラス属性の型ヒント: **必須**。

```python
@dataclass
class Product:
    product_id: str
    name: str
    price: float
    stock: int
    description: Optional[str] = None
```

## 17〜18. エラーハンドリング (PY-17 WARN, PY-26)
- 具体的な例外クラスを使う (`except Exception` / `raise Exception` は避ける)。bare except は禁止 (PY-26)。
- 独自の失敗はカスタム例外にする:

```python
class ValidationError(Exception):
    """バリデーションエラー。"""
```

## 19〜20. テスト (PY-19, PY-20)
- **テストコードのないコードを生成しない。** コードとテストを同時に作る (`test_<module>.py`)。
- テスト関数名: `test_[機能]_[条件]_[期待結果]` (3 つ以上の語)。
- 構造は AAA。`# Arrange` / `# Act` / `# Assert` のコメントで区切る。

```python
def test_calculate_discount_price_negative_price_raises_value_error() -> None:
    """負の価格で ValueError になる。"""
    # Arrange
    price = -1.0

    # Act
    with pytest.raises(ValueError) as exc_info:
        calculate_discount_price(price, 0.2)

    # Assert
    assert "price" in str(exc_info.value)
```
(pytest を使う例。モジュールの承認が先。`# Arrange` / `# Act` / `# Assert` はそれぞれ別のコメント行にする。)

## 21〜23. ロギング (PY-21)
- `print` は使用不可。各モジュールに `logger = logging.getLogger(__name__)` を **必須** で置く。
- レベル: DEBUG (開発時のみ) / INFO (処理の開始・完了、本番で有効) / WARNING (継続可能だが注意) / ERROR (失敗、リトライ可) / CRITICAL (システム停止級)。
- ベストプラクティス: key=value 形式の構造化ログ、例外は `logger.error("処理失敗", exc_info=True)`、必要なコンテキスト (path, size, duration) を含める。

## 24〜25. コメント (PY-25 WARN)
- コードは「何を」、コメントは「**なぜ**」を説明する。不要なコメントはノイズ (レビュー)。
- `TODO(担当者): 内容` / `FIXME(担当者): 内容` / `HACK(担当者): 内容`。TODO は期限か Issue 番号、FIXME は優先度を添える。

## 26. 禁止事項 (PY-26)
- マジックナンバー禁止 (WARN。名前付き定数にする)。
- グローバル変数は禁止 (WARN。例外は理由をコメントで明記)。`global` 文は ERROR。
- bare except 禁止 (ERROR)。

## 27. レガシーコード
旧規約のファイルは、先頭に `LEGACY CODE WARNING` の docstring (作成日・最終更新・移行予定) を明記する。新規修正時は新規約に準拠する。

## 28. パフォーマンス最適化による例外
規約を逸脱する場合は、その直前に `# PERFORMANCE OPTIMIZATION: 理由` と、根拠 (`# Benchmark: URL`) を明記する。
行長の逸脱は、この注記があれば PY-12 の対象外になる。

## 参考: 機械検査の対象外 (レビューで見る)
命名が機能を表しているか、コメントが「なぜ」を書いているか、例外の選択が適切か、docstring の内容が実装と一致しているか、
設計の妥当性、テストが条件を網羅しているか。
