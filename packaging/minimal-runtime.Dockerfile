# This image is a disposable runtime fixture, not a deployment recipe.
FROM ubuntu:24.04
COPY solartt.deb /tmp/solartt.deb
# Ubuntu Docker images discard documentation by default. Preserve the exact
# package docs, configuration examples and license notices used by the install guide.
RUN sed -i '/path-exclude=.*share.*doc/d' /etc/dpkg/dpkg.cfg.d/* \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    /tmp/solartt.deb python3 openssl util-linux \
    && rm -f /tmp/solartt.deb && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/solartt-test
COPY minimal_runtime.py .
RUN touch DISPOSABLE && mkdir /report
ENTRYPOINT ["python3", "/opt/solartt-test/minimal_runtime.py"]
