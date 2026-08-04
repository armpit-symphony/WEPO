# Isolated Three-Host Seed Rehearsal

Status: required release-candidate rehearsal; not mainnet deployment

## Purpose and boundary

This runbook creates an isolated three-host WEPO **test-profile** network to
exercise public P2P reachability, static peer bootstrap, restart recovery, and
independent-host traffic. It does not set genesis parameters, enable mainnet,
publish DNS seeds, expose node APIs, or start the 30-day release clock.

Use three distinct failure domains:

| Role | Recommended location | Requirement |
| --- | --- | --- |
| Seed A | DigitalOcean | public IPv4, TCP 22567 |
| Seed B | AWS | public IPv4, TCP 22567 |
| Seed C | independent provider | public IPv4, TCP 22567; not a home NAT |

Do not use this PC as the third public seed. It may join the rehearsal as an
observer only after the three public hosts are healthy.

## Network policy

- Expose only TCP `22567` to the public internet.
- Keep node API `8122` bound to `127.0.0.1`; do not open it in cloud firewalls.
- Use the `test` profile and `--no-mining` service template exactly as supplied.
- Configure every host with the other two public `IP:22567` endpoints in
  `WEPO_STATIC_PEERS` and keep `WEPO_DNS_SEEDS=off`.
- Do not add a DNS record until a domain is owned, a DNS-seed behavior is
  reviewed, and the frozen network identity is approved.
- Do not place wallet seeds, validator keys, API credentials, or production
  Redis credentials on a seed node.

## Host preparation

On each fresh Ubuntu host, after an operator has installed the reviewed source
at `/opt/wepo` and created the `wepo` service user and virtual environment:

```bash
sudo install -d -m 0750 -o root -g wepo /etc/wepo
sudo install -d -m 0755 -o wepo -g wepo /var/lib/wepo/seed-rehearsal /var/log/wepo
sudo cp /opt/wepo/wepo-production-deployment/seed-rehearsal.env.example /etc/wepo/seed-rehearsal.env
sudo cp /opt/wepo/wepo-production-deployment/wepo-seed-rehearsal.service.example /etc/systemd/system/wepo-seed-rehearsal.service
sudo chmod 0640 /etc/wepo/seed-rehearsal.env
```

Edit `/etc/wepo/seed-rehearsal.env` before enabling the service:

1. Replace documentation addresses with the other two hosts' public IPs.
2. Keep `WEPO_NETWORK_PROFILE=test`, `WEPO_REQUIRE_MAINNET_SEEDS=0`, and
   `WEPO_DNS_SEEDS=off` unchanged.
3. Confirm API settings remain `127.0.0.1:8122`.

On each cloud firewall/security group, allow TCP `22567` from the internet for
the rehearsal and restrict SSH to operator administration sources. Do not open
`8122`.

## Start and verify

Bring up all three hosts within the same short window:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wepo-seed-rehearsal
sudo /opt/wepo/wepo-production-deployment/verify-seed-rehearsal-host.sh
```

Run the verifier on every host only after all three services are active. It
checks the test profile, static peer configuration, local listener, local API,
reported peer count, and outbound TCP reachability. It does not prove public
inbound reachability; collect that separately from a fourth independent network
using a documented TCP probe.

After external probes pass, fill
`wepo-production-deployment/seed-node-inventory.template.json` with the actual
owned-domain metadata, public IPs, failure domains, firewall evidence, selected
API/seed FQDNs, and probe timestamps. Retain the filled file with the release
evidence and validate it before a go/no-go review:

```bash
python3 /opt/wepo/wepo-production-deployment/verify-seed-node-inventory.py \
  --inventory /path/to/filled-seed-node-inventory.json
```

## Required evidence

Retain, for every host and the same source commit:

- filled seed-node inventory JSON passing `verify-seed-node-inventory.py`;
- public IP, provider/failure domain, OS image, and firewall/security-group rule;
- rendered service and environment file hashes with peer IPs redacted if needed;
- `systemctl status`, local verifier output, and external TCP 22567 probe output;
- local `/api/network/status` output showing at least two peers;
- node logs across restart and a controlled one-host outage/rejoin; and
- the multi-host P2P, hostile-traffic, and recovery rehearsals run against the
  three hosts.

Any changed source commit, P2P identity, peer address, firewall rule, or host
image requires the relevant rehearsal evidence to be refreshed.

## Still open after this rehearsal

This is an operations and network-confidence step, not readiness acceptance.
Mainnet remains unavailable until genesis and parameter decisions, production
Redis/TLS/monitoring/backups, independent reviews, clean candidate artifacts,
and the continuous seven-day rehearsal are complete.
