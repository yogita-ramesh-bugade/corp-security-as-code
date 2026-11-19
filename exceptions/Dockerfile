FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py service.py clients.py santa_rules.py types.yaml ./
RUN useradd --system --create-home bot && mkdir /data && chown bot /data
USER bot
# /deploy is a clone owned by your Mac user; tell git that's fine
RUN git config --global --add safe.directory /deploy
EXPOSE 8200
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8200", "--no-access-log"]
