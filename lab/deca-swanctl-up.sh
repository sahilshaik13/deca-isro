#!/usr/bin/env bash
# Load swanctl IPsec (copy_dscp) and initiate CHILD_SA. Idempotent.
set +e
for i in 1 2 3 4 5 6 7 8 9 10 11 12 15; do
  [[ -S /var/run/charon.vici ]] && break
  sleep 1
done
if [[ ! -S /var/run/charon.vici ]]; then
  echo "[deca-swanctl-up] no vici socket — is strongswan-starter running?" >&2
  exit 0
fi
swanctl --load-all >/dev/null 2>&1
# Initiate may race the peer; retry a few times
for i in 1 2 3 4 5; do
  swanctl --list-sas 2>/dev/null | grep -q ESTABLISHED && exit 0
  swanctl --initiate --child net >/dev/null 2>&1 || true
  sleep 2
done
exit 0
