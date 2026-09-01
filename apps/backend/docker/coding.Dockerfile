# Build once on the host; Coding Agent never installs dependencies at runtime.
# docker build -t neuroasist-coding:latest -f apps/backend/docker/coding.Dockerfile .
FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && python3 -m pip install --no-cache-dir --break-system-packages pytest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid agent --create-home --shell /usr/sbin/nologin agent

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp
WORKDIR /workspace
USER agent
