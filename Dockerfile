# syntax=docker/dockerfile:1
# ══════════════════════════════════════════════════════════════
# builder — installs Python deps into a venv; not shipped
# ══════════════════════════════════════════════════════════════
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml ./
# Install third-party dependencies only (cached); pyproject.toml parsed at build time
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    python3 -c "
import tomllib, subprocess, sys
deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']
subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + deps)
"

COPY pagemenot/ pagemenot/
# Install local package only — no cache, no deps; always reflects current source
RUN pip install --no-cache-dir --no-deps .

# ══════════════════════════════════════════════════════════════
# base — clean runtime image: venv + app code + kubectl
# pip, setuptools, wheel stay in builder; not copied here
# ══════════════════════════════════════════════════════════════
FROM python:3.12-slim AS base

WORKDIR /app

# curl: needed for kubectl download and HEALTHCHECK; kept at runtime
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# One layer for all app code
COPY pagemenot/ pagemenot/ scripts/ scripts/ knowledge/ knowledge/

# kubectl — single binary, arch-aware, pinned version; sha256 verified
ARG KUBECTL_VERSION=v1.35.2
RUN ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    curl -fsSLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" && \
    curl -fsSLo /tmp/kubectl.sha256 \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl.sha256" && \
    echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check --strict && \
    rm /tmp/kubectl.sha256 && \
    chmod +x /usr/local/bin/kubectl

RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --no-create-home appuser && \
    mkdir -p /app/data/chroma /app/.config/crewai && \
    echo '{"show_tracing_ui": false}' > /app/.config/crewai/settings.json && \
    chown -R appuser:appgroup /app /venv

ENV HOME=/app
ENV CREWAI_TRACING_ENABLED=false
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080
CMD ["python", "-m", "pagemenot.main"]

# ══════════════════════════════════════════════════════════════
# aws — + AWS CLI v2  (~500 MB)
# PAGEMENOT_BUILD_TARGET=aws
# unzip: setup only — removed after install
# ══════════════════════════════════════════════════════════════
FROM base AS aws

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends unzip && \
    ARCH=$(uname -m) && \
    curl -fsSLo /tmp/awscliv2.zip \
      "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" && \
    unzip -q /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscliv2.zip /tmp/aws && \
    apt-get remove --purge -y unzip && apt-get autoremove -y

# ══════════════════════════════════════════════════════════════
# gcp — + gcloud CLI  (~400 MB)
# PAGEMENOT_BUILD_TARGET=gcp
# gnupg: setup only — removed after key import
# ══════════════════════════════════════════════════════════════
FROM base AS gcp

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends gnupg && \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y --no-install-recommends google-cloud-cli && \
    apt-get remove --purge -y gnupg && apt-get autoremove -y

# ══════════════════════════════════════════════════════════════
# azure — + Azure CLI  (~300 MB)
# PAGEMENOT_BUILD_TARGET=azure
# gnupg, lsb-release: setup only — removed after repo configured
# ══════════════════════════════════════════════════════════════
FROM base AS azure

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends gnupg lsb-release && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSLS https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    AZ_DIST=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] \
https://packages.microsoft.com/repos/azure-cli/ ${AZ_DIST} main" \
      > /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && apt-get install -y --no-install-recommends azure-cli && \
    apt-get remove --purge -y gnupg lsb-release && apt-get autoremove -y

# ══════════════════════════════════════════════════════════════
# cloud — + AWS CLI + gcloud + Azure CLI  (~1.2 GB extra)
# PAGEMENOT_BUILD_TARGET=cloud
# FROM base (not aws): all three CLIs in one RUN, one cleanup pass.
# Build deps (unzip, gnupg, lsb-release) installed and purged in same layer.
# ══════════════════════════════════════════════════════════════
FROM base AS cloud

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    # ── build-time deps ──────────────────────────────────────
    apt-get update && apt-get install -y --no-install-recommends \
      unzip gnupg lsb-release && \
    # ── AWS CLI v2 ───────────────────────────────────────────
    ARCH=$(uname -m) && \
    curl -fsSLo /tmp/awscliv2.zip \
      "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" && \
    unzip -q /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/awscliv2.zip /tmp/aws && \
    # ── gcloud repo ──────────────────────────────────────────
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    # ── azure repo ───────────────────────────────────────────
    mkdir -p /etc/apt/keyrings && \
    curl -fsSLS https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg && \
    AZ_DIST=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] \
https://packages.microsoft.com/repos/azure-cli/ ${AZ_DIST} main" \
      > /etc/apt/sources.list.d/azure-cli.list && \
    # ── install all CLIs in one pass ─────────────────────────
    apt-get update && apt-get install -y --no-install-recommends \
      google-cloud-cli azure-cli && \
    # ── purge build-time deps ─────────────────────────────────
    apt-get remove --purge -y unzip gnupg lsb-release && apt-get autoremove -y
