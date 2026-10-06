FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && (pip install --no-cache-dir "vnstock>=4.0" \
        || echo "vnstock khong cai duoc (PyPI cach ly?) - bot chay khong co BCTC/nganh")

COPY . .
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "bot_phan_tich.bot.main"]
