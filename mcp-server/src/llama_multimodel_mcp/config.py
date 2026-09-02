"""Configuration loading for llama-multimodel-mcp.

Config file resolution order:
  1. $LLAMA_MM_CONFIG env var
  2. ~/.llama-mm/config.json
  3. config.json next to the package (mcp-server/config.json)
Missing file -> all defaults. Every value can be overridden by env vars
(LLAMA_MM_SERVER_EXE, LLAMA_MM_VRAM_BUDGET_GB, ...).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, current):
    v = os.environ.get(name)
    return v if v is not None else current


@dataclass
class Config:
    server_exe: str = "llama-server"
    host: str = "127.0.0.1"
    vram_budget_gb: float = 20.0
    stats_enabled: bool = True
    stats_path: str | None = None          # default: <pkg>/stats/usage.json
    log_dir: str | None = None             # default: <pkg>/logs
    profiles_file: str | None = None       # default: ~/.llama-mm/profiles.json
    env_amd_file: str | None = None        # optional .env-amd style adapter input
    env_amd_aliases: dict = field(default_factory=dict)   # optional id/weight aliases
    rocm_smi_path: str | None = None
    source: str = "defaults"


def _config_candidates() -> list[Path]:
    cands = []
    if os.environ.get("LLAMA_MM_CONFIG"):
        cands.append(Path(os.environ["LLAMA_MM_CONFIG"]))
    cands.append(Path.home() / ".llama-mm" / "config.json")
    cands.append(Path(__file__).resolve().parent.parent.parent / "config.json")
    return cands


def load_config() -> Config:
    cfg = Config()
    for cand in _config_candidates():
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8-sig"))
                cfg.source = str(cand)
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("server_exe", "host", "stats_path", "log_dir",
                        "profiles_file", "env_amd_file", "rocm_smi_path"):
                if isinstance(data.get(key), str):
                    setattr(cfg, key, os.path.expandvars(os.path.expanduser(data[key])))
            if isinstance(data.get("env_amd_aliases"), dict):
                cfg.env_amd_aliases = data["env_amd_aliases"]
            if isinstance(data.get("vram_budget_gb"), (int, float)):
                cfg.vram_budget_gb = float(data["vram_budget_gb"])
            if isinstance(data.get("stats_enabled"), bool):
                cfg.stats_enabled = data["stats_enabled"]
            break
    cfg.server_exe = _env("LLAMA_MM_SERVER_EXE", cfg.server_exe)
    cfg.host = _env("LLAMA_MM_HOST", cfg.host)
    if os.environ.get("LLAMA_MM_VRAM_BUDGET_GB"):
        cfg.vram_budget_gb = float(os.environ["LLAMA_MM_VRAM_BUDGET_GB"])
    if os.environ.get("LLAMA_MM_PROFILES"):
        cfg.profiles_file = os.environ["LLAMA_MM_PROFILES"]
    if os.environ.get("LLAMA_MM_ENV_AMD"):
        cfg.env_amd_file = os.environ["LLAMA_MM_ENV_AMD"]
    if os.environ.get("LLAMA_MM_STATS_PATH"):
        cfg.stats_path = os.environ["LLAMA_MM_STATS_PATH"]
    if os.environ.get("LLAMA_MM_LOG_DIR"):
        cfg.log_dir = os.environ["LLAMA_MM_LOG_DIR"]
    return cfg


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Test helper."""
    global _config
    _config = None
