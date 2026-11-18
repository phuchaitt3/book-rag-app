import base64
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from types import ModuleType

PATH = Path(__file__).resolve().parents[3] / "scripts" / "kaggle_run.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kaggle_run", PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kaggle_run = _load()


def test_build_embeds_bundle_and_writes_private_gpu_metadata(tmp_path: Path, monkeypatch) -> None:
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text('{"id": "x"}\n')
    monkeypatch.setattr(kaggle_run, "BUILD", tmp_path / "build")
    out = kaggle_run.build("serving", prompts, "someone")
    meta = json.loads((out / "kernel-metadata.json").read_text())
    assert meta["id"] == "someone/book-rag-serving-bench"
    assert meta["title"].replace(" ", "-") == "book-rag-serving-bench"
    assert meta["is_private"] and meta["enable_gpu"] and meta["enable_internet"]
    script = (out / "script.py").read_text()
    assert "__BUNDLE__" not in script and "__COMMIT__" not in script
    encoded = script.split('BUNDLE = "', 1)[1].split('"', 1)[0]
    names = zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))).namelist()
    assert sorted(names) == ["concurrency_bench.py", "measure.py", "prompts.jsonl"]
    compile(script, "script.py", "exec")  # the generated kernel is valid Python
