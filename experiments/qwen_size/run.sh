#!/bin/bash
# 0.5B vs 3B answer-model comparison (#287). Run with Git Bash explicitly, under the GPU lock:
#   python ~/claude-config/scripts/gpu_run.py run --wait -- "C:/Program Files/Git/bin/bash.exe" experiments/qwen_size/run.sh
# (a bare `bash` resolves to WSL there). Needs the PDF at experiments/e2e/data/vsl.pdf.
# SMOKE=1 runs 3 blind + 2 unanswerable questions per arm and writes to $OUT_DIR (not a result).
# The reranker is off: only db, s3, migrate, api and worker start. Always tears down at the end.
cd "$(dirname "$0")/../.." || exit 9
ROOT=$(pwd)
export COMPOSE_PROJECT_NAME=qwen287 LLM_MODEL=eval287-0.5b
F="-f compose.yaml -f experiments/qwen_size/compose.override.yaml"
OUT=${OUT_DIR:-experiments/qwen_size/results}
export OUT_DIR=$OUT
LIMIT=${LIMIT:-0}
[ -n "$SMOKE" ] && LIMIT=3
mkdir -p "$OUT"
TMPD=$(mktemp -d)
OPID=""

start_ollama() {
  OLLAMA_HOST=127.0.0.1:11435 OLLAMA_KEEP_ALIVE=30m OLLAMA_MAX_LOADED_MODELS=2 ollama serve > "$OUT/ollama-$1.log" 2>&1 &
  OPID=$!
  for i in $(seq 1 30); do curl -sf localhost:11435/api/version >/dev/null 2>&1 && return 0; sleep 1; done
  echo "OLLAMA DID NOT START"; exit 6
}
stop_ollama() {
  [ -n "$OPID" ] && kill $OPID 2>/dev/null
  OPID=""
  sleep 5
  echo "gpu memory after stopping ollama: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
}
cleanup() {
  echo "== teardown"
  docker compose $F down 2>&1 | tail -3
  [ -n "$OPID" ] && kill $OPID 2>/dev/null
  OLLAMA_HOST=127.0.0.1:11434 ollama rm eval287-0.5b eval287-3b >/dev/null 2>&1
  rm -rf "$TMPD"
}
trap cleanup EXIT

docker info >/dev/null 2>&1 || { echo NO DOCKER; exit 5; }
git rev-parse HEAD
sha256sum experiments/e2e/data/vsl.pdf
echo "free RAM GB: $(powershell -c '[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)')"

# Local aliases that fix temperature 0, seed 287 and a 4096 context (the app sends no options).
# They are created from the already pulled models; no download.
start_ollama ingest
for pair in "0.5b:qwen2.5:0.5b-instruct" "3b:qwen2.5:3b-instruct"; do
  name=eval287-${pair%%:*}; base=${pair#*:}
  printf 'FROM %s\nPARAMETER temperature 0\nPARAMETER seed 287\nPARAMETER num_ctx 4096\n' "$base" > "$TMPD/Modelfile"
  OLLAMA_HOST=127.0.0.1:11435 ollama create "$name" -f "$TMPD/Modelfile" 2>&1 | tail -1
done

docker compose $F up -d --build db s3 migrate api worker 2>&1 | tail -12
for i in $(seq 1 60); do curl -sf localhost:8000/health >/dev/null 2>&1 || curl -sf localhost:8000/docs >/dev/null 2>&1 && break; sleep 5; done
RESP=$(uv run --frozen python - <<'P'
import httpx, json
r = httpx.post("http://localhost:8000/books", files={"file": ("vsl.pdf", open("experiments/e2e/data/vsl.pdf","rb"), "application/pdf")}, data={"title": "Viet Nam su luoc Q1"}, headers={"X-Dev-User":"dev-user"}, timeout=120)
print(json.dumps(r.json()))
P
)
echo "upload: $RESP"
BOOK_ID=$(echo "$RESP" | python -c "import sys,json;print(json.load(sys.stdin)['book']['id'])")
[ -z "$BOOK_ID" ] && { echo NO BOOK; exit 4; }
START=$(date +%s)
for i in $(seq 1 240); do
  S=$(docker compose $F exec -T db psql -U bookrag -tAc "select status from ingestion_jobs order by created_at desc limit 1" 2>/dev/null)
  echo "job: $S"; [ "$S" = "succeeded" ] && break; [ "$S" = "failed" ] && { echo INGEST FAILED; exit 3; }; sleep 15
done
echo "ingest_s=$(( $(date +%s) - START )) book=$BOOK_ID"
docker compose $F exec -T db psql -U bookrag -tAc "select count(*) from chunks where book_id='$BOOK_ID'"
stop_ollama

run_arm() {  # label, alias
  start_ollama "$1"
  LLM_MODEL=$2 docker compose $F up -d api 2>&1 | tail -3
  # Warm both models straight through Ollama (not the app) so a cold load is not counted as a failed
  # question; the load time is recorded as a cost. Amendment of 2026-11-19, see the note.
  W0=$(date +%s)
  curl -s localhost:11435/api/embed -d '{"model":"bge-m3","input":["khoi dong"]}' > /dev/null
  W1=$(date +%s)
  curl -s localhost:11435/api/chat -d '{"model":"'$2'","messages":[{"role":"user","content":"Xin chao"}],"stream":false,"options":{"num_predict":4}}' > /dev/null
  W2=$(date +%s)
  echo "warm-up $1: bge-m3 load $((W1-W0)) s, answer model load $((W2-W1)) s" | tee "$OUT/warm-$1.txt"
  for i in $(seq 1 60); do curl -sf localhost:8000/health >/dev/null 2>&1 || curl -sf localhost:8000/docs >/dev/null 2>&1 && break; sleep 3; done
  BOOK_ID=$BOOK_ID LABEL=$1 MODEL=$2 LIMIT=$LIMIT uv run --frozen python experiments/qwen_size/run_arm.py
  curl -s localhost:11435/api/ps > "$OUT/ps-$1.json"
  echo "== api log, errors for $1:"; docker compose $F logs api 2>&1 | grep -ci "error\|traceback"
  stop_ollama
}
run_arm 0.5b eval287-0.5b
run_arm 3b eval287-3b

# Judge phase (exploratory): the 3B judge, after both arms, so it cannot touch their VRAM or timings.
start_ollama judge
for label in 0.5b 3b; do
  LABEL=$label OLLAMA_URL=http://localhost:11435 uv run --frozen python experiments/qwen_size/judge_arm.py
done
stop_ollama
uv run --frozen python experiments/qwen_size/report.py
