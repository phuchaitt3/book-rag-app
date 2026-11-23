"""Build, push and fetch the vLLM (AWQ) serving benchmark on a Kaggle T4 (#245).

Follows the pattern of the thesis repository's ``tools/kaggle_run.py``: the kernel is generated
from files in this repository, never edited by hand, and the ``kaggle`` CLI does the pushing.

    python experiments/serving/kaggle_run.py build               # writes build/kaggle/serving/
    python experiments/serving/kaggle_run.py --smoke             # build, compile, no CLI call
    python experiments/serving/kaggle_run.py push --owner NAME   # uses the free GPU quota
    python experiments/serving/kaggle_run.py status --owner NAME
    python experiments/serving/kaggle_run.py output --owner NAME # to build/kaggle/serving/output/

``--smoke`` (also ``--dry-run``) builds the kernel into a temporary folder, compiles it and prints
the metadata and the benchmark settings. It never calls ``kaggle`` and never reads credentials.
The Kaggle account name comes from ``--owner`` or ``KAGGLE_OWNER``; credentials stay in the CLI's
own config.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "kaggle" / "serving"
SLUG = "book-rag-vllm-serving"
DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct-AWQ"
DEFAULT_CONCURRENCY = (1, 2, 4, 8, 16)

# Runs on the Kaggle T4. It installs vLLM, serves the model on an OpenAI-compatible port and
# measures time to first token and streamed characters per second at each concurrency level,
# with the standard library only. `build` injects the settings as JSON in place of __CFG__.
KERNEL_SOURCE = r'''
import json
import subprocess
import sys
import threading
import time
import urllib.request

CFG = json.loads(r"""__CFG__""")
PORT = 8000

subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "vllm==" + CFG["vllm_version"]], check=True
)
server = subprocess.Popen(
    [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", CFG["model"],
        "--quantization", "awq", "--dtype", "half",
        "--max-model-len", str(CFG["max_model_len"]), "--port", str(PORT),
    ]
)
base = f"http://127.0.0.1:{PORT}"
for _ in range(180):
    try:
        urllib.request.urlopen(base + "/v1/models", timeout=2).read()
        break
    except Exception:
        time.sleep(5)
else:
    raise SystemExit("vllm did not start")


def one(prompt, out):
    body = json.dumps(
        {
            "model": CFG["model"], "stream": True, "max_tokens": CFG["max_tokens"],
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        base + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    start, first, chars = time.perf_counter(), None, 0
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            piece = (json.loads(line[5:])["choices"][0].get("delta") or {}).get("content")
            if piece:
                first = first or time.perf_counter()
                chars += len(piece)
    end = time.perf_counter()
    out.append({"ttft_s": (first or end) - start, "total_s": end - start, "chars": chars})


results = {"config": CFG, "levels": []}
for level in CFG["concurrency"]:
    out = []
    began = time.perf_counter()
    for _round in range(CFG["requests_per_level"]):
        group = [
            threading.Thread(target=one, args=(CFG["prompt"] + f" ({i})", out))
            for i in range(level)
        ]
        for t in group:
            t.start()
        for t in group:
            t.join()
    wall = time.perf_counter() - began
    out.sort(key=lambda r: r["ttft_s"])
    results["levels"].append(
        {
            "concurrency": level, "requests": len(out), "wall_s": wall,
            "ttft_p50_s": out[len(out) // 2]["ttft_s"], "ttft_max_s": out[-1]["ttft_s"],
            "chars_per_s": sum(r["chars"] for r in out) / wall,
        }
    )
    print(results["levels"][-1], flush=True)
server.terminate()
with open("/kaggle/working/serving_results.json", "w") as f:
    json.dump(results, f, indent=2)
'''


def settings(
    model: str = DEFAULT_MODEL, concurrency: tuple[int, ...] = DEFAULT_CONCURRENCY
) -> dict[str, Any]:
    return {
        "model": model,
        "vllm_version": "0.6.3.post1",
        "max_model_len": 4096,
        "max_tokens": 256,
        "requests_per_level": 2,
        "concurrency": list(concurrency),
        "prompt": "Trả lời ngắn gọn: vì sao bầu trời có màu xanh?",
    }


def build(owner: str, build_dir: Path = BUILD, cfg: dict[str, Any] | None = None) -> Path:
    """Write the kernel script and ``kernel-metadata.json`` into ``build_dir``."""
    cfg = cfg or settings()
    build_dir.mkdir(parents=True, exist_ok=True)
    code_file = f"{SLUG}.py"
    (build_dir / code_file).write_text(
        KERNEL_SOURCE.replace("__CFG__", json.dumps(cfg, ensure_ascii=False)), encoding="utf-8"
    )
    metadata = {
        "id": f"{owner}/{SLUG}",
        "title": SLUG.replace("-", " "),
        "code_file": code_file,
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [],
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }
    (build_dir / "kernel-metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return build_dir


def parse_status(text: str) -> str:
    """The state name in ``kaggle kernels status`` output (``... "KernelWorkerStatus.RUNNING"``)."""
    return text.strip().rsplit(".", 1)[-1].strip('" ')


def _kaggle(*args: str) -> None:
    subprocess.run(["kaggle", *args], check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", nargs="?", choices=["build", "push", "status", "output"])
    parser.add_argument("--owner", default=os.environ.get("KAGGLE_OWNER", ""))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--smoke", "--dry-run", dest="smoke", action="store_true")
    args = parser.parse_args(argv)
    cfg = settings(args.model)

    if args.smoke:
        with tempfile.TemporaryDirectory() as tmp:
            out = build(args.owner or "OWNER", Path(tmp), cfg)
            compile((out / f"{SLUG}.py").read_text(encoding="utf-8"), SLUG, "exec")
            print((out / "kernel-metadata.json").read_text(encoding="utf-8"))
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        print("smoke: kernel built and compiled; nothing pushed, no kaggle call")
        return 0
    if args.command is None:
        parser.error("give a command or --smoke")
    if args.command == "build":
        print(f"built {build(args.owner or 'OWNER', cfg=cfg)}")
        return 0
    if not args.owner:
        parser.error("--owner or KAGGLE_OWNER is required")
    ref = f"{args.owner}/{SLUG}"
    if args.command == "push":
        _kaggle("kernels", "push", "-p", str(build(args.owner, cfg=cfg)))
    elif args.command == "status":
        _kaggle("kernels", "status", ref)
    else:
        (BUILD / "output").mkdir(parents=True, exist_ok=True)
        _kaggle("kernels", "output", ref, "-p", str(BUILD / "output"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
