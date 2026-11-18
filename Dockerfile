FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KIDSWRITER_PORT=8122 \
    KIDSWRITER_DATA=/app/data \
    KIDSWRITER_UI=/app/index.html \
    TZ=Asia/Shanghai

WORKDIR /app

RUN pip install --no-cache-dir "edge-tts==7.3.1" "pypinyin==0.55.0" \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
    || pip install --no-cache-dir "edge-tts==7.3.1" "pypinyin==0.55.0"

COPY 童阅写稿器.py /app/writer.py
COPY 界面.html /app/index.html
COPY covers /app/covers

RUN mkdir -p /app/data && chmod 777 /app/data

VOLUME /app/data
EXPOSE 8122

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8122/api/config',timeout=3)" || exit 1

CMD ["python", "-u", "/app/writer.py", "--serve", "--no-browser", "--port", "8122"]
