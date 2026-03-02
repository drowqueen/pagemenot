# ══════════════════════════════════════════════════════════════
# base — Python app + kubectl
# Selects correct binary for amd64 and arm64 automatically.
# ══════════════════════════════════════════════════════════════
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip pip install .

COPY pagemenot/ pagemenot/
COPY scripts/ scripts/
COPY knowledge/ knowledge/

ARG KUBECTL_VERSION=v1.35.2
RUN ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    curl -fsSLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" && \
    chmod +x /usr/local/bin/kubectl

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080
CMD ["python", "-m", "pagemenot.main"]

# ══════════════════════════════════════════════════════════════
# aws — + AWS CLI v2  (~500 MB)
# PAGEMENOT_BUILD_TARGET=aws
# ══════════════════════════════════════════════════════════════
FROM base AS aws

RUN apt-get update && apt-get install -y --no-install-recommends unzip && \
    rm -rf /var/lib/apt/lists/* && \
    ARCH=$(uname -m) && \
    curl -fsSLo /tmp/awscliv2.zip \
      "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" && \
    unzip -q /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscliv2.zip /tmp/aws

# ══════════════════════════════════════════════════════════════
# gcp — + gcloud CLI  (~400 MB)
# PAGEMENOT_BUILD_TARGET=gcp
# ══════════════════════════════════════════════════════════════
FROM base AS gcp

RUN apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https gnupg && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y --no-install-recommends google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# ══════════════════════════════════════════════════════════════
# azure — + Azure CLI  (~300 MB)
# PAGEMENOT_BUILD_TARGET=azure
# ══════════════════════════════════════════════════════════════
FROM base AS azure

RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg lsb-release && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSLS https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    AZ_DIST=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] \
https://packages.microsoft.com/repos/azure-cli/ ${AZ_DIST} main" \
      > /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && apt-get install -y --no-install-recommends azure-cli && \
    rm -rf /var/lib/apt/lists/*

# ══════════════════════════════════════════════════════════════
# cloud — + AWS CLI + gcloud + Azure CLI  (~1.2 GB extra)
# PAGEMENOT_BUILD_TARGET=cloud
# Builds FROM aws to reuse cached aws layer.
# ══════════════════════════════════════════════════════════════
FROM aws AS cloud

RUN apt-get update && apt-get install -y --no-install-recommends \
    apt-transport-https gnupg lsb-release && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y --no-install-recommends google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSLS https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    AZ_DIST=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] \
https://packages.microsoft.com/repos/azure-cli/ ${AZ_DIST} main" \
      > /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && apt-get install -y --no-install-recommends azure-cli && \
    rm -rf /var/lib/apt/lists/*
