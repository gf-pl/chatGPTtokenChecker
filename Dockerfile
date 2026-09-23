FROM node:22-bookworm-slim AS codex-cli
RUN npm install --global @openai/codex@0.156.0

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules/@openai/codex /opt/codex
RUN ln -s /opt/codex/bin/codex.js /usr/local/bin/codex
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /app/data && useradd --uid 10001 --create-home monitor && chown -R monitor:monitor /app/data
USER monitor
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
