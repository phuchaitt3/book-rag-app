"""Stub OpenAI-compatible server that records the prompts the app sends (#245).

Point the app at it (`LLM_PROVIDER=openai`, `LLM_BASE_URL=http://host.docker.internal:8081`) and
ask each question once through `POST /books/{id}/chat`: the app builds its prompt (retrieval,
reranking, `prompts.build_messages`) exactly as in production, sends it here, and gets a one-token
answer back. Each request body is appended to the output file as one JSON line, so the Kaggle job
needs no database, embedder or reranker. Standard library only.

    python experiments/serving/capture_stub.py OUT.jsonl [PORT]
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHUNK = {
    "id": "stub",
    "object": "chat.completion.chunk",
    "choices": [{"index": 0, "delta": {"content": "ok"}}],
}


def make_handler(out: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, ensure_ascii=False) + "\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps(CHUNK)}\n\ndata: [DONE]\n\n".encode())

        def log_message(self, *args: object) -> None:
            pass

    return Handler


def main() -> None:
    out = Path(sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8081
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(out)).serve_forever()


if __name__ == "__main__":
    main()
