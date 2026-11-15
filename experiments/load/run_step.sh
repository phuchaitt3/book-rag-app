#!/usr/bin/env bash
# One step: ./run_step.sh chat 40   or   ./run_step.sh upload 0.5
# Samples docker stats every 5 s and /load-stats around the k6 run, writes results/<name>.*
set -u
KIND=$1; LEVEL=$2; NAME="${3:-$KIND-$LEVEL}"
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="$HERE/results"; mkdir -p "$OUT"
NET=bookrag-load_default
curl -s "localhost:18000/load-stats?reset=true" >/dev/null
( while true; do docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' \
    | sed "s/^/$(date +%s),/" >> "$OUT/$NAME.stats.csv"; sleep 5; done ) &
SAMP=$!
if [ "$KIND" = chat ]; then SCRIPT=chat_reads.js; ENVV="VUS=$LEVEL"; else SCRIPT=upload.js; ENVV="RATE=$LEVEL"; fi
MSYS_NO_PATHCONV=1 docker run --rm --name "k6-$NAME" --network $NET --memory 512m \
  -v "$HERE:/load:ro" -v "$OUT:/out" -e "$ENVV" grafana/k6:latest run \
  --summary-export "/out/$NAME.summary.json" "/load/k6/$SCRIPT" > "$OUT/$NAME.k6.txt" 2>&1
echo "k6 exit=$?" >> "$OUT/$NAME.k6.txt"
kill $SAMP 2>/dev/null
curl -s "localhost:18000/load-stats" > "$OUT/$NAME.loadstats.json"
tail -30 "$OUT/$NAME.k6.txt"; cat "$OUT/$NAME.loadstats.json"; echo
