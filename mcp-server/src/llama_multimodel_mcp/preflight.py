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

    Returns {"slot_ctx": int, "model": id|None, "exact": bool} where exact
    means the value came from meta.n_ctx of a loaded model (or the targeted
    loaded model). `model` (a fragment is enough) selects a specific entry;
    unloaded selections are parsed from args (exact=False). No match / no
    usable numbers → None.
    """
    def norm(s):
        return str(s or "")

    def entry_id(m):
        return norm(m.get("id") or m.get("model"))

    def entry_state(m):
        st = m.get("status") or {}
        return str(st.get("value", st)).lower() if isinstance(st, dict) else str(st).lower()

    target = None
    loaded_caps: list[int] = []
    for m in models:
        mid = entry_id(m)
        meta = m.get("meta") or {}
        st = m.get("status") or {}
        args = st.get("args") if isinstance(st, dict) else None
        selected = bool(model) and (model in mid or mid in model)
        if entry_state(m) == "loaded":
            cap = meta.get("n_ctx") if isinstance(meta, dict) else None
            if isinstance(cap, int) and cap > 0:
                if selected:
                    return {"slot_ctx": cap, "model": mid, "exact": True}
                loaded_caps.append(cap)
        if selected and target is None:
            cap = parse_args_capacity(args or [])
            if cap:
                target = {"slot_ctx": cap, "model": mid, "exact": False}
    if target:
        return target
    if loaded_caps:
        # several loaded and no explicit model: the request lands on one of
        # them — be conservative with the smallest.
        return {"slot_ctx": min(loaded_caps), "model": None, "exact": True}
    caps = [c for c in (parse_args_capacity((m.get("status") or {}).get("args") or [])
                        for m in models) if c]
    if caps:
        return {"slot_ctx": min(caps), "model": None, "exact": False}
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
         count_exact, model: str | None = None) -> dict | None:
    """Full gate for one request. `capacity` is models_capacity()/props output
    or None (probe failed → allow, fail open). `count_exact(content, model)`
    counts tokens via /tokenize; any exception downgrades to the heuristic."""
    if capacity is None:
        return None
    cfg = get_config()
    slot = capacity["slot_ctx"]
    approx = heuristic_tokens(prompt_text)
    if approx + max_tokens > slot:  # absurd on its face — no network leg needed
        return decision(approx, max_tokens, slot, exact=False, model=capacity.get("model"))
    if not capacity.get("exact"):
        # unloaded router model: exact counting may trigger autoload — stand on the heuristic
        if approx + max_tokens > slot * 0.9:  # 10% headroom for estimate error
            return decision(approx, max_tokens, slot, exact=False, model=capacity.get("model"))
        return None
    try:
        exact_n = count_exact(model or capacity.get("model"))
    except Exception:
        if approx + max_tokens > slot:
            return decision(approx, max_tokens, slot, exact=False, model=capacity.get("model"))
        return None
    return decision(exact_n, max_tokens, slot, exact=True, model=capacity.get("model"))
