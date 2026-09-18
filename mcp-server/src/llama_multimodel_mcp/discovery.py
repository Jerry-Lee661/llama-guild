"""LAN service discovery for _local-ai._tcp (mDNS / DNS-SD).

Wire protocol aligns with LYiHub/pub-local-ai-discovery-server: TXT keys
v / api / auth / base / models. Registration probes the endpoint and writes a
local profile: llama-server answers /props -> remote llama-server profile
(chat/complete/bench available, lifecycle refused); anything else ->
openai-compatible (chat/usage_stats only).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from . import profiles as profiles_mod

DEFAULT_SERVICE_TYPE = "_local-ai._tcp.local."
DEFAULT_WAIT_SECONDS = 4.0


class DiscoveryError(RuntimeError):
    pass


def discover(service_type: str = DEFAULT_SERVICE_TYPE,
             wait_seconds: float = DEFAULT_WAIT_SECONDS) -> list[dict]:
    """Browse an mDNS service type and return resolved endpoints."""
    try:
        from zeroconf import IPVersion, ServiceBrowser, Zeroconf
    except ImportError as e:  # pragma: no cover - depends on env
        raise DiscoveryError(
            "缺少 zeroconf 依赖: pip install zeroconf（或重装本包）") from e

    if not service_type.endswith(".local."):
        service_type = service_type.rstrip(".") + ".local."

    found: dict[str, dict] = {}

    class _Listener:
        def _add(self, info) -> None:
            addrs = info.parsed_addresses(IPVersion.V4Only) or info.parsed_addresses()
            if not addrs or not info.port:
                return
            txt: dict[str, str] = {}
            for k, v in (info.properties or {}).items():
                k = k.decode(errors="replace") if isinstance(k, bytes) else str(k)
                v = (v.decode(errors="replace") if isinstance(v, bytes)
                     else ("" if v is None else str(v)))
                txt[k] = v
            name = info.name
            if name.endswith("." + info.type):
                name = name[: -len(info.type) - 1]
            base = txt.get("base") or "/v1"
            entry = {
                "name": name,
                "server": (info.server or "").rstrip("."),
                "address": addrs[0],
                "port": info.port,
                "auth": txt.get("auth") or "none",
                "txt": txt,
                "base_url": f"http://{addrs[0]}:{info.port}{base}",
                "models_url": f"http://{addrs[0]}:{info.port}{txt.get('models') or '/v1/models'}",
            }
            found[f"{name}@{addrs[0]}"] = entry

        def add_service(self, zc, type_, name) -> None:
            info = zc.get_service_info(type_, name, 2500)
            if info:
                self._add(info)

        def update_service(self, zc, type_, name) -> None:
            pass

        def remove_service(self, zc, type_, name) -> None:
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, service_type, _Listener())
        time.sleep(max(0.5, wait_seconds))
    finally:
        zc.close()
    return list(found.values())


def _profiles_file() -> Path:
    p = profiles_mod._default_profiles_path()
    if p is None:
        p = Path.home() / ".llama-mm" / "profiles.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{\n  \"profiles\": {}\n}\n", encoding="utf-8")
    return p


def _probe(origin: str, models_url: str, timeout: float = 4.0) -> dict:
    """best-effort endpoint probe -> {is_llama_server, model_id}.

    /props is a root-level llama-server endpoint, so it is probed against the
    origin (http://host:port), not against base_url which may carry a path."""
    out = {"is_llama_server": False, "model_id": ""}
    try:
        r = httpx.get(origin.rstrip("/") + "/props", timeout=timeout, trust_env=False)
        out["is_llama_server"] = r.status_code < 400
    except httpx.HTTPError:
        pass
    try:
        r = httpx.get(models_url, timeout=timeout, trust_env=False)
        if r.status_code < 400:
            payload = r.json()
            data = payload.get("data") or payload.get("models") or []
            if isinstance(data, list) and data:
                first = data[0]
                out["model_id"] = str(first.get("id") or first.get("model")
                                      or first.get("name") or "")
    except (httpx.HTTPError, ValueError):
        pass
    return out


def register_profiles(services: list[dict], overwrite: bool = False,
                      probe_timeout: float = 4.0) -> list[dict]:
    """Write discovered endpoints into profiles.json (best-effort probing)."""
    path = _profiles_file()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data.setdefault("profiles", {})
    results = []
    for svc in services:
        pid = re.sub(r"[^0-9A-Za-z_.-]+", "-", svc["name"]).strip("-") or "lan-ai"
        if pid in data["profiles"] and not overwrite:
            results.append({"profile": pid, "registered": False,
                            "note": "同名档位已存在（overwrite=true 覆盖）"})
            continue
        probe = (_probe(f"http://{svc['address']}:{svc['port']}",
                        svc["models_url"], probe_timeout)
                 if svc.get("auth") == "none" else {})
        if probe.get("is_llama_server"):
            entry = {"provider": "llama-server", "host": svc["address"],
                     "port": svc["port"], "tier": "",
                     "description": (f"LAN 发现(_local-ai._tcp, {svc['server']})，"
                                     "远程 llama-server：支持 chat/complete/bench/metrics，"
                                     "生命周期由远端管理")}
        else:
            entry = {"provider": "openai-compatible", "base_url": svc["base_url"],
                     "model_id": probe.get("model_id", ""), "tier": "",
                     "description": (f"LAN 发现(_local-ai._tcp, {svc['server']})，"
                                     "OpenAI 兼容端点：仅 chat/usage_stats")}
        if svc.get("auth") not in (None, "", "none"):
            entry["description"] += f"；auth={svc['auth']}（key 不会广播，需自行配置）"
        data["profiles"][pid] = entry
        results.append({"profile": pid, "registered": True,
                        "provider": entry["provider"],
                        "base_url": entry.get("base_url")
                        or f"http://{entry['host']}:{entry['port']}",
                        "probed_llama_server": probe.get("is_llama_server", False)})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return results
