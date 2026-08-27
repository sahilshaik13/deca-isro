#!/usr/bin/env sh
# Create dual-fabric Kafka topics inside the compose kafka container.
set -eu
BS="${KAFKA_BOOTSTRAP:-kafka:29092}"
BIN=/opt/kafka/bin/kafka-topics.sh

for topic in sdwan_telemetry_pi sdwan_telemetry_gns3; do
  "$BIN" --bootstrap-server "$BS" --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions 3 \
    --replication-factor 1
  echo "topic ok: $topic"
done

"$BIN" --bootstrap-server "$BS" --create \
  --if-not-exists \
  --topic sdwan_telemetry \
  --partitions 3 \
  --replication-factor 1 || true

"$BIN" --bootstrap-server "$BS" --list
