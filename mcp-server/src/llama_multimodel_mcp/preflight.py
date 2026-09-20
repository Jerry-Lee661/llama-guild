"""Context preflight: fast, machine-readable rejection before inference
requests enter the llama-server slot queue.

Two legs:
  1. heuristic — chars/chars_per_token estimate; blocks absurd requests with
     zero network cost (also the only leg for openai-compatible backends).
  2. exact — POST /tokenize (handled at the HTTP layer, never enters the slot
     queue). On a llama-router this REQUIRES a `model` field (400 otherwise,
     verified on x99 b1-8172e65); unloaded models are not exact-counted
     (tokenize may trigger autoload) — the heuristic result stands instead.

Capacity resolution:
  - normal instance: /props default_generation_settings.n_ctx == per-slot
    capacity (already divided by --parallel by the server);
  - router instance: /props reports role:"router", n_ctx:0 — unusable. Use
    GET /models instead: loaded models expose meta.n_ctx (verified equal to
    --ctx-size / --parallel on x99); unloaded models are parsed from
    status.args (--ctx-size // --parallel).

Rejection shape (returned as data, not raised — callers must be able to read
`retryable:false` instead of guessing whether to retry):
  {"error": {"type": "context_exceeded", "retryable": False,
             "prompt_tokens": N, "slot_ctx": N,
             "hint": "compact or start a new session"}}
"""

from __future__ import annotations

import time

from .config import get_config

_CTX_TTL = 60.0
_ctx_cache: dict[str, tuple[float, dict]] = {}


def heuristic_tokens(text: str, chars_per_token: float | None = None) -> int:
    cpt = chars_per_token if chars_per_token is not None else get_config().heuristic_chars_per_token
    return int(len(text) / max(cpt, 0.1))


def parse_args_capacity(args: list[str]) -> int | None:
    """--ctx-size // --parallel from a llama-server argv (parallel defaults to 1)."""
    def val(flag: str) -> int | None:
        try:
            i = args.index(flag)
            return int(args[i + 1])
        except (ValueError, IndexError, TypeError):
            return None
    ctx = val("--ctx-size") or val("-c")
    if ctx is None:
        return None
    parallel = val("--parallel") or 1
    return max(1, ctx // max(1, parallel))


def models_capacity(models: list[dict], model: str | None = None) -> dict | None:
    """Capacity from a GET /models payload (router form).

    Returns {"slot_ctx": int, "model": id|None, "loaded": bool}. Slot capacity
    is ALWAYS derived from launch args (--ctx-size // --parallel) — observed on
    x99 (2026-09-19): meta.n_ctx under parallel>1 may report the GGUF training
    ctx (262144) instead of the per-slot value (131072), so meta is only a
    fallback when args are missing. `model` (fragment match) selects an entry;
    `loaded` reports whether it is currently loaded (drives the /tokenize leg:
    tokenizing an unloaded model may trigger autoload). No usable numbers →
    None.
    """
    def norm(s):
        return str(s or "")

    def entry_id(m):
        return norm(m.get("id") or m.get("model"))

    def entry_state(m):
        st = m.get("status") or {}
        return str(st.get("value", st)).lower() if isinstance(st, dict) else str(st).lower()

    def cap_of(m) -> int | None:
        st = m.get("status") or {}
        cap = parse_args_capacity(st.get("args") or [])
        if cap:
            return cap
        meta = m.get("meta") or {}
        cap = meta.get("n_ctx") if isinstance(meta, dict) else None
        return cap if isinstance(cap, int) and cap > 0 else None

    target = None
    loaded_caps: list[int] = []
    for m in models:
        mid = entry_id(m)
        selected = bool(model) and (model in mid or mid in model)
        is_loaded = entry_state(m) == "loaded"
        cap = cap_of(m)
        if selected and cap:
            target = {"slot_ctx": cap, "model": mid, "loaded": is_loaded}
        if is_loaded and cap:
            loaded_caps.append(cap)
    if target:
        return target
    if loaded_caps:
        # several loaded and no explicit model: the request lands on one of
        # them — be conservative with the smallest.
        return {"slot_ctx": min(loaded_caps), "model": None, "loaded": True}
    caps = [c for c in (cap_of(m) for m in models) if c]
    if caps:
        return {"slot_ctx": min(caps), "model": None, "loaded": False}
    return None


def decision(prompt_tokens: int, max_tokens: int, slot_ctx: int,
             exact: bool = True, model: str | None = None) -> dict | None:
    """Return the rejection dict when over budget, else None."""
    if prompt_tokens + max_tokens <= slot_ctx:
        return None
    err = {"type": "context_exceeded", "retryable": False,
           "prompt_tokens": prompt_tokens, "max_tokens": max_tokens,
           "slot_ctx": slot_ctx,
           "hint": "compact or start a new session"}
    if not exact:
        err["capacity_estimated"] = True
    if model:
        err["model"] = model
    return {"error": err}


def gate(prompt_text: str, max_tokens: int, capacity: dict | None,
         count_exact) -> dict | None:
    """Full gate for one request. `capacity` is models_capacity()/props output
    or None (probe failed → allow, fail open). `count_exact(model)` counts
    tokens via /tokenize and is only attempted when capacity["loaded"] is true
    (tokenizing an unloaded router model may trigger autoload); any exception
    downgrades to the heuristic."""
    if capacity is None:
        return None
    slot = capacity["slot_ctx"]
    model = capacity.get("model")
    approx = heuristic_tokens(prompt_text)

    if not capacity.get("loaded"):
        # unloaded/sleeping router model: exact counting may trigger autoload —
        # stand on the heuristic with 10% headroom for estimate error
        if approx + max_tokens > slot:
            return decision(approx, max_tokens, slot, model=model)
        if approx + max_tokens > slot * 0.9:
            return decision(approx, max_tokens, slot, model=model)
        return None

    # loaded: /tokenize is safe and exact — prefer it, heuristic only as the
    # fallback when the endpoint misbehaves
    try:
        exact_n = count_exact(model)
    except Exception:
        if approx + max_tokens > slot:
            return decision(approx, max_tokens, slot, model=model)
        return None
    return decision(exact_n, max_tokens, slot, model=model)
