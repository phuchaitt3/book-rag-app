"""The serving benchmark's Kaggle runner builds a valid kernel and never calls Kaggle (#245)."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

PATH = Path(__file__).resolve().parents[3] / "experiments" / "serving" / "kaggle_run.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("serving_kaggle_run", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_writes_compilable_kernel_and_metadata(tmp_path: Path) -> None:
    run = load()
    out = run.build("someone", tmp_path)
    meta = json.loads((out / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert meta["id"] == "someone/book-rag-vllm-serving"
    assert meta["enable_gpu"] is True
    source = (out / meta["code_file"]).read_text(encoding="utf-8")
    assert "__CFG__" not in source
    compile(source, "kernel", "exec")


def test_smoke_does_not_call_kaggle(monkeypatch: pytest.MonkeyPatch) -> None:
    run = load()

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("smoke must not run a subprocess")

    monkeypatch.setattr(subprocess, "run", boom)
    assert run.main(["--smoke"]) == 0


def test_parse_status() -> None:
    assert load().parse_status('has status "KernelWorkerStatus.RUNNING"') == "RUNNING"
