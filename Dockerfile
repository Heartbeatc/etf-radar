FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
COPY app ./app
RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent --no-create-home app \
    && mkdir -p /opt/etf-radar/data /app/data \
    && chown -R app:app /opt/etf-radar /app
USER app
EXPOSE 8088
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088", "--no-server-header"]
