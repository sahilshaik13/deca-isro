#!/usr/bin/env bash
set -euo pipefail
cnt=$(journalctl --since "60 sec ago" -p warning..alert -q -o cat 2>/dev/null | wc -l | tr -d ' ')
printf "syslog_err_count value=%s\n" "${cnt:-0}"
