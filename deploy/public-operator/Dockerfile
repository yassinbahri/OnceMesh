ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="OnceMesh public federation origin" \
      org.opencontainers.image.source="https://github.com/yassinbahri/OnceMesh" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --gid 10001 oncemesh \
    && useradd --uid 10001 --gid 10001 --create-home \
      --shell /usr/sbin/nologin oncemesh

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

USER 10001:10001
EXPOSE 8443
ENTRYPOINT ["python", "-m", "oncemesh.secret_exec"]
