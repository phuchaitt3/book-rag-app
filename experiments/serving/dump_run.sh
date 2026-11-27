#!/bin/bash
# Dump the 208 prompts the app builds (#245). Run under the lock with Git Bash:
#   python ~/claude-config/scripts/gpu_run.py run --wait -- "C:/Program Files/Git/bin/bash.exe" experiments/serving/dump_run.sh <log-prefix>
# Needs the book PDF at $PDF (default: the #285 worktree's copy). The answer LLM is the capture
# stub (no model); the embedder runs in a private Ollama on port 11436. Always tears down.
cd "$(dirname "$0")/../.." || exit 6
PDF=${PDF:-../285-real-llm/experiments/e2e/data/vsl.pdf}
# LIMIT=3 is the smoke run: the first 3 questions, written beside the real output.
export COMPOSE_PROJECT_NAME=dump245 LLM_PROVIDER=openai LLM_BASE_URL=http://host.docker.internal:8081
export RERANKER_OWNER=245-vllm
cat > $1.override.yaml <<'Y'
services:
  api:
    environment:
      OLLAMA_URL: http://host.docker.internal:11436
      CHAT_RATE_LIMIT: "0"
  worker:
    environment:
      OLLAMA_URL: http://host.docker.internal:11436
Y
F="-f compose.yaml -f compose.reranker.yaml -f $1.override.yaml"
mkdir -p experiments/serving/data
cleanup() {
  echo "== teardown"; docker compose $F down 2>&1 | tail -3
  [ -n "$OPID" ] && kill $OPID 2>/dev/null
  [ -n "$SPID" ] && kill $SPID 2>/dev/null
}
trap cleanup EXIT
OLLAMA_HOST=127.0.0.1:11436 OLLAMA_KEEP_ALIVE=30m ollama serve > $1.ollama.log 2>&1 &
OPID=$!
sleep 8
docker info >/dev/null 2>&1 || { echo NO DOCKER; exit 5; }
git rev-parse HEAD
docker compose $F up -d --build --scale qdrant=0 --scale web=0 2>&1 | tail -12
for i in $(seq 1 60); do curl -sf localhost:8000/health >/dev/null 2>&1 && break; sleep 5; done
RESP=$(python - <<P
import urllib.request, json, uuid, os
b = uuid.uuid4().hex
pdf = open(os.environ.get("PDF", "$PDF"), "rb").read()
body = (f"--{b}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nViet Nam su luoc Q1\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"vsl.pdf\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{b}--\r\n".encode()
r = urllib.request.Request("http://localhost:8000/books", data=body, headers={"X-Dev-User": "dev-user", "Content-Type": f"multipart/form-data; boundary={b}"})
print(urllib.request.urlopen(r, timeout=120).read().decode())
P
)
echo "upload: $RESP"
BOOK_ID=$(echo "$RESP" | python -c "import sys,json;print(json.load(sys.stdin)['book']['id'])")
[ -z "$BOOK_ID" ] && { echo NO BOOK; exit 4; }
for i in $(seq 1 240); do
  S=$(docker compose $F exec -T db psql -U bookrag -tAc "select status from ingestion_jobs order by created_at desc limit 1" 2>/dev/null)
  echo "job: $S"; [ "$S" = "succeeded" ] && break; [ "$S" = "failed" ] && { echo INGEST FAILED; exit 3; }; sleep 15
done
rm -f $1.captured.jsonl
python experiments/serving/capture_stub.py $1.captured.jsonl 8081 > $1.stub.log 2>&1 &
SPID=$!
sleep 2
OUT=experiments/serving/data/prompts-208.jsonl
[ -n "$LIMIT" ] && OUT=experiments/serving/data/prompts-smoke.jsonl
BOOK_ID=$BOOK_ID LIMIT=${LIMIT:-0} python experiments/serving/dump_prompts.py $1.captured.jsonl $OUT
sha256sum $OUT
wc -l $OUT
