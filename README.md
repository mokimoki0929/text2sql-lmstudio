# text2sql-lmstudio

ローカルLLM（LM Studio）または Groq を使って、自然言語から SQL を生成して PostgreSQL に対して実行し、結果を返す Text-to-SQL 検証用プロジェクトです。  
評価用の質問セット（JSONL）を回して、実行成功率・一致率を測定できます。

## 主な機能

- 自然文 → SQL 生成（LM Studio / Groq）
- SQL の安全ガード（DML/DDL などの危険操作を拒否）
- PostgreSQL でクエリ実行して結果表示
- JSONL のテストセットを用いた精度評価（`--show-mismatch` で差分表示）
- DBスキーマを自動取得してプロンプトに埋め込む（`--introspect`）

---
