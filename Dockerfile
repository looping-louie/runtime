FROM python:3.12-slim

ARG CODEX_CLI_VERSION=0.160.0
ARG COPILOT_CLI_VERSION=1.0.91

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes git nodejs npm \
    && npm install --global --omit=dev \
        "@openai/codex@${CODEX_CLI_VERSION}" \
        "@github/copilot@${COPILOT_CLI_VERSION}" \
    && codex --version \
    && copilot --version \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

ENTRYPOINT ["looping-louie-runtime"]
