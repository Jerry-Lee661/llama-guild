"""Unit tests that need no network/GPU: adapter parsing + JSON profile loading
+ provider gating. Run: python -m pytest tests/ (or python tests/test_offline.py)
"""

import json
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from llama_multimodel_mcp import env_amd_adapter, providers  # noqa: E402
from llama_multimodel_mcp.config import reset_config  # noqa: E402
from llama_multimodel_mcp.profiles import _from_json  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent.parent / "examples" / "launch-commands.example.ps1"


def test_adapter_parses_example():
    res = env_amd_adapter.parse_env_amd(str(EXAMPLE))
    assert len(res.profiles) == 3, f"expected 3 profiles, got {len(res.profiles)}"
    # scenario naming: code + writing share port 8081
    ids = [p.id for p in res.profiles]
    assert any(p.id.endswith("-code") for p in res.profiles), ids
    assert any(p.id.endswith("-writing") for p in res.profiles), ids
    code = next(p for p in res.profiles if p.id.endswith("-code"))
    assert code.port == 8081 and code.ctx == 65536
    assert code.flags["--temp"] == "0.6"
    assert not res.issues, res.issues


def test_adapter_detects_orphaned_flags():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
        f.write("C:\\bin\\llama-server.exe `\n")
        f.write("  -m /models/x.gguf `\n")
        f.write("  --port 8090 `\n")
        f.write("  -c 4096\n")
        f.write("  --mmproj /models/x-mmproj.gguf `\n")
        tmp = f.name
    try:
        res = env_amd_adapter.parse_env_amd(tmp)
        kinds = [i.kind for i in res.issues]
        assert "orphaned_flags" in kinds
        assert any("--mmproj" in " ".join(p.orphaned_flags) for p in res.profiles)
    finally:
        os.unlink(tmp)


def test_json_profile_openai_compatible():
    reset_config()
    d = {"provider": "openai-compatible", "tier": "quality",
         "base_url": "http://127.0.0.1:1234", "model_id": "m1"}
    p = _from_json("lmstudio", d)
    assert p.provider == "openai-compatible" and p.port == 1234
    assert p.base_url == "http://127.0.0.1:1234" and p.model == "m1"


def test_json_profile_args_dict_to_tokens():
    reset_config()
    d = {"provider": "llama-server", "tier": "bulk", "port": 8082,
         "ctx": 8192, "model": "/m.gguf",
         "args": {"-ngl": "99", "--jinja": None, "--temp": "0.7"}}
    p = _from_json("bulk", d)
    assert "-ngl" in p.raw_args and "--jinja" in p.raw_args
    assert p.flags["--temp"] == "0.7" and p.flags["--jinja"] is None


def test_provider_gating():
    assert providers.supports("llama-server", "bench")
    assert not providers.supports("openai-compatible", "bench")
    try:
        providers.require("openai-compatible", "start_profile")
        raise AssertionError("should have raised")
    except providers.UnsupportedFeature as e:
        assert "llama-server" in str(e)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
