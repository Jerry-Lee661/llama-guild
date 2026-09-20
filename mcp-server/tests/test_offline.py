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


def test_log_path_traversal_rejected():
    from llama_multimodel_mcp import process_mgr
    for evil in (r"..\..\evil", "../../etc/passwd", "/abs/path", "a/b", "..", "a..b"):
        try:
            process_mgr.log_path_for(evil)
            raise AssertionError(f"should have rejected {evil!r}")
        except ValueError:
            pass
    ok = process_mgr.log_path_for("qwen3.8-27b-uncensored")
    assert ok.endswith("qwen3.8-27b-uncensored.log")
    router = process_mgr.log_path_for("router-8081")
    assert router.endswith("router-8081.log")


def test_default_profile(tmp_path=None):
    import tempfile
    from llama_multimodel_mcp.profiles import read_default_id, _from_json
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"default": "lmstudio",
                   "profiles": {"lmstudio": {"provider": "openai-compatible",
                                             "base_url": "http://127.0.0.1:1234"}}}, f)
        tmp = f.name
    try:
        assert read_default_id(tmp) == "lmstudio"
        assert read_default_id(str(tmp_path or "Z:/definitely/missing.json")) is None
        p = _from_json("lmstudio", {"provider": "openai-compatible",
                                    "base_url": "http://127.0.0.1:1234", "model_id": None})
        assert p.model == "" and p.base_url.endswith(":1234")
    finally:
        os.unlink(tmp)


def test_build_args_injects_model_and_port():
    from llama_multimodel_mcp.server import _build_args
    # JSON 元数据档位：model/port 存结构化字段，args 只含附加 flag
    p = _from_json("meta", {"provider": "llama-server", "port": 8187,
                            "model": "/models/m.gguf",
                            "args": {"-np": "1", "-ngl": "99"}})
    args = _build_args(p, None, None)
    assert args[args.index("-m") + 1] == "/models/m.gguf"
    assert args[args.index("--port") + 1] == "8187"
    assert args.count("-m") == 1 and args.count("--port") == 1


def test_build_args_idempotent_for_raw_args():
    from llama_multimodel_mcp.server import _build_args
    # env-amd 档位：-m/--port 已在 raw_args 原样携带，不得重复注入
    p = _from_json("raw", {"provider": "llama-server", "port": 8081,
                           "model": "/models/m.gguf",
                           "args": ["-m", "/models/other.gguf", "--port", "8081",
                                    "-ngl", "99"]})
    args = _build_args(p, None, None)
    assert args.count("-m") == 1 and args.count("--port") == 1
    assert args[args.index("-m") + 1] == "/models/other.gguf"


def test_start_profile_refuses_profile_without_model():
    from llama_multimodel_mcp import server
    p = _from_json("broken", {"provider": "llama-server", "port": 8091,
                              "args": {"-ngl": "99"}})
    assert p.model == ""
    saved = (server.find_profile,
             server.process_mgr.port_listener_pid,
             server.process_mgr.vram_conflicts,
             server.process_mgr.start_profile)
    server.find_profile = lambda pid: p
    server.process_mgr.port_listener_pid = lambda port: None
    server.process_mgr.vram_conflicts = lambda w, d="default": []

    def _must_not_launch(*a, **k):
        raise AssertionError("must not launch")

    server.process_mgr.start_profile = _must_not_launch
    try:
        try:
            server.start_profile("broken")
            raise AssertionError("should have raised")
        except ValueError as e:
            assert "定义不完整" in str(e)
    finally:
        (server.find_profile,
         server.process_mgr.port_listener_pid,
         server.process_mgr.vram_conflicts,
         server.process_mgr.start_profile) = saved


def test_profile_device_vram_gb_and_remote_host():
    reset_config()
    r = _from_json("r", {"provider": "llama-server", "host": "192.168.1.50",
                         "port": 8191, "model": "/m.gguf",
                         "device": "gpu1", "vram_gb": 9.5})
    assert r.remote and r.base_url == "http://192.168.1.50:8191"
    assert r.device == "gpu1" and r.vram_gb == 9.5 and r.host == "192.168.1.50"
    loc = _from_json("l", {"provider": "llama-server", "host": "127.0.0.1",
                           "port": 8191, "model": "/m.gguf"})
    assert not loc.remote and loc.base_url == "http://127.0.0.1:8191"
    plain = _from_json("p", {"provider": "llama-server", "port": 8192, "model": "/m.gguf"})
    assert plain.device == "default" and plain.host is None and not plain.remote


def test_vram_conflicts_scoped_by_device():
    from llama_multimodel_mcp import process_mgr
    reset_config()
    snap = {"used_estimated_gb": 15.0, "budget_gb": 20.0,
            "per_port": {8191: {"estimated_gb": 15.0, "device": "gpu0"}},
            "by_device": {"gpu0": {"used_estimated_gb": 15.0, "budget_gb": 24.0},
                          "gpu1": {"used_estimated_gb": 0.0, "budget_gb": 12.0}}}
    saved = process_mgr.vram_snapshot
    process_mgr.vram_snapshot = lambda: snap
    try:
        assert process_mgr.vram_conflicts(15.0, "gpu0"), "gpu0 15+15=30>24 应冲突"
        assert process_mgr.vram_conflicts(15.0, "gpu1"), "gpu1 0+15=15>12 应冲突"
        assert not process_mgr.vram_conflicts(9.5, "gpu1"), \
            "gpu1 9.5GB 可放；旧全局逻辑会拿别池的 15GB 误判"
    finally:
        process_mgr.vram_snapshot = saved


def test_instance_device_resolution():
    from llama_multimodel_mcp import profiles as profiles_mod, process_mgr
    gpu1 = _from_json("g", {"provider": "llama-server", "port": 8195,
                            "model": "/m.gguf", "device": "gpu1"})
    saved = profiles_mod.find_profile
    profiles_mod.find_profile = lambda pid: gpu1
    try:
        assert process_mgr.instance_device({"source": "g"}) == "gpu1"
        assert process_mgr.instance_device({"source": "external"}) == "default"
    finally:
        profiles_mod.find_profile = saved


def test_switch_profile_stops_same_pool_only():
    import types
    from llama_multimodel_mcp import profiles as profiles_mod, process_mgr, server
    reset_config()
    tgt = _from_json("t", {"provider": "llama-server", "port": 8195,
                           "model": "~/m.gguf", "device": "gpu1"})
    oth = _from_json("o", {"provider": "llama-server", "port": 8196,
                           "model": "~/m.gguf", "device": "gpu0"})
    saved = (profiles_mod.find_profile, server.find_profile,
             process_mgr.find_servers, process_mgr.stop_tree,
             process_mgr.port_listener_pid, process_mgr.vram_conflicts,
             process_mgr.start_profile, process_mgr.wait_health,
             server.time.sleep)
    by_id = {"t": tgt, "o": oth}
    profiles_mod.find_profile = lambda pid: by_id[pid]
    server.find_profile = lambda pid: by_id[pid]
    process_mgr.find_servers = lambda: [
        {"pid": 111, "port": 8195, "source": "t", "model": "/m.gguf"},
        {"pid": 222, "port": 8196, "source": "o", "model": "/m.gguf"}]
    killed: list[int] = []
    process_mgr.stop_tree = lambda pid: killed.append(pid) or True
    process_mgr.port_listener_pid = lambda port: None
    process_mgr.vram_conflicts = lambda w, d="default": []
    process_mgr.start_profile = lambda exe, args, pid, extra=None: types.SimpleNamespace(pid=999)
    process_mgr.wait_health = lambda port, timeout=300.0: {"status": "ok"}
    server.time.sleep = lambda s: None
    real_isfile = os.path.isfile
    os.path.isfile = lambda p: True
    try:
        out = server.switch_profile("t")
        assert killed == [111], f"只应停同池 gpu1 的 111，实际: {killed}"
        assert out["device_pool"] == "gpu1" and out["started"]["pid"] == 999
    finally:
        os.path.isfile = real_isfile
        (profiles_mod.find_profile, server.find_profile,
         process_mgr.find_servers, process_mgr.stop_tree,
         process_mgr.port_listener_pid, process_mgr.vram_conflicts,
         process_mgr.start_profile, process_mgr.wait_health,
         server.time.sleep) = saved


def test_remote_profile_lifecycle_refused():
    from llama_multimodel_mcp import server
    from llama_multimodel_mcp.providers import UnsupportedFeature
    reset_config()
    r = _from_json("remote", {"provider": "llama-server", "host": "10.0.0.9",
                              "port": 8191, "model": "/m.gguf"})
    saved = server.find_profile
    server.find_profile = lambda pid: r
    try:
        for fn in (server.start_profile, server.stop_profile, server.switch_profile):
            try:
                fn("remote")
                raise AssertionError(f"{fn.__name__} should have refused")
            except UnsupportedFeature as e:
                assert "远程" in str(e)
    finally:
        server.find_profile = saved


def test_record_usage_falls_back_when_props_unavailable():
    from llama_multimodel_mcp import llama_client
    reset_config()

    def _404(base):
        raise llama_client.LlamaHTTPError("HTTP 404 GET /props")

    captured: dict = {}
    saved = (llama_client.props, llama_client.stats.record)
    llama_client.props = _404
    llama_client.stats.record = lambda model, *a, **k: captured.update(model=model)
    try:
        llama_client.record_usage("http://127.0.0.1:1234", {"total_ms": 5},
                                  {"prompt_tokens": 1, "completion_tokens": 2},
                                  resp_model=None, source="chat")
        assert captured["model"] == "endpoint-http://127.0.0.1:1234", \
            "/props 不可用时统计不应被丢弃，应落到 endpoint 名"
        llama_client.record_usage(8081, {}, {}, resp_model="m.gguf", source="chat")
        assert captured["model"] == "m.gguf"
    finally:
        llama_client.props, llama_client.stats.record = saved


def test_preflight_capacity_and_gate():
    from llama_multimodel_mcp import preflight as pf

    # args parsing: --ctx-size / --parallel, defaults
    assert pf.parse_args_capacity(["--ctx-size", "262144", "--parallel", "2"]) == 131072
    assert pf.parse_args_capacity(["-c", "65536"]) == 65536
    assert pf.parse_args_capacity(["--jinja"]) is None

    # router /models payload: loaded model meta.n_ctx, per-model selection
    models = [
        {"id": "qwen38-27b", "status": {"value": "unloaded", "args": ["--ctx-size", "65536"]}},
        {"id": "tiel-q6", "status": {"value": "loaded", "args": ["--ctx-size", "262144", "--parallel", "2"]},
         "meta": {"n_ctx": 131072}},
    ]
    cap = pf.models_capacity(models)                      # loaded wins; no model → None
    assert cap == {"slot_ctx": 131072, "model": None, "loaded": True}
    cap = pf.models_capacity(models, model="qwen38-27b")  # unloaded target: parsed from args
    assert cap == {"slot_ctx": 65536, "model": "qwen38-27b", "loaded": False}

    # parallel>1 with meta.n_ctx reporting training ctx: args-derived wins
    # (observed on x99 2026-09-19: meta 262144, real slot 262144/2=131072)
    models2 = [{"id": "2x-tiel-q6-262k-n2", "status": {"value": "sleeping",
               "args": ["--ctx-size", "262144", "--parallel", "2"]},
               "meta": {"n_ctx": 262144, "n_ctx_train": 262144}}]
    cap2 = pf.models_capacity(models2, model="2x-tiel-q6-262k-n2")
    assert cap2 == {"slot_ctx": 131072, "model": "2x-tiel-q6-262k-n2", "loaded": False}

    # gate: over budget → structured rejection; within → None
    d = pf.decision(134000, 4096, 131072)
    assert d["error"]["type"] == "context_exceeded" and d["error"]["retryable"] is False
    assert d["error"]["prompt_tokens"] == 134000 and d["error"]["slot_ctx"] == 131072
    assert pf.decision(1000, 256, 131072) is None

    # heuristic leg: absurd request rejected without tokenizing
    cap = {"slot_ctx": 131072, "model": "m", "loaded": False}
    d = pf.gate("x" * 400000, 4096, cap,
                count_exact=lambda m: (_ for _ in ()).throw(RuntimeError("must not tokenize")))
    assert d["error"]["type"] == "context_exceeded"

    # moderate request on non-loaded model: 90%-headroom heuristic, allow
    assert pf.gate("x" * 3000, 4096, cap,
                   count_exact=lambda m: (_ for _ in ()).throw(RuntimeError("no tokenize"))) is None
    # near-limit on non-loaded model: rejected with headroom
    d = pf.gate("x" * (131072 * 3), 4096, cap,
                count_exact=lambda m: (_ for _ in ()).throw(RuntimeError("no tokenize")))
    assert d["error"]["type"] == "context_exceeded"

    # loaded model: exact tokenize leg runs; over → exact-number rejection
    cap_loaded = {"slot_ctx": 131072, "model": "m", "loaded": True}
    d = pf.gate("x" * 400000, 4096, cap_loaded, count_exact=lambda m: 134000)
    assert d["error"]["prompt_tokens"] == 134000 and d["error"]["type"] == "context_exceeded"
    assert pf.gate("x" * 3000, 256, cap_loaded, count_exact=lambda m: 12) is None

    # fail-open: unknown capacity allows the request
    assert pf.gate("x" * 10**7, 4096, None, count_exact=lambda m: 1) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
