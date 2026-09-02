"""Persistent per-model token usage stats (local-only, no telemetry)."""

from __future__ import annotations

import json
import os
import time

RECENT_LIMIT = 100


def _stats_path() -> str:
    from .config import get_config
    cfg = get_config()
    if cfg.stats_path:
        return cfg.stats_path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats", "usage.json")


def record(model: str, prompt_tokens: int | None, completion_tokens: int | None,
           total_ms: float, tps: float | None, source: str = "chat") -> None:
    try:
        data = _load()
        agg = data["models"].setdefault(model, {
            "requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_ms": 0, "tps_samples": 0, "tps_sum": 0.0, "last_used": None,
        })
        agg["requests"] += 1
        agg["prompt_tokens"] += prompt_tokens or 0
        agg["completion_tokens"] += completion_tokens or 0
        agg["total_ms"] += round(total_ms)
        if tps:
            agg["tps_samples"] += 1
            agg["tps_sum"] += tps
        agg["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
        recent = data.setdefault("recent", [])
        recent.append({"time": agg["last_used"], "model": os.path.basename(model),
                       "prompt_tokens": prompt_tokens,
                       "completion_tokens": completion_tokens,
                       "total_ms": round(total_ms), "tps": tps, "source": source})
        del recent[:-RECENT_LIMIT]
        _save(data)
    except OSError:
        pass


def aggregate() -> dict:
    out = {}
    for model, a in _load().get("models", {}).items():
        out[model] = {
            "requests": a["requests"],
            "prompt_tokens": a["prompt_tokens"],
            "completion_tokens": a["completion_tokens"],
            "total_tokens": a["prompt_tokens"] + a["completion_tokens"],
            "total_s": round(a["total_ms"] / 1000, 1),
            "avg_tps": round(a["tps_sum"] / a["tps_samples"], 1) if a["tps_samples"] else None,
            "last_used": a["last_used"],
        }
    return out


def recent(n: int = 20) -> list[dict]:
    return _load().get("recent", [])[-n:]


def reset() -> None:
    _save({"models": {}, "recent": []})


def _load() -> dict:
    try:
        with open(_stats_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"models": {}, "recent": []}


def _save(data: dict) -> None:
    path = _stats_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
