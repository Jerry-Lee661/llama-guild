"""llama-server process discovery / start / stop via psutil (cross-platform)."""

from __future__ import annotations

import os
import re
import subprocess
import time

import psutil

from . import llama_client
from .config import get_config

# Processes this MCP server spawned in-process (profile_id -> psutil.Process).
_started: dict[str, psutil.Process] = {}

# profile ids end up in filesystem paths (log files); keep them strictly safe.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def safe_profile_id(profile_id: str) -> str:
    """Reject path separators / traversal before an id touches the filesystem."""
    if not _SAFE_ID.fullmatch(profile_id) or ".." in profile_id:
        raise ValueError(f"非法 profile_id（仅允许字母数字与 . _ -）: {profile_id!r}")
    return profile_id


def find_servers() -> list[dict]:
    out = []
    for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            name = (p.info["name"] or "").lower()
            if "llama-server" not in name.replace("_", "-") and "llama-server" not in name:
                if "llama-server" not in (p.info["exe"] or "").lower():
                    continue
            cmdline = p.info["cmdline"] or []
            model = port = None
            for j, a in enumerate(cmdline):
                if a == "-m" and j + 1 < len(cmdline):
                    model = cmdline[j + 1]
                if a == "--port" and j + 1 < len(cmdline):
                    port = int(cmdline[j + 1])
            out.append({
                "pid": p.info["pid"], "exe": p.info["exe"] or "",
                "model": model, "port": port,
                "started_at": time.strftime("%m-%d %H:%M", time.localtime(p.info["create_time"])),
                "source": next((k for k, v in _started.items() if v.pid == p.info["pid"]),
                               "external"),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def port_listener_pid(port: int) -> int | None:
    for c in psutil.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port and c.pid:
            return c.pid
    return None


def instance_device(inst: dict) -> str:
    """GPU pool of a running instance: the source profile's device field.
    Externally started instances land in the default pool."""
    if inst.get("source", "external") == "external":
        return "default"
    try:
        from .profiles import find_profile
        return find_profile(inst["source"]).device or "default"
    except Exception:
        return "default"


def vram_snapshot() -> dict:
    """Per-instance VRAM estimate + optional live sources (metrics gauges where
    the build provides them, rocm-smi when installed). Budgets from config,
    per GPU pool (device); pools without a budget use the global one."""
    cfg = get_config()
    weights: dict[str, float] = {}
    try:
        from . import profiles as profiles_mod
        for p in profiles_mod.load_profiles()[0]:
            w = p.vram_gb or p.weight_gb
            if w and p.model:
                weights[os.path.basename(p.model)] = w
    except Exception:
        pass

    def budget_for(dev: str) -> float:
        return cfg.vram_budget_by_device.get(dev, cfg.vram_budget_gb)

    per: dict[int, dict] = {}
    pool_used: dict[str, float] = {}
    total_est = 0.0
    for inst in find_servers():
        if inst["port"] is None:
            continue
        dev = instance_device(inst)
        entry: dict = {"device": dev}
        if inst["model"]:
            w = weights.get(os.path.basename(inst["model"]))
            if w:
                entry["estimated_gb"] = w
                total_est += w
                pool_used[dev] = pool_used.get(dev, 0.0) + w
        try:
            m = llama_client.metrics_vram(inst["port"])
            if "vram_used_gb" in m:
                entry["used_gb"] = m["vram_used_gb"]
                entry["source"] = "metrics"
        except llama_client.LlamaHTTPError:
            pass
        if not entry:
            entry["note"] = "无实时来源：按档位权重估算"
        per[inst["port"]] = entry
    rocm = cfg.rocm_smi_path
    if not per and rocm and os.path.isfile(rocm):
        try:
            out = subprocess.run([rocm, "--showmeminfo", "vram", "--json"],
                                 capture_output=True, text=True, timeout=10)
            import json
            data = json.loads(out.stdout)
            total_est = sum(int(v.get("Used", 0))
                            for v in next(iter(data.values())).values()) / 2**30
        except Exception:
            pass
    pools = sorted(set(pool_used) | set(cfg.vram_budget_by_device)) or ["default"]
    by_device = {d: {"used_estimated_gb": round(pool_used.get(d, 0.0), 2),
                     "budget_gb": budget_for(d)} for d in pools}
    return {"used_estimated_gb": round(total_est, 2),
            "budget_gb": cfg.vram_budget_gb, "per_port": per,
            "by_device": by_device}


def vram_conflicts(new_weight_gb: float | None, device: str = "default") -> list[str]:
    """Budget check scoped to one GPU pool; other pools are not counted."""
    snap = vram_snapshot()
    dev = device or "default"
    pool = snap.get("by_device", {}).get(dev, {})
    used = pool.get("used_estimated_gb", 0.0)
    budget = pool.get("budget_gb", get_config().vram_budget_by_device.get(
        dev, get_config().vram_budget_gb))
    projected = used + (new_weight_gb or 0)
    if projected <= budget:
        return []
    lines = [f"GPU 池 '{dev}' 已用(估) {round(used, 2)}GB + 新模型约 {new_weight_gb or '?'}GB "
             f"= {round(projected, 2)}GB > 预算 {budget}GB"]
    lines += [f"  端口 {p}: {e.get('used_gb') or e.get('estimated_gb') or '?'}GB"
              for p, e in snap["per_port"].items() if e.get("device") == dev]
    return lines


def start_profile(exe: str, args: list[str], profile_id: str,
                  extra_path: str | None = None) -> psutil.Process:
    profile_id = safe_profile_id(profile_id)
    cfg = get_config()
    log_dir = cfg.log_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    env = os.environ.copy()
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    kwargs: dict = {}
    if os.name == "nt":
        from subprocess import CREATE_NEW_PROCESS_GROUP, DETACHED_PROCESS
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    logf = open(os.path.join(log_dir, f"{profile_id}.log"), "ab")
    proc = subprocess.Popen([exe] + args, stdout=logf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env,
                            cwd=os.path.dirname(exe) or None, **kwargs)
    _started[profile_id] = psutil.Process(proc.pid)
    return _started[profile_id]


def stop_tree(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    try:
        children = proc.children(recursive=True)
        for c in children:
            c.kill()
        proc.kill()
        psutil.wait_procs(children + [proc], timeout=10)
        gone = not proc.is_running()
    except psutil.NoSuchProcess:
        gone = True
    for k in [k for k, v in _started.items() if v.pid == pid]:
        del _started[k]
    return gone


def stop_all() -> int:
    n = 0
    for inst in find_servers():
        if stop_tree(inst["pid"]):
            n += 1
    return n


def wait_health(port: int, timeout_s: float = 300.0) -> dict:
    t0 = time.time()
    last = {"status": "unknown"}
    while time.time() - t0 < timeout_s:
        last = llama_client.health(port, timeout=5.0)
        if last["status"] == "ok":
            return last
        time.sleep(2)
    return last


def log_path_for(profile_id: str) -> str:
    safe = safe_profile_id(profile_id)
    cfg = get_config()
    log_dir = os.path.abspath(cfg.log_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "logs"))
    path = os.path.abspath(os.path.join(log_dir, safe + ".log"))
    if os.path.commonpath([path, log_dir]) != log_dir:   # containment belt-and-braces
        raise ValueError(f"日志路径越界: {profile_id!r}")
    return path
