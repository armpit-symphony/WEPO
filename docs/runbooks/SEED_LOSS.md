# Seed Loss Runbook

## Trigger and objective

Use this runbook when a seed is unreachable, port 22567 fails external checks,
DNS returns stale addresses, or provider/failure-domain loss reduces bootstrap
capacity below three independent seeds. Preserve peer connectivity while
restoring bootstrap diversity; do not change consensus or mainnet parameters.

## First response

1. Record failing host, provider/region, public IP, DNS answer, TCP observation,
   node height/tip, service status, firewall changes, and last healthy time.
2. Verify from an external network. A local listen socket is not reachability.
3. Confirm remaining seeds agree on network identity, height, tip, and supply.
4. Do not point DNS at a home/NAT node or an unqualified replacement.

## Restore or replace

If the host is healthy but unreachable, repair the narrow firewall, route, or
provider rule and repeat external TCP plus P2P handshake tests. If replacement
is required, deploy the frozen release image in a distinct failure domain,
verify its manifest, restore/catch up from trusted chain data, and run
`verify-seed-rehearsal-host.sh` plus the production host checks before publishing
it.

Update static peer inventories before DNS. Use low TTL only during the approved
migration. Publish an A/AAAA record only after the replacement is synchronized,
externally reachable, and monitored. Remove the dead address after caches and
static peer packages have been reviewed.

## Acceptance

- at least three independently hosted seeds are externally reachable on 22567;
- new nodes bootstrap with DNS unavailable by using reviewed static peers;
- new nodes bootstrap with one static peer unavailable by using DNS/other peers;
- all seeds match network/genesis/parameter identity and canonical tip;
- alerts, provider inventory, DNS, and release evidence identify the replacement;
- no API, database, Redis, signer, or SSH management port was exposed publicly.
