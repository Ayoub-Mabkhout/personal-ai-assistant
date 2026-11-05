ARG PYTHON_IMAGE=library/python@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
FROM ${PYTHON_IMAGE} AS iron-league
# Pin the source revision and check the archive before extracting the static files.
ADD https://codeload.github.com/Ayoub-Mabkhout/iron-league/tar.gz/6e00e6e0aba5c8bf90c6cb038fdec2231194bfee /tmp/iron-league.tar.gz
RUN echo '2a8225b39687114533ccb11cc67ec2be3aa044ed8686145ee6bd16bfc52d42f5  /tmp/iron-league.tar.gz' | sha256sum -c - \
    && mkdir /web \
    && tar -xzf /tmp/iron-league.tar.gz -C /web --strip-components=2 iron-league-6e00e6e0aba5c8bf90c6cb038fdec2231194bfee/web \
    && test -s /web/index.html

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-server.lock ./
RUN pip install --no-cache-dir -r requirements-server.lock
COPY pyproject.toml ./
COPY src ./src
COPY apps/groceries ./apps/groceries
COPY apps/tasks ./apps/tasks
COPY apps/shared ./apps/shared
COPY --from=iron-league /web/ ./apps/train-web/
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 assistant \
    && useradd --uid 10001 --gid 10001 --no-create-home assistant \
    && mkdir /data && chown assistant:assistant /data
USER 10001:10001
EXPOSE 8765
# Long-polling claims hold connections open (capped at 24 in relay/wakeups.py); 64 keeps 40 for other traffic.
CMD ["uvicorn", "personal_assistant.relay.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8765", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
