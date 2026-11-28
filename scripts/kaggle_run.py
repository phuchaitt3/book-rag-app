"""Build, push, wait for and fetch a Kaggle GPU kernel from files in this repository (#245).

Pattern: the thesis repository's `tools/kaggle_run.py` (build, push, wait, fetch). It uses the
`kaggle` CLI you are already logged in with; this script never reads the credential files.

Kernels are *generated*: a bundle of repository files (zip, base64) is embedded in a script
template, so a kernel needs no Kaggle dataset. Two kernels exist today:

    serving  experiments/serving/kaggle_kernel.py.tmpl: vLLM (AWQ) and Ollama on one T4,
             concurrency benchmark of `experiments/serving/concurrency_bench.py`

Usage (from the repository root)::

    python scripts/kaggle_run.py build serving --prompts experiments/serving/data/prompts-208.jsonl
    python scripts/kaggle_run.py push serving      # starts the run: uses the free weekly GPU quota
    python scripts/kaggle_run.py status serving
    python scripts/kaggle_run.py wait serving      # polls every 60 s, then downloads the output
    python scripts/kaggle_run.py output serving    # downloads to build/kaggle/serving-output/

`build/` is git-ignored. The kernel is private, GPU on, internet on (it downloads weights and
installs vLLM). Internet in kernels needs a phone-verified Kaggle account.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "kaggle"

SERVING: dict = {
    "template": ROOT / "experiments" / "serving" / "kaggle_kernel.py.tmpl",
    "files": {
        "experiments/serving/measure.py": "measure.py",
        "experiments/serving/concurrency_bench.py": "concurrency_bench.py",
    },
    "prompts_as": "prompts.jsonl",
}
# kernel name -> (slug, template, files copied into the bundle: path in repo -> path in bundle,
# vars: more placeholders of the template)
KERNELS: dict[str, dict] = {
    "serving": {
        **SERVING,
        "slug": "book-rag-serving-bench",
        "vars": {
            "__VLLM_MODEL__": "Qwen/Qwen2.5-3B-Instruct-AWQ",
            "__OLLAMA_MODEL__": "qwen2.5:3b-instruct",
        },
    },
    # The same comparison on the app's default model size (#245 amendment).
    "serving-05b": {
        **SERVING,
        "slug": "book-rag-serving-bench-05b",
        "vars": {
            "__VLLM_MODEL__": "Qwen/Qwen2.5-0.5B-Instruct-AWQ",
            "__OLLAMA_MODEL__": "qwen2.5:0.5b-instruct",
        },
    },
}
FINAL_STATES = ("complete", "error", "cancel")


def make_bundle(
    files: dict[str, str], prompts: Path | None, prompts_as: str, limit: int = 0
) -> str:
    """Zip the named repository files (and the prompts file) and return them base64-encoded.

    `limit` keeps only the first n prompts, for a smoke kernel.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, dest in files.items():
            zf.write(ROOT / src, dest)
        if prompts is not None:
            rows = prompts.read_text(encoding="utf-8").splitlines(keepends=True)
            zf.writestr(prompts_as, "".join(rows[:limit] if limit else rows))
    return base64.b64encode(buf.getvalue()).decode()


def commit() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip() or "unknown"


def owner() -> str:
    """The logged-in Kaggle user name, from `kaggle config view` (the key is never read)."""
    out = subprocess.run(["kaggle", "config", "view"], capture_output=True, text=True, check=True)
    for line in out.stdout.splitlines():
        if line.strip().startswith("- username:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("kaggle CLI is not logged in (no username in `kaggle config view`)")


def build(name: str, prompts: Path | None, user: str, limit: int = 0) -> Path:
    spec = KERNELS[name]
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=True)
    script = (
        spec["template"]
        .read_text(encoding="utf-8")
        .replace("__BUNDLE__", make_bundle(spec["files"], prompts, spec["prompts_as"], limit))
        .replace("__COMMIT__", commit())
    )
    for placeholder, value in spec.get("vars", {}).items():
        script = script.replace(placeholder, value)
    (out / "script.py").write_text(script, encoding="utf-8")
    meta = {
        "id": f"{user}/{spec['slug']}",
        "title": spec["slug"].replace("-", " "),  # Kaggle derives the slug from the title
        "code_file": "script.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out


def kaggle(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["kaggle", *args], capture_output=True, text=True)


def status(ref: str) -> str:
    """Lower-case status word of the latest run, e.g. running, complete, error."""
    text = kaggle("kernels", "status", ref).stdout.lower()
    for word in ("running", "queued", "complete", "error", "cancel"):
        if word in text:
            return word
    return text.strip() or "unknown"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("cmd", choices=["build", "push", "status", "wait", "output"])
    p.add_argument("kernel", choices=sorted(KERNELS))
    p.add_argument("--prompts", type=Path, help="prompts file to embed (build)")
    p.add_argument("--limit", type=int, default=0, help="embed only the first n prompts (smoke)")
    p.add_argument("--timeout-s", type=int, default=3 * 3600, help="kernel run limit (push)")
    args = p.parse_args()

    user = owner()
    ref = f"{user}/{KERNELS[args.kernel]['slug']}"
    folder = BUILD / args.kernel
    if args.cmd == "build":
        print(build(args.kernel, args.prompts, user, args.limit))
    elif args.cmd == "push":
        res = kaggle(
            "kernels",
            "push",
            "-p",
            str(folder),
            "--accelerator",
            "NvidiaTeslaT4",
            "-t",
            str(args.timeout_s),
        )
        print(res.stdout, res.stderr)
        sys.exit(res.returncode)
    elif args.cmd == "status":
        print(status(ref))
    elif args.cmd in ("wait", "output"):
        if args.cmd == "wait":
            while (s := status(ref)) not in FINAL_STATES:
                print(time.strftime("%H:%M:%S"), s, flush=True)
                time.sleep(60)
            print("final state:", s)
        dest = BUILD / f"{args.kernel}-output"
        dest.mkdir(parents=True, exist_ok=True)
        res = kaggle("kernels", "output", ref, "-p", str(dest))
        print(res.stdout, res.stderr)


if __name__ == "__main__":
    main()
