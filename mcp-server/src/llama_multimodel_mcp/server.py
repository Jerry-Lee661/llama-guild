"""llama-multimodel-mcp: expose local model profiles, lifecycle, inference
debugging and token stats to coding agents (ZCode / Claude Code / Codex /
VS Code / DSH).

Config: ~/.llama-mm/config.json + ~/.llama-mm/profiles.json (see examples).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time

from mcp.server.fastmcp import FastMCP

from . import bench as bench_mod
from . import discovery as discovery_mod
from . import env_amd_adapter, llama_client, process_mgr, profiles as profiles_mod, stats
from .config import get_config
from .profiles import Profile, ProfileError, find_profile, load_profiles, read_default_id
from .providers import UnsupportedFeature, require

mcp = FastMCP(
    "llama-multimodel-mcp",
    instructions=(
        "本机模型档位与生命周期调试工具。配置：~/.llama-mm/profiles.json。"
        "典型流程：list_profiles 看档位 → start_profile/switch_profile 启动 → "
        "chat/complete 调试推理 → bench 测速 → server_status 看 VRAM → usage_stats 看统计。"
        "tier 字段驱动工作流路由：quality=高质量执行档，bulk=高速批量档。"
        "未指定 profile_id 时回退到 profiles.json 的 default 档位（未设置则要求用户指定）。"
        "provider=openai-compatible（LM Studio/Ollama/vLLM）仅支持推理与统计。"
        "局域网节点：lan_discover 浏览 _local-ai._tcp 并可注册为远程档位。"
    ),
)


# ---------- targeting helpers ----------

def _target(profile_id: str | None, port: int | None) -> tuple[int | str, Profile | None]:
    """Resolve a tool target to (base, profile). base = int port or full URL.
    Falls back to the profiles.json "default" profile when both are omitted."""
    if profile_id:
        p = find_profile(profile_id)
        base = p.base_url or (p.port if p.port is not None else None)
        if base is None:
            raise ProfileError(f"profile '{profile_id}' 缺少 port/base_url，无法定位实例")
        return base, p
    if port is not None:
        return port, None
    d = read_default_id()
    if d:
        p = find_profile(d)
        base = p.base_url or p.port
        if base is not None:
            return base, p
    raise ValueError(
        '需要 profile_id 或 port 之一；也可在 profiles.json 顶层设置 "default": "<档位id>" '
        '作为未指定时的回退')


def _need(profile: Profile | None, feature: str, port: int | None) -> None:
    """Gate llama-server-only features. Raw port targets are assumed llama-server."""
    if profile is not None:
        require(profile.provider, feature)


def _build_args(p: Profile, ctx: int | None, extra_args: list[str] | None) -> list[str]:
    args = list(p.raw_args)
    # JSON 档位的 model/port 存结构化字段、env-amd 档位在 raw_args 里原样携带；
    # 无论哪种来源，最终命令行必须带 -m 和 --port，否则 llama-server 会静默
    # 降级成 router 模式并绑默认端口 8080。
    if p.model and "-m" not in args and "--model" not in args:
        args += ["-m", p.model]
    if p.port is not None and "--port" not in args:
        args += ["--port", str(p.port)]
    if ctx is not None:
        if "-c" in args:
            args[args.index("-c") + 1] = str(ctx)
        else:
            args += ["-c", str(ctx)]
    if "--metrics" not in args:
        args.append("--metrics")  # token counters; VRAM gauges depend on build
    for a in extra_args or []:
        args += shlex.split(a) if " " in a else [a]
    return args


def _log_tail(path: str, tail: int) -> list[str] | None:
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()[-tail:]
    except OSError:
        return None


def _psutil_name(pid: int) -> str | None:
    import psutil
    try:
        return psutil.Process(pid).name()
    except psutil.NoSuchProcess:
        return None


# ---------- 1. profiles ----------

@mcp.tool()
def list_profiles(include_removed: bool = False) -> dict:
    """列出全部模型档位（provider、tier、端口、ctx、关键参数、权重）。tier: quality=高质量执行档, bulk=高速批量档。"""
    profs, issues = load_profiles()
    default = read_default_id()
    out = []
    for p in profs:
        if p.removed and not include_removed:
            continue
        out.append({
            "id": p.id, "provider": p.provider, "tier": p.tier or None,
            "default": p.id == default,
            "port": p.port, "ctx": p.ctx, "device": p.device,
            "remote_host": p.base_url if p.remote else None,
            "model": os.path.basename(p.model) if p.model else None,
            "draft_model": os.path.basename(p.draft_model) if p.draft_model else None,
            "vision": bool(p.mmproj), "weight_gb": p.weight_gb,
            "removed": p.removed, "line": p.line,
            "key_flags": {k: v for k, v in p.flags.items()
                          if k in ("--spec-type", "--spec-draft-n-max", "--reasoning",
                                   "--temp", "--top-p", "--top-k", "--n-predict")},
            "note": p.description[:200],
        })
    return {"count": len(out), "default": default, "profiles": out, "issues": issues or None}


# ---------- 2. status ----------

@mcp.tool()
def server_status() -> dict:
    """运行中的 llama-server 进程、监听端口、健康状态、VRAM 快照与预算检查。"""
    instances = []
    for inst in process_mgr.find_servers():
        entry: dict = {"pid": inst["pid"], "port": inst["port"], "source": inst["source"],
                       "model": os.path.basename(inst["model"]) if inst["model"] else None,
                       "started_at": inst["started_at"], "exe": inst["exe"]}
        if inst["port"]:
            entry["health"] = llama_client.health(inst["port"])["status"]
            try:
                pr = llama_client.props(inst["port"])
                entry["model_path"] = pr.get("model_path") if isinstance(pr, dict) else None
            except llama_client.LlamaHTTPError:
                pass
        instances.append(entry)
    vram = process_mgr.vram_snapshot()
    over = {d: v for d, v in vram.get("by_device", {}).items()
            if v["used_estimated_gb"] > v["budget_gb"]}
    ports: dict = {}
    for pp in load_profiles()[0]:
        if pp.port is not None and pp.provider == "llama-server":
            ports[str(pp.port)] = {"profile": pp.id, "tier": pp.tier or None}
    return {"instances": instances, "vram": vram,
            "vram_note": "used 为估算值（profile weight_gb/vram_gb）；实时 VRAM 需构建支持" if instances else None,
            "budget_warning": ("GPU 池超预算: " + "; ".join(
                f"{d} {v['used_estimated_gb']}/{v['budget_gb']}GB"
                for d, v in over.items()) if over else None),
            "profile_ports": ports}


# ---------- 3-6. lifecycle (llama-server only) ----------

def _profile_or_default(profile_id: str | None) -> Profile:
    if profile_id:
        return find_profile(profile_id)
    d = read_default_id()
    if d:
        return find_profile(d)
    raise ValueError(
        '需要 profile_id；也可在 profiles.json 顶层设置 "default": "<档位id>" 作为缺省')


@mcp.tool()
def start_profile(profile_id: str | None = None, ctx: int | None = None,
                  extra_args: list[str] | None = None, force: bool = False,
                  wait_seconds: float = 300.0) -> dict:
    """按档位启动 llama-server（ctx 可覆盖；profile_id 省略时用 profiles 的 default 档）。端口被占或 VRAM 超预算时拒绝（force=true 越过 VRAM 限制）。"""
    p = _profile_or_default(profile_id)
    require(p.provider, "start")
    if p.remote:
        raise UnsupportedFeature(
            f"profile {p.id} 指向远程 host（{p.base_url}），无法在本地启动；"
            "直接用 chat/complete/bench 调用它即可")
    if p.removed and not force:
        raise ValueError(f"profile {p.id} 标记为已移除（模型文件可能已删），确认请传 force=true")
    if p.model and not os.path.isfile(p.model) and not p.model.startswith("~"):
        raise ValueError(f"模型文件不存在: {p.model}")
    port = p.port
    if port is None:
        raise ValueError(f"profile {p.id} 缺少 port")
    listener = process_mgr.port_listener_pid(port)
    if listener is not None:
        raise ValueError(f"端口 {port} 已被 PID {listener} 监听，先 stop_profile 或 switch_profile")
    conflicts = process_mgr.vram_conflicts(p.vram_gb or p.weight_gb, p.device)
    if conflicts and not force:
        raise ValueError("VRAM 预算冲突:\n" + "\n".join(conflicts) + "\n确认启动请传 force=true")
    extra_path = None
    if p.needs_rocm_path:
        extra_path = get_config().rocm_smi_path and os.path.dirname(get_config().rocm_smi_path) or None
    final_args = _build_args(p, ctx, extra_args)
    if "-m" not in final_args and "--model" not in final_args:
        raise ValueError(
            f"profile {p.id} 定义不完整：model 字段为空且 args 里没有 -m/--model，"
            "拒绝启动（否则会静默起成无模型的 router 模式）")
    proc = process_mgr.start_profile(p.exe, final_args, p.id, extra_path)
    h = process_mgr.wait_health(port, wait_seconds)
    out = {"profile": p.id, "pid": proc.pid, "port": port, "ctx": ctx or p.ctx,
           "log": process_mgr.log_path_for(p.id), "health": h["status"]}
    if h["status"] != "ok":
        out["log_tail"] = _log_tail(process_mgr.log_path_for(p.id), 30)
        out["hint"] = "大模型加载可能超过等待时间，可稍后用 server_status 再查"
    return out


@mcp.tool()
def stop_profile(profile_id: str | None = None) -> dict:
    """停止某档位对应的 llama-server 实例（按监听端口定位，树杀；省略时用 default 档）。"""
    p = _profile_or_default(profile_id)
    require(p.provider, "stop")
    if p.remote:
        raise UnsupportedFeature(
            f"profile {p.id} 指向远程 host（{p.base_url}），本机没有它的进程可停")
    if p.port is None:
        raise ValueError(f"profile {p.id} 缺少 port")
    pid = process_mgr.port_listener_pid(p.port)
    if pid is None:
        return {"profile": p.id, "stopped": False, "note": f"端口 {p.port} 无监听进程"}
    name = (_psutil_name(pid) or "").lower()
    if "llama-server" not in name:
        raise ValueError(f"端口 {p.port} 的监听进程是 {name}（PID {pid}），不是 llama-server，拒绝停止")
    return {"profile": p.id, "pid": pid, "stopped": process_mgr.stop_tree(pid)}


@mcp.tool()
def stop_all() -> dict:
    """停止本机全部 llama-server 进程。"""
    return {"stopped": process_mgr.stop_all()}


@mcp.tool()
def switch_profile(profile_id: str | None = None, ctx: int | None = None, force: bool = False,
                   wait_seconds: float = 300.0) -> dict:
    """切换档位：停掉目标 GPU 池（profile.device）上的 llama-server 再启动目标档，
    其他池的实例不受影响（省略 profile_id 时用 default 档）。"""
    p = _profile_or_default(profile_id)
    require(p.provider, "switch")
    if p.remote:
        raise UnsupportedFeature(
            f"profile {p.id} 指向远程 host（{p.base_url}），无法在本地执行 switch")
    pool = p.device or "default"
    victims = [i["pid"] for i in process_mgr.find_servers()
               if process_mgr.instance_device(i) == pool]
    for pid in victims:
        process_mgr.stop_tree(pid)
    time.sleep(1)
    started = start_profile(profile_id, ctx=ctx, force=force, wait_seconds=wait_seconds)
    return {"stopped_pids": victims, "device_pool": pool, "started": started}


# ---------- 7-10. router mode (llama-server) ----------

@mcp.tool()
def start_router(port: int, models_dir: str = "~/models", models_max: int = 2,
                 autoload: bool = True, sleep_idle_seconds: int | None = None,
                 ctx: int = 8192, extra_args: list[str] | None = None) -> dict:
    """以 router 模式启动 llama-server（--models-dir），支持 /models/load|unload 热切换与 warm-up。"""
    if process_mgr.port_listener_pid(port) is not None:
        raise ValueError(f"端口 {port} 已被占用")
    cfg = get_config()
    args = ["--host", cfg.host, "--port", str(port),
            "--models-dir", os.path.expanduser(models_dir),
            "--models-max", str(models_max),
            "-c", str(ctx), "-ngl", "99", "--flash-attn", "on", "--metrics"]
    if not autoload:
        args.append("--no-models-autoload")
    if sleep_idle_seconds:
        args += ["--sleep-idle-seconds", str(sleep_idle_seconds)]
    for a in extra_args or []:
        args += shlex.split(a) if " " in a else [a]
    profile_id = f"router-{port}"
    proc = process_mgr.start_profile(cfg.server_exe, args, profile_id)
    h = process_mgr.wait_health(port, 120)
    return {"profile": profile_id, "pid": proc.pid, "port": port,
            "models_dir": models_dir, "health": h["status"],
            "log": process_mgr.log_path_for(profile_id)}


@mcp.tool()
def router_models(profile_id: str | None = None, port: int | None = None) -> dict:
    """列出 router 实例发现的模型及状态（loaded/loading/unloaded）。非 router 实例明确报错。"""
    base, p = _target(profile_id, port)
    _need(p, "router", None if isinstance(base, int) else port)
    return {"base": str(base), "models": llama_client.router_models(base)}


@mcp.tool()
def router_load(profile_id: str | None = None, port: int | None = None,
                model: str = "", wait: bool = True,
                wait_seconds: float = 600.0) -> dict:
    """router 模式加载模型（warm-up）；wait=true 时轮询直到 loaded。"""
    base, p = _target(profile_id, port)
    _need(p, "router", None if isinstance(base, int) else port)
    if not model:
        raise ValueError("需要 model 参数")
    return llama_client.router_load(base, model, wait, wait_seconds)


@mcp.tool()
def router_unload(profile_id: str | None = None, port: int | None = None,
                  model: str = "", wait: bool = True) -> dict:
    """router 模式卸载模型释放 VRAM。"""
    base, p = _target(profile_id, port)
    _need(p, "router", None if isinstance(base, int) else port)
    if not model:
        raise ValueError("需要 model 参数")
    return llama_client.router_unload(base, model, wait)


# ---------- 11-12. inference (both providers) ----------

@mcp.tool()
def chat(profile_id: str | None = None, port: int | None = None,
         messages: list[dict] | None = None, max_tokens: int = 256,
         temperature: float | None = None, top_p: float | None = None,
         top_k: int | None = None, model: str | None = None,
         timeout_seconds: float = 300.0) -> dict:
    """调试推理（流式测 TTFT；分离 reasoning；返回 usage/tps）。messages=[{"role","content"}]。model 字段供 router/多模型端点路由。"""
    if not messages:
        raise ValueError("需要 messages 参数")
    base, p = _target(profile_id, port)
    if model is None and p is not None and p.host and p.model:
        model = p.model
    return llama_client.chat(base, messages, model=model, max_tokens=max_tokens,
                             temperature=temperature, top_p=top_p, top_k=top_k,
                             timeout=timeout_seconds)


@mcp.tool()
def complete(profile_id: str | None = None, port: int | None = None,
             prompt: str = "", n_predict: int = 256,
             extra_body: dict | None = None, timeout_seconds: float = 600.0) -> dict:
    """原生 /completion 直通（全部 llama.cpp 采样参数经 extra_body），返回 timings 与 MTP 验收遥测（draft_n_accepted）。仅 llama-server。"""
    if not prompt:
        raise ValueError("需要 prompt 参数")
    base, p = _target(profile_id, port)
    _need(p, "complete_native", None if isinstance(base, int) else port)
    return llama_client.complete(base, prompt, n_predict=n_predict,
                                 timeout=timeout_seconds, **(extra_body or {}))


# ---------- 13-16. inspect / bench / log / raw ----------

@mcp.tool()
def server_inspect(profile_id: str | None = None, port: int | None = None,
                   section: str = "props") -> dict:
    """查看实例的 health / props / slots / metrics（四选一）。metrics 含 VRAM（若构建提供）。仅 llama-server。"""
    base, p = _target(profile_id, port)
    _need(p, "props", None if isinstance(base, int) else port)
    section = section.lower()
    if section == "health":
        return llama_client.health(base)
    if section == "props":
        return llama_client._truncate(llama_client.props(base))
    if section == "slots":
        return llama_client._truncate(llama_client.slots(base))
    if section == "metrics":
        return llama_client.metrics_vram(base)
    raise ValueError("section 只支持 health/props/slots/metrics")


@mcp.tool()
def bench(profile_id: str | None = None, port: int | None = None,
          mode: str = "speed", runs: int = 3, gen_tokens: int = 256,
          target_tokens: int = 32768, temperature: float = 0.6) -> dict:
    """性能基准。mode: speed（解码 t/s + MTP 验收）/ ttft（首 token 延迟）/ prefill / longctx（灌 KV）。依赖原生 /completion timings，仅 llama-server。"""
    base, p = _target(profile_id, port)
    _need(p, "bench", None if isinstance(base, int) else port)
    return bench_mod.run(base, mode=mode, runs=runs, gen_tokens=gen_tokens,
                         target_tokens=target_tokens, temperature=temperature)


@mcp.tool()
def read_server_log(profile_id: str, tail: int = 200) -> dict:
    """尾读本 server 启动的实例日志（硬上限 200 行）。"""
    try:
        prof = find_profile(profile_id)
    except ProfileError:
        prof = None   # router-<port> 等非档位日志仍可读
    if prof is not None and prof.remote:
        raise UnsupportedFeature(f"profile {profile_id} 指向远程 host，本机没有它的日志")
    tail = min(int(tail), 200)
    path = process_mgr.log_path_for(profile_id)
    return {"profile": profile_id, "log": path, "tail": _log_tail(path, tail)}


@mcp.tool()
def raw_request(profile_id: str | None = None, port: int | None = None,
                method: str = "GET", path: str = "/props",
                body: dict | None = None) -> str:
    """调试逃生门：向目标端点直发请求（返回截断 12000 字符）。"""
    if not path.startswith("/"):
        path = "/" + path
    base, _p = _target(profile_id, port)
    return llama_client._truncate(llama_client.request(base, method, path, body))


# ---------- 17. usage stats ----------

@mcp.tool()
def usage_stats(profile_id: str | None = None, port: int | None = None,
                recent_n: int = 20) -> dict:
    """本地模型真实 token 统计（仅存本地）：按模型聚合（请求数、prompt/completion/总 token、平均速度、累计耗时）+ 最近调用。给出 target 时附带 /metrics 服务端累计计数器。"""
    out: dict = {"models": stats.aggregate(), "recent": stats.recent(recent_n),
                 "privacy": "统计仅写入本机 stats 文件，无任何遥测"}
    if profile_id or port is not None:
        base, p = _target(profile_id, port)
        _need(p, "metrics", None if isinstance(base, int) else port)
        try:
            c = llama_client.live_counters(base)
            out["live_counters"] = {
                "prompt_tokens_total": c.get("llamacpp:prompt_tokens_total"),
                "predicted_tokens_total": c.get("llamacpp:tokens_predicted_total"),
                "cached_tokens_total": c.get("llamacpp:prompt_tokens_cached_total"),
                "spec_draft_total": c.get("llamacpp:spec_decode_num_draft_tokens_total"),
                "spec_accepted_total": c.get("llamacpp:spec_decode_num_accepted_tokens_total"),
                "avg_prompt_tps": c.get("llamacpp:prompt_tokens_seconds"),
                "avg_decode_tps": c.get("llamacpp:predicted_tokens_seconds"),
            }
        except llama_client.LlamaHTTPError as e:
            out["live_counters_error"] = str(e)[:200]
    return out


# ---------- 18. lan discovery ----------

@mcp.tool()
def lan_discover(service_type: str = "_local-ai._tcp.local.", wait_seconds: float = 4.0,
                 register: bool = False, overwrite: bool = False) -> dict:
    """发现局域网中的本地模型服务（mDNS/DNS-SD，默认 _local-ai._tcp，兼容
    pub-local-ai-discovery-server 的 v/api/auth/base/models TXT 协议）。
    register=true 时探测端点并写入 profiles.json：/props 有响应的注册为远程
    llama-server 档（chat/complete/bench/metrics 可用，生命周期归远端），其余注册为
    openai-compatible 档（仅 chat/usage_stats）；同名档位需 overwrite=true 覆盖。"""
    services = discovery_mod.discover(service_type, wait_seconds)
    out: dict = {"service_type": service_type, "count": len(services), "services": services}
    if register:
        out["registered"] = (discovery_mod.register_profiles(services, overwrite=overwrite)
                             if services else [])
    return out


# ---------- 19. validation ----------

@mcp.tool()
def validate_profiles() -> dict:
    """校验配置：profiles.json 问题 + 可选 env-amd 适配器解析报告（孤立 flag/残缺行）+ 模型文件存在性 + 端口复用。"""
    issues: list[dict] = []
    profs, load_issues = load_profiles()
    issues += load_issues
    missing = []
    for p in profs:
        if p.provider != "llama-server" or p.remote:
            continue   # 远程档位的模型/可执行文件在别的机器上，不在本机检查
        for label, path in (("exe", p.exe), ("model", p.model),
                            ("draft", p.draft_model), ("mmproj", p.mmproj)):
            if path and not os.path.isfile(os.path.expanduser(path)):
                missing.append({"profile": p.id, "kind": label, "missing": path})
        for f in p.orphaned_flags:
            issues.append({"kind": "orphaned_flags", "line": p.line,
                           "detail": f"profile {p.id}: 孤立 flag 未生效: {f}"})
    by_port: dict[int, list[str]] = {}
    for p in profs:
        if p.port is not None and p.provider == "llama-server":
            by_port.setdefault(p.port, []).append(p.id)
    tiers = {p.id: p.tier or None for p in profs if p.tier}
    if not read_default_id() and profs:
        issues.append({"kind": "no_default",
                       "detail": '未设置 "default" 档位——未指定 profile_id 的调用将要求用户选择。'
                                 '建议在 profiles.json 顶层加 "default": "<档位id>"'})
    return {"profiles": len(profs), "tiers": tiers, "issues": issues,
            "missing_files": missing,
            "port_reuse": {str(k): v for k, v in by_port.items() if len(v) > 1}}


def main() -> None:
    cfg = get_config()
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[llama-mm] WARNING: host={cfg.host} 不是回环地址。本 server 无鉴权且具备"
              "进程控制等高权限能力，仅供受信任的本机客户端使用，不要暴露到网络。",
              file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
