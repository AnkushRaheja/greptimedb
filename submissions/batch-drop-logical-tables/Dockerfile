FROM public.ecr.aws/d3j8x8q7/olympus-base-rust:latest

ARG PROTOBUF_VERSION=29.3
ARG PROTOBUF_SHA256=3e866620c5be27664f3d2fa2d656b5f3e09b5152b42f1bedbf427b333e90021a
ARG NEXTEST_VERSION=0.9.146
ARG NEXTEST_SHA256=682c21b777c333e96fd532e114d3a5a894e0729ab88d94c0a9f20f8419695428

ENV DEBIAN_FRONTEND=noninteractive \
    CARGO_TERM_COLOR=never \
    CARGO_INCREMENTAL=0

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libssl-dev \
        pkg-config \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# protoc from apt is too old for this repository, use the pinned release like docker/dev-builder.
RUN curl -fsSL -o /tmp/protoc.zip \
        "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOBUF_VERSION}/protoc-${PROTOBUF_VERSION}-linux-x86_64.zip" && \
    echo "${PROTOBUF_SHA256}  /tmp/protoc.zip" | sha256sum -c - && \
    unzip -q -o /tmp/protoc.zip -d /usr/local && \
    chmod 0755 /usr/local/bin/protoc && \
    rm /tmp/protoc.zip

RUN curl -fsSL -o /tmp/nextest.tar.gz \
        "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-${NEXTEST_VERSION}/cargo-nextest-${NEXTEST_VERSION}-x86_64-unknown-linux-gnu.tar.gz" && \
    echo "${NEXTEST_SHA256}  /tmp/nextest.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/nextest.tar.gz -C /usr/local/bin && \
    rm /tmp/nextest.tar.gz

WORKDIR /app
COPY . /app

# The base image ships another Rust release; install the toolchain pinned by
# rust-toolchain.toml and fetch the locked dependencies for offline builds.
RUN rustup toolchain install "$(sed -n 's/^channel = "\(.*\)"$/\1/p' rust-toolchain.toml)" --profile minimal && \
    rustc --version && \
    protoc --version && \
    cargo fetch --locked && \
    git config --system --add safe.directory /app && \
    chmod -R a+rwX /opt/cargo /opt/rustup

ENV CARGO_NET_OFFLINE=true

CMD ["/bin/bash"]
