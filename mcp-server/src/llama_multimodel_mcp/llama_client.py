"""HTTP client for llama-server / OpenAI-compatible endpoints.

`base` accepts either an int port (-> http://127.0.0.1:<port>) or a full URL
(e.g. http://127.0.0.1:1234 for LM Studio). Native llama.cpp endpoints
(/completion, /props, /slots, /metrics, /models/load) are only meaningful for
provider 'llama-server'; the server layer gates them via providers.require().
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from . import preflight as preflight_mod
from . import stats
from .config import get_config

MAX_TOOL_CHARS = 12000


class LlamaHTTPError(RuntimeError):
    pass


def _base(base: int | str) -> str:
    if isinstance(base, int):
        return f"http://127.0.0.1:{base}"
    return base.rstrip("/") if "://" in str(base) else f"http://127.0.0.1:{base}"


def _truncate(obj: Any, limit: int = MAX_TOOL_CHARS) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)
    if len(s) > limit:
        s = s[:limit] + f"\n...[truncated {len(s) - limit} chars]"
    return s


def request(base: int | str, method: str, path: str, body: dict | None = None,
            timeout: float = 300.0) -> Any:
    url = _base(base) + (path if path.startswith("/") else "/" + path)
    try:
        r = httpx.request(method.upper(), url, json=body, timeout=timeout)
    except httpx.HTTPError as e:
        raise LlamaHTTPError(f"{method} {url} 失败: {e}") from e
    if r.status_code >= 400:
        raise LlamaHTTPError(f"HTTP {r.status_code} {method} {path}: {r.text[:400]}")
    ct = r.headers.get("content-type", "")
    return r.json() if "json" in ct else r.text


# ---------- read endpoints (llama-server) ----------

def health(base: int | str, timeout: float = 5.0) -> dict:
    try:
        return {"status": "ok", "detail": request(base, "GET", "/health", timeout=timeout)}
    except LlamaHTTPError as e:
        msg = str(e)
        if "503" in msg:
            return {"status": "loading", "detail": msg}
        return {"status": "down", "detail": msg[:200]}


def props(base: int | str) -> Any:
    return request(base, "GET", "/props")


def slots(base: int | str) -> Any:
    return request(base, "GET", "/slots")


def metrics_vram(base: int | str) -> dict:
    text = request(base, "GET", "/metrics")
    used = total = None
    for line in text.splitlines():
        if line.startswith("llamacpp:vram_used"):
            used = float(line.split()[1])
        elif line.startswith("llamacpp:vram_total"):
            total = float(line.split()[1])
    out: dict[str, Any] = {"base": str(base)}
    if used is not None:
        out["vram_used_gb"] = round(used / 2**30, 2)
    if total is not None:
        out["vram_total_gb"] = round(total / 2**30, 2)
    if used is None:
        out["raw_metrics"] = _truncate(text, 2000)
    return out


# ---------- inference (both providers) ----------

_ctx_cache: dict[str, tuple[float, dict | None]] = {}
_CTX_TTL = 60.0


def slot_capacity(base: int | str, model: str | None = None,
                  use_cache: bool = True) -> dict | None:
    """Per-slot context capacity for the target endpoint. None = unknown
    (probe failed → preflight fails open). Cached ~60s per (base, model)."""
    key = f"{_base(base)}::{model or ''}"
    now = time.time()
    hit = _ctx_cache.get(key)
    if use_cache and hit and now - hit[0] < _CTX_TTL:
        return hit[1]
    cap = None
    try:
        props = request(base, "GET", "/props", timeout=10)
        if isinstance(props, dict):
            n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            if isinstance(n_ctx, int) and n_ctx > 0:
                cap = {"slot_ctx": n_ctx, "model": None, "exact": True}
        if cap is None:
            # props unusable (router: role="router", n_ctx=0) — fall back to /models
            cap = preflight_mod.models_capacity(_iter_models(router_models(base)), model)
    except LlamaHTTPError:
        cap = None
    _ctx_cache[key] = (now, cap)
    return cap


def preflight_gate(base: int | str, prompt_text: str, max_tokens: int,
                   model: str | None = None, capacity: dict | None = None,
                   enabled: bool | None = None) -> dict | None:
    """Context preflight. Returns the rejection dict ({"error": {...}}) when
    over budget, else None (allow). Fails open on probe failure."""
    if enabled is None:
        enabled = get_config().preflight
    if not enabled:
        return None
    if capacity is None:
        capacity = slot_capacity(base, model)
    if capacity is None:
        return None

    def count_exact(m: str | None) -> int:
        body: dict[str, Any] = {"content": prompt_text}
        if m:
            body["model"] = m
        resp = request(base, "POST", "/tokenize", body, timeout=15)
        return len(resp.get("tokens", []))

    return preflight_mod.gate(prompt_text, max_tokens, capacity, count_exact)


def _new_stream_state() -> dict:
    return {"content": [], "reasoning": [], "usage": None, "model_hint": None,
            "ttft_ms": None, "logprobs": []}


def _consume_chunk(state: dict, chunk: dict, t0: float) -> None:
    """Fold one SSE chunk into the accumulated state (pure; unit-tested)."""
    if state["model_hint"] is None and chunk.get("model"):
        state["model_hint"] = chunk["model"]
    if chunk.get("usage"):
        state["usage"] = chunk["usage"]
    for ch in chunk.get("choices", []):
        d = ch.get("delta", {}) or {}
        rc, c = d.get("reasoning_content"), d.get("content")
        if rc or c:
            if state["ttft_ms"] is None:
                state["ttft_ms"] = (time.perf_counter() - t0) * 1000
            if rc:
                state["reasoning"].append(rc)
            if c:
                state["content"].append(c)
        lp = ch.get("logprobs")
        if lp:  # OpenAI stream shape: {"content": [{token, logprob, top_logprobs}]}
            for entry in (lp.get("content") or []):
                state["logprobs"].append({
                    "token": entry.get("token"),
                    "logprob": entry.get("logprob"),
                    "top": [{"token": t.get("token"), "logprob": t.get("logprob")}
                            for t in (entry.get("top_logprobs") or [])],
                })


def chat(base: int | str, messages: list[dict], model: str | None = None,
         max_tokens: int = 256, temperature: float | None = None,
         top_p: float | None = None, top_k: int | None = None,
         timeout: float = 300.0, preflight: bool | None = None,
         preflight_capacity: dict | None = None,
         logprobs: bool | None = None, top_logprobs: int | None = None) -> dict:
    gate = preflight_gate(base, " ".join(str(m.get("content", "")) for m in messages),
                          max_tokens, model=model, enabled=preflight,
                          capacity=preflight_capacity)
    if gate:
        return gate
    body: dict[str, Any] = {
        "messages": messages, "max_tokens": max_tokens, "stream": True,
        "stream_options": {"include_usage": True},
    }
    if model:
        body["model"] = model
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if top_k is not None:
        body["top_k"] = top_k
    if logprobs or top_logprobs is not None:
        body["logprobs"] = True
        if top_logprobs is not None:
            body["top_logprobs"] = int(top_logprobs)

    state = _new_stream_state()
    t0 = time.perf_counter()
    with httpx.stream("POST", _base(base) + "/v1/chat/completions",
                      json=body, timeout=timeout) as r:
        if r.status_code >= 400:
            raise LlamaHTTPError(f"HTTP {r.status_code}: {r.read().decode(errors='replace')[:400]}")
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            _consume_chunk(state, chunk, t0)
    total_ms = (time.perf_counter() - t0) * 1000

    usage = state["usage"]
    out: dict[str, Any] = {"base": str(base),
                           "content": "".join(state["content"]),
                           "reasoning": "".join(state["reasoning"]) or None,
                           "ttft_ms": round(state["ttft_ms"]) if state["ttft_ms"] is not None else None,
                           "total_ms": round(total_ms)}
    if state["logprobs"]:
        out["logprobs"] = state["logprobs"]
    if usage:
        ct = usage.get("completion_tokens")
        if ct:
            out["tps"] = round(ct / (total_ms / 1000), 1)
        out["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": ct,
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        }
        record_usage(base, out, usage,
                     resp_model=(usage.get("model") or state["model_hint"] or None), source="chat")
    if out["content"] == "" and out["reasoning"] is None:
        out["note"] = "无输出（可能 reasoning 预算耗尽或被截断）"
    return out


def complete(base: int | str, prompt: str, n_predict: int = 256,
             timeout: float = 600.0, preflight: bool | None = None,
             **sampling: Any) -> dict:
    """Native llama.cpp /completion with sampling passthrough + timings/draft
    telemetry. llama-server only (gate via providers.require at tool layer)."""
    gate = preflight_gate(base, prompt, n_predict, model=sampling.get("model"),
                          enabled=preflight)
    if gate:
        return gate
    body: dict[str, Any] = {"prompt": prompt, "n_predict": n_predict,
                            "cache_prompt": True}
    body.update(sampling)
    t0 = time.perf_counter()
    resp = request(base, "POST", "/completion", body, timeout=timeout)
    total_ms = (time.perf_counter() - t0) * 1000
    timings = resp.get("timings", {}) or {}
    out: dict[str, Any] = {
        "base": str(base), "content": resp.get("content", ""),
        "total_ms": round(total_ms),
        "prompt_n": timings.get("prompt_n"),
        "predicted_n": timings.get("predicted_n"),
        "prefill_tps": round(timings["prompt_per_second"], 1) if timings.get("prompt_per_second") else None,
        "decode_tps": round(timings["predicted_per_second"], 1) if timings.get("predicted_per_second") else None,
    }
    if timings.get("draft_n"):
        dn, da = timings["draft_n"], timings.get("draft_n_accepted", 0)
        out["draft"] = {"draft_n": dn, "draft_n_accepted": da,
                        "acceptance": round(da / dn, 3) if dn else None}
    if resp.get("tokens_cached") is not None:
        out["tokens_cached"] = resp["tokens_cached"]
    if resp.get("completion_probabilities"):
        out["completion_probabilities"] = resp["completion_probabilities"]
    out["stopped"] = [s for s in (resp.get("stop_reason"), resp.get("stopped_word")) if s]
    usage = {"prompt_tokens": timings.get("prompt_n"),
             "completion_tokens": timings.get("predicted_n")}
    record_usage(base, out, usage, resp_model=resp.get("model"), source="completion")
    return out


def record_usage(base: int | str, out: dict, usage: dict, resp_model: str | None,
                 source: str) -> None:
    if not get_config().stats_enabled:
        return
    try:
        model = resp_model
        if not model:
            try:
                model = props(base).get("model_path")
            except Exception:
                model = None   # openai-compatible 端点没有 /props，落到 endpoint 名
        tps = out.get("decode_tps") or out.get("tps")
        stats.record(model or f"endpoint-{base}", usage.get("prompt_tokens"),
                     usage.get("completion_tokens"), out.get("total_ms", 0),
                     tps, source)
    except Exception:
        pass  # stats must never break inference


# ---------- router mode (llama-server) ----------

def router_models(base: int | str) -> Any:
    try:
        return request(base, "GET", "/models")
    except LlamaHTTPError as e:
        if "404" in str(e):
            raise LlamaHTTPError(
                f"{base} 没有 /models 端点——该实例不是 router 模式"
                "（需以 --models-dir 启动）") from e
        raise


def _iter_models(models_resp: Any) -> list[dict]:
    if isinstance(models_resp, list):
        return models_resp
    for key in ("models", "data"):
        if isinstance(models_resp, dict) and isinstance(models_resp.get(key), list):
            return models_resp[key]
    return [models_resp] if isinstance(models_resp, dict) else []


def router_load(base: int | str, model: str, wait: bool = True,
                wait_seconds: float = 600.0) -> dict:
    request(base, "POST", "/models/load", {"model": model})
    if not wait:
        return {"base": str(base), "model": model, "state": "load_requested"}
    t0 = time.time()
    while time.time() - t0 < wait_seconds:
        for m in _iter_models(router_models(base)):
            if model in str(m.get("id", m.get("model", ""))):
                if str(m.get("state", "")).lower() == "loaded":
                    return {"base": str(base), "model": model, "state": "loaded",
                            "waited_s": round(time.time() - t0, 1)}
        time.sleep(2)
    return {"base": str(base), "model": model, "state": "timeout"}


def router_unload(base: int | str, model: str, wait: bool = True,
                  wait_seconds: float = 120.0) -> dict:
    request(base, "POST", "/models/unload", {"model": model})
    if not wait:
        return {"base": str(base), "model": model, "state": "unload_requested"}
    t0 = time.time()
    while time.time() - t0 < wait_seconds:
        states = {str(m.get("id", m.get("model", ""))): str(m.get("state", "")).lower()
                  for m in _iter_models(router_models(base))}
        match = next((s for name, s in states.items() if model in name), None)
        if match in ("unloaded", "not_loaded", ""):
            return {"base": str(base), "model": model, "state": "unloaded",
                    "waited_s": round(time.time() - t0, 1)}
        time.sleep(2)
    return {"base": str(base), "model": model, "state": "timeout"}


def live_counters(base: int | str) -> dict:
    text = request(base, "GET", "/metrics")
    counters: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("llamacpp:") and " " in line:
            name, _, val = line.partition(" ")
            try:
                counters[name] = float(val)
            except ValueError:
                continue
    return counters
