# Build and test environment for GreptimeDB common-meta.
# The Rust version matches rust-toolchain.toml (1.96.1).
FROM rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663

ARG PROTOBUF_VERSION=29.3
ARG PROTOBUF_SHA256=3e866620c5be27664f3d2fa2d656b5f3e09b5152b42f1bedbf427b333e90021a
ARG NEXTEST_VERSION=0.9.146
ARG NEXTEST_SHA256=682c21b777c333e96fd532e114d3a5a894e0729ab88d94c0a9f20f8419695428

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    CARGO_TERM_COLOR=never \
    CARGO_INCREMENTAL=0

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libssl-dev \
        pkg-config \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# protoc from apt is too old for this repository, use the pinned release like docker/dev-builder.
RUN curl -fsSL -o /tmp/protoc.zip \
        "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOBUF_VERSION}/protoc-${PROTOBUF_VERSION}-linux-x86_64.zip" && \
    echo "${PROTOBUF_SHA256}  /tmp/protoc.zip" | sha256sum -c - && \
    unzip -q /tmp/protoc.zip -d /usr/local && \
    chmod 0755 /usr/local/bin/protoc && \
    rm /tmp/protoc.zip

RUN curl -fsSL -o /tmp/nextest.tar.gz \
        "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-${NEXTEST_VERSION}/cargo-nextest-${NEXTEST_VERSION}-x86_64-unknown-linux-gnu.tar.gz" && \
    echo "${NEXTEST_SHA256}  /tmp/nextest.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/nextest.tar.gz -C /usr/local/cargo/bin && \
    rm /tmp/nextest.tar.gz

RUN useradd --create-home --uid 1000 --shell /bin/bash model

WORKDIR /app
COPY . /app

# Fetches the locked dependencies and compiles the common-meta unit tests so that
# test runs need neither the network nor a cold build. No test is executed here.
RUN cargo fetch --locked && \
    cargo test -p common-meta --lib --locked --no-run && \
    git config --system --add safe.directory /app && \
    chown -R model:model /app /usr/local/cargo

ENV CARGO_NET_OFFLINE=true

USER model

CMD ["/bin/bash"]
