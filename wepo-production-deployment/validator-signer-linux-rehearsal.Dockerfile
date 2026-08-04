FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y --no-install-recommends sudo=1.9.16p2-3+deb13u2 \
    && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' 'dilithium-py==1.1.0 --hash=sha256:0bd29e80bad7ed6700984708ca2798a318e3a8bd404f2a5c8d08cc9eceafd5a5' \
        >/tmp/signer-requirements.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/signer-requirements.txt \
    && rm -f /tmp/signer-requirements.txt

RUN install -d -m 0755 -o root -g root /usr/local/libexec/wepo
COPY install-validator-signer.sh /usr/local/libexec/wepo/install-validator-signer.sh
COPY verify-validator-signer-host.sh /usr/local/libexec/wepo/verify-validator-signer-host.sh
COPY validator_signer_rehearsal_client.py /usr/local/libexec/wepo/validator_signer_rehearsal_client.py
COPY validator-signer-linux-rehearsal.sh /usr/local/libexec/wepo/validator-signer-linux-rehearsal.sh
RUN sed -i 's/\r$//' /usr/local/libexec/wepo/* \
    && chmod 0755 /usr/local/libexec/wepo/* \
    && chown -R root:root /usr/local/libexec/wepo

ENTRYPOINT ["/usr/local/libexec/wepo/validator-signer-linux-rehearsal.sh"]
