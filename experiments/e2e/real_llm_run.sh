#!/bin/bash
# Run with Git Bash explicitly under the lock: python ~/claude-config/scripts/gpu_run.py run --wait -- "C:/Program Files/Git/bin/bash.exe" experiments/e2e/real_llm_run.sh <log-prefix>
# (a bare `bash` resolves to WSL there and fails). Needs the PDF at experiments/e2e/data/vsl.pdf (sha in e2e-real-model.md).
# Real-LLM through-the-app run (#285). Runs under the GPU lock. Always tears down at the end.
cd "$(dirname "$0")/../.." || exit 6
# LIMIT=n is the smoke run (first n questions, written under a -smoke label).
export COMPOSE_PROJECT_NAME=real285 LLM_MODEL=qwen2.5:3b-instruct
export RERANKER_OWNER=285-real-llm
# EXTRA_COMPOSE=file adds a machine-local override (for example another model-cache volume).
F="-f compose.yaml -f compose.reranker.yaml -f experiments/e2e/real_llm_ollama_port.yaml ${EXTRA_COMPOSE:+-f $EXTRA_COMPOSE}"
LOG=$1
cleanup() {
  docker compose $F logs --no-color api > $LOG.api.log 2>&1
  echo "== teardown"; docker compose $F down 2>&1 | tail -3
  [ -n "$OPID" ] && kill $OPID 2>/dev/null
}
trap cleanup EXIT
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_KEEP_ALIVE=30m OLLAMA_MAX_LOADED_MODELS=2 ollama serve > $LOG.ollama.log 2>&1 &
OPID=$!
sleep 8
docker info >/dev/null 2>&1 || { echo NO DOCKER; exit 5; }
git rev-parse HEAD
# Not started: qdrant (only used when VECTOR_STORE=qdrant; default pgvector) and web (this run talks to the API only). Saves RAM.
docker compose $F up -d --build --scale qdrant=0 --scale web=0 2>&1 | tail -12
for i in $(seq 1 60); do curl -sf localhost:8000/readyz >/dev/null 2>&1 && break; sleep 5; done
# ingest
RESP=$(uv run python - <<'P'
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
[ -z "$BOOK_ID" ] && { echo NO BOOK; exit 4; }
echo "ingest_s=$(( $(date +%s) - START )) book=$BOOK_ID"
docker compose $F exec -T db psql -U bookrag -tAc "select count(*) from chunks where book_id='$BOOK_ID'"
# warm both models nothing special: first question counted (pre-registered)
LABEL=qwen3b-rerank-on
[ -n "$LIMIT" ] && LABEL=$LABEL-smoke
BOOK_ID=$BOOK_ID LABEL=$LABEL KINDS=blind LIMIT=${LIMIT:-0} TOP_K=6 OUT_DIR=experiments/e2e/results uv run python evals/answer_eval.py
echo "== api log reranker warnings:"; docker compose $F logs api 2>&1 | grep -ci "rerank.*\(fail\|timeout\|error\)"
docker compose $F logs api 2>&1 | grep -i "rerank" | grep -i "fail\|timeout\|warn" | head -3
curl -s localhost:11435/api/ps | head -c 800
echo; echo "== ollama truncation warnings: $(grep -c -i truncat $LOG.ollama.log)"
