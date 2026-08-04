#!/usr/bin/env bash
# Emit last SD-WAN controller metrics written by lab/deca_sdwan_controller.py
set -euo pipefail
F=/var/lib/deca/sdwan_metrics.influx
if [[ -f "$F" ]]; then
  cat "$F"
else
  # zeroed placeholders so scrape stays green when controller is down
  echo 'sdwan_active_path,class=voice,path=gre value=0'
  echo 'sdwan_active_path,class=voice,path=eth0 value=0'
  echo 'sdwan_path_switch_count,class=voice value=0i'
  echo 'sdwan_last_switch_reason,class=voice,reason=controller_down value=1'
fi
