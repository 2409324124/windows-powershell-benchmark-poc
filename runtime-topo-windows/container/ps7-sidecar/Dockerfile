FROM ubuntu:24.04

COPY .cache/powershell.deb /tmp/powershell.deb

RUN apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=20 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=20 install -y --no-install-recommends /tmp/powershell.deb openssh-server ca-certificates \
    && rm -f /tmp/powershell.deb \
    && useradd --create-home --shell /bin/bash wcb-task \
    && mkdir -p /run/sshd /etc/ssh/keys /opt/wcb/tools \
    && rm -rf /var/lib/apt/lists/*

COPY manifest-helper.sh /opt/wcb/tools/manifest-helper
RUN chmod 0755 /opt/wcb/tools/manifest-helper

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /usr/local/bin/wcb-sidecar-entrypoint
RUN chmod 0755 /usr/local/bin/wcb-sidecar-entrypoint

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/wcb-sidecar-entrypoint"]
