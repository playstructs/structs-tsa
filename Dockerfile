FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

LABEL maintainer="Slow Ninja <info@slow.ninja>"
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ARG TARGETARCH
ARG STRUCTSD_VERSION=v0.22.0
ARG STRUCTSD_SHA256=321d001eb9dc75897271353043fe0914f6532f70a90232a67dc0213d0df4e135
ARG SIGN_PROXY_REF=6b76e2aadb2bc284ac8782df4d0edadbd344e342

RUN test "$TARGETARCH" = amd64 && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 python3-venv libpq5 nodejs npm && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 3 -o /tmp/structsd.tar.gz \
      "https://github.com/playstructs/structsd/releases/download/${STRUCTSD_VERSION}/structsd-${STRUCTSD_VERSION#v}-linux-amd64.tar.gz" && \
    printf '%s  %s\n' "$STRUCTSD_SHA256" /tmp/structsd.tar.gz | sha256sum --check --strict && \
    mkdir /tmp/structsd-release && tar -xzf /tmp/structsd.tar.gz -C /tmp/structsd-release && \
    test "$(find /tmp/structsd-release -type f -name structsd | wc -l)" -eq 1 && \
    install -m 0755 "$(find /tmp/structsd-release -type f -name structsd)" /usr/local/bin/structsd && \
    test "$(structsd version 2>/dev/null)" = "${STRUCTSD_VERSION#v}" && \
    rm -rf /tmp/structsd.tar.gz /tmp/structsd-release
RUN git init /opt/structs-sign-proxy && cd /opt/structs-sign-proxy && \
    git remote add origin https://github.com/playstructs/structs-sign-proxy.git && \
    git fetch --depth 1 origin "$SIGN_PROXY_REF" && git checkout --detach FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = "$SIGN_PROXY_REF" && npm ci --omit=dev --ignore-scripts && \
    ln -s /opt/structs-sign-proxy/bin/structs-sign-proxy.js /usr/local/bin/structs-sign-proxy

COPY requirements.txt /opt/tsa/requirements.txt
RUN python3 -m venv /opt/tsa/venv && /opt/tsa/venv/bin/pip install --require-hashes --only-binary=:all: -r /opt/tsa/requirements.txt
ENV PATH="/opt/tsa/venv/bin:${PATH}" PYTHONPATH=/opt/tsa
WORKDIR /opt/tsa
COPY tsa /opt/tsa/tsa
COPY scripts/verify-tx.mjs scripts/keyring-proof.mjs /opt/structs-sign-proxy/
COPY scripts/manual-reload.sh scripts/manual-role-init.sh /src/structs/
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD ["python", "-m", "tsa", "health"]
RUN mkdir -p /var/structs/accounts /var/structs/chain /var/structs/tsa && chmod 700 /var/structs/accounts
CMD ["python", "-m", "tsa"]
