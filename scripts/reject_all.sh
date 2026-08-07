#!/bin/bash
# Rejects all active alerts in the DECA backend
ids=$(curl -s http://localhost:8000/api/alerts | jq -r '.active[].id')
if [ -z "$ids" ]; then
  echo "No active alerts to reject."
  exit 0
fi

for id in $ids; do
  echo "Rejecting alert $id..."
  curl -s -X POST "http://localhost:8000/api/actions/$id/reject" \
       -H "Content-Type: application/json" \
       -d '{"operator_note": "Bulk reject via terminal", "approved_by": "deca-ui"}'
done
echo "All alerts rejected."
