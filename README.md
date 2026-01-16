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

## ディレクトリ構成

text2sql-lmstudio/

  config/
  
    setting.json
    
  src/
  
    gpt_oss_local_api.py
    
    text2sql_prompt.py        # スキーマ＋ルールを結合してプロンプト化
    
    run_text2sql.py           # 自然文→SQL→DB実行→結果表示
    
  db/
  
    init/
    
      001_schema.sql
      
      002_seed.sql
      
      003_seed_more.sql
      
  docker/
  
    postgres/
    
      Dockerfile              # いらない
      
  docker-compose.yml
  
  requirements.txt
  
  .gitignore
  
