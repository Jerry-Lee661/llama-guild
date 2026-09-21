"""Unified profile model: JSON profiles (primary) or optional .env-amd adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import config as config_mod


@dataclass
class Profile:
    id: str
    provider: str = "llama-server"          # llama-server | openai-compatible
    tier: str = ""                          # quality | bulk | ""
    exe: str = "llama-server"               # llama-server only
    model: str = ""                         # gguf path, or model_id for openai-compatible
    draft_model: str | None = None
    mmproj: str | None = None
    port: int | None = None
    ctx: int | None = None
    base_url: str | None = None             # openai-compatible, or llama-server with host
    host: str | None = None                 # llama-server on another machine -> remote
    remote: bool = False                    # lifecycle tools refuse remote profiles
    device: str = "default"                 # GPU pool: gpu0 / gpu1 / default / ...
    flags: dict = field(default_factory=dict)
    raw_args: list[str] = field(default_factory=list)  # launch tokens after exe
    description: str = ""
    weight_gb: float | None = None
    vram_gb: float | None = None            # VRAM budget share; falls back to weight_gb
    removed: bool = False
    needs_rocm_path: bool = False
    orphaned_flags: list[str] = field(default_factory=list)
    line: int = 0


def _host_is_remote(url: str) -> bool:
    authority = url.split("://", 1)[-1].split("/", 1)[0]
    host = authority.rsplit(":", 1)[0].strip("[]")
    return not (host == "localhost" or host == "::1" or host.startswith("127."))


def _from_json(pid: str, d: dict) -> Profile:
    provider = d.get("provider", "llama-server")
    args = d.get("args", {}) or {}
    if isinstance(args, list):                       # verbatim token list
        flags, raw = {}, list(args)
        j = 0
        while j < len(raw):
            t = raw[j]
            if t.startswith("-") and j + 1 < len(raw) and not raw[j + 1].startswith("-"):
                flags[t] = raw[j + 1]
                j += 2
            else:
                flags[t] = None
                j += 1
    else:                                            # flag -> value (null = boolean)
        flags = dict(args)
        raw = []
        for k, v in flags.items():
            raw += [k] if v is None else [k, str(v)]
    port = d.get("port")
    base_url = d.get("base_url")
    # `remote_host` accepted as an alias: profiles written before the key was
    # standardized on `host` would otherwise silently point at localhost.
    host = d.get("host") or d.get("remote_host")
    if provider == "llama-server" and host:
        h = str(host).rstrip("/")
        if "://" not in h:
            h = "http://" + h
        authority = h.split("://", 1)[1].split("/", 1)[0]
        # only append the port when the host string has no explicit one —
        # "http://192.168.2.104:8080" must not become "...:8080:8080"
        base_url = h if ":" in authority else f"{h}:{port if port is not None else 8080}"
    remote = bool(provider == "llama-server" and base_url
                  and _host_is_remote(str(base_url)))
    if provider == "openai-compatible" and not base_url:
        base_url = f"http://127.0.0.1:{port or 8080}"
    if provider == "openai-compatible" and port is None and base_url:
        try:
            port = int(base_url.rstrip("/").rsplit(":", 1)[1])
        except (IndexError, ValueError):
            pass
    return Profile(
        id=pid, provider=provider, tier=d.get("tier", ""),
        exe=os.path.expandvars(os.path.expanduser(d.get("exe", "llama-server"))),
        model=os.path.expandvars(os.path.expanduser(d.get("model") or "")) if provider == "llama-server" else (d.get("model_id") or ""),
        draft_model=d.get("draft_model"), mmproj=d.get("mmproj"),
        port=port, ctx=d.get("ctx"), base_url=base_url,
        host=str(host) if host else None, remote=remote,
        device=d.get("device") or "default",
        flags=flags, raw_args=raw, description=d.get("description", ""),
        weight_gb=d.get("weight_gb"), vram_gb=d.get("vram_gb"),
        removed=bool(d.get("removed")),
    )


def _default_profiles_path() -> Path | None:
    cfg = config_mod.get_config()
    if cfg.profiles_file:
        p = Path(cfg.profiles_file)
        return p if p.is_file() else None
    p = Path.home() / ".llama-mm" / "profiles.json"
    return p if p.is_file() else None


class ProfileError(RuntimeError):
    pass


def load_profiles() -> tuple[list[Profile], list[dict]]:
    """Return (profiles, issues). JSON file is primary; env-amd adapter appends
    when config.env_amd_file is set and no JSON profile shares the id."""
    profiles: list[Profile] = []
    issues: list[dict] = []
    path = _default_profiles_path()
    if path:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProfileError(f"profiles 文件解析失败 {path}: {e}") from e
        for pid, d in (data.get("profiles") or {}).items():
            try:
                profiles.append(_from_json(pid, d or {}))
            except Exception as e:  # noqa: BLE001 - report, don't drop the rest
                issues.append({"kind": "bad_profile", "detail": f"{pid}: {e}"})
    cfg = config_mod.get_config()
    if cfg.env_amd_file:
        from . import env_amd_adapter as adapter
        res = adapter.parse_env_amd(cfg.env_amd_file, aliases=cfg.env_amd_aliases)
        known = {p.id for p in profiles}
        for p in res.profiles:
            if p.id not in known:
                profiles.append(p)
        issues += [{"kind": i.kind, "line": i.line, "detail": i.detail} for i in res.issues]
    return profiles, issues


def read_default_id(path: str | None = None) -> str | None:
    """Return the profiles.json "default" profile id, if set."""
    p = Path(path) if path else _default_profiles_path()
    if not p or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    v = d.get("default")
    return v if isinstance(v, str) else None


def find_profile(profile_id: str) -> Profile:
    profiles, _ = load_profiles()
    for p in profiles:
        if p.id == profile_id:
            return p
    ids = ", ".join(p.id for p in profiles) or "(无 — 先创建 ~/.llama-mm/profiles.json，参考 profiles.example.json)"
    raise ProfileError(f"找不到 profile '{profile_id}'。可用: {ids}")
