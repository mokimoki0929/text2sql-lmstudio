FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 依存を先に入れる（キャッシュが効く）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体
COPY src/ /app/src/
COPY config/ /app/config/

# デフォルト実行（とりあえず疎通確認用）
# run_text2sql.py を作ったらここを差し替えるのがオススメ
CMD ["python", "-m", "src.gpt_oss_local_api", "テストです。1+1は？"]