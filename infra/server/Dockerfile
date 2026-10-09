FROM library/python@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-server.lock ./
RUN pip install --no-cache-dir -r requirements-server.lock
COPY pyproject.toml ./
COPY src ./src
COPY apps/groceries ./apps/groceries
COPY apps/tasks ./apps/tasks
COPY apps/shared ./apps/shared
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 assistant \
    && useradd --uid 10001 --gid 10001 --no-create-home assistant \
    && mkdir /data && chown assistant:assistant /data
USER 10001:10001
EXPOSE 8765
CMD ["uvicorn", "personal_assistant.relay.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8765", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
