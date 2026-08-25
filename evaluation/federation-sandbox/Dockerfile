FROM python:3.12-slim

RUN groupadd --gid 10001 oncemesh \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin oncemesh

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

USER 10001:10001
ENTRYPOINT ["python", "-m", "oncemesh.secret_exec"]
