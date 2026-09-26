"""Jev-style decision primitives over constrained decoding.

A typed atomic question ("which of these K options?") is answered with a
single grammar-constrained token; per-option probabilities come from
`completion_probabilities`; two passes with the option order swapped are
averaged to cancel position bias; confidence uses the Jev formula
c = (pmax - 1/K) / (1 - 1/K).

Primitives: choice (K-way), noul (yes/no), score (ordered K-way, same
mechanism). Runnable without MCP via the `llama-decide` console script.

Two render formats:
  plain   - question + "A. option" lines; works on any instruct model (GBNF path)
  sysone  - the System One contract the fine-tuned engine was trained on:
            system = JUDGE_SYSTEM, user = [QUESTION]/[OPTIONS]/[STATE]. This
            one must go through /v1/chat/completions (the chat template is part
            of the contract) and read logprobs at the answer position instead of
            a GBNF completion.

Policy (per profile, optional): probability rules, a min-confidence gate and a
fail_mode action, plus an append-only JSONL audit trail.

Known limits (from the Jev/OpenJEV evaluation): probabilities are uncalibrated
inheritances of the base model — use them for *ranking*, not as calibrated
certainty; the swap-average cancels order bias, not miscalibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from . import llama_client
from .profiles import find_profile

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_OPTIONS = len(LETTERS)
PRIMITIVES = ("choice", "noul", "score")
FORMATS = ("plain", "sysone")

# Must match training/common.py::JUDGE_SYSTEM — the engine is tuned on this exact text.
SYSONE_SYSTEM = (
    "You are a judgment engine. Read the question and the options, then "
    "decide which single option best matches the state. "
    "Answer with EXACTLY ONE letter and nothing else."
)
DEFAULT_AUDIT_DIR = Path.home() / ".llama-mm" / "audit"


def validate_options(options: list[str], primitive: str) -> None:
    if primitive not in PRIMITIVES:
        raise ValueError(f"未知 primitive '{primitive}'（可用: {', '.join(PRIMITIVES)}）")
    if primitive == "noul":
        if len(options) != 2:
            raise ValueError("noul 需要恰好两个选项（yes/no 语义）")
        return
    if not 2 <= len(options) <= MAX_OPTIONS:
        raise ValueError(f"选项数须在 2..{MAX_OPTIONS}（单 token 字母标签约束）")


def build_grammar(k: int) -> str:
    """GBNF constraining the answer to exactly one option letter."""
    return "root ::= " + " | ".join(f'"{LETTERS[i]}"' for i in range(k))


def build_prompt(question: str, options: list[str], system: str | None = None) -> str:
    lines = []
    if system:
        lines.append(system.rstrip())
    lines.append(question.rstrip())
    lines.append("")
    for i, opt in enumerate(options):
        lines.append(f"{LETTERS[i]}. {opt}")
    lines.append("")
    lines.append(f"Answer with exactly one letter (A-{LETTERS[len(options) - 1]}), "
                 "nothing else.")
    return "\n".join(lines)


def build_messages(question: str, options: list[str], state: str,
                   system: str | None = None) -> list[dict]:
    """Chat messages in the System One render contract (training/common.py).

    Order matters: [QUESTION] -> [OPTIONS] -> [STATE]; the state comes last.
    """
    lines = [f"{LETTERS[i]}. {opt}" for i, opt in enumerate(options)]
    user = (f"[QUESTION]\n{question}\n\n[OPTIONS]\n" + "\n".join(lines)
            + f"\n\n[STATE]\n{state}")
    return [{"role": "system", "content": system or SYSONE_SYSTEM},
            {"role": "user", "content": user}]


def option_name(option: str) -> str:
    """'deny: Destructive …' -> 'deny'; a bare option is its own name."""
    return option.split(":", 1)[0].strip() or option.strip()


def extract_option_probs(completion_probabilities: list[dict], k: int) -> dict[str, float]:
    """Pull option-letter probabilities from /completion `completion_probabilities`
    (first generated token) and renormalize over the K letters.

    Two server shapes are handled: this build returns
    {"token", "logprob", "top_logprobs": [{"token", "logprob"}]} (raw probs,
    pre-grammar) and older/OpenAI-style responses carry `probs`/`top_probs`
    with `prob` values. The grammar mask renormalizes over the allowed set, so
    renormalizing the raw letter probabilities over the K letters yields the
    constrained distribution (ratios are preserved by masking)."""
    if not completion_probabilities:
        raise ValueError("响应缺少 completion_probabilities（n_probs 未生效？）")
    first = completion_probabilities[0]
    entries = (first.get("probs") or first.get("top_probs")
               or first.get("top_logprobs") or [])
    import math
    raw: dict[str, float] = {}
    for entry in entries:
        tok = str(entry.get("token", "")).strip().upper()
        if len(tok) == 1 and tok in LETTERS[:k]:
            if "prob" in entry:
                p = float(entry.get("prob") or 0.0)
            else:
                p = math.exp(float(entry.get("logprob", -99.0)))
            if p > raw.get(tok, -1.0):
                raw[tok] = p
    missing = [LETTERS[i] for i in range(k) if LETTERS[i] not in raw]
    if missing:
        raise ValueError(
            f"选项字母 {missing} 不在 top-n 概率内——提高 n_probs（当前覆盖 "
            f"{len(entries)} 个 token）后重试")
    total = sum(raw.values()) or 1.0
    return {letter: p / total for letter, p in raw.items()}


def average_swaps(pass1: dict[str, float], pass2: dict[str, float], k: int) -> dict[str, float]:
    """Average the two passes per ORIGINAL option index.

    pass1: letter i == original option i.
    pass2: options were displayed reversed, so displayed position j (letter j)
    holds original option k-1-j."""
    out: dict[str, float] = {}
    for i in range(k):
        letter = LETTERS[i]
        p1 = pass1.get(letter)
        p2 = pass2.get(LETTERS[k - 1 - i])
        vals = [v for v in (p1, p2) if v is not None]
        out[letter] = sum(vals) / len(vals) if vals else 0.0
    return out


def best_option(probs: dict[str, float], options: list[str]) -> str:
    """argmax letter -> option string (pure; ties break toward letter order)."""
    best = max(LETTERS[:len(options)], key=lambda l: probs.get(l, 0.0))
    return options[LETTERS.index(best)]


def confidence(pmax: float, k: int) -> float:
    """Jev confidence: rescales the argmax probability to [0,1] where 0 =
    uniform (1/K) and 1 = certain."""
    if k <= 1:
        return 1.0
    return max(0.0, min(1.0, (pmax - 1.0 / k) / (1.0 - 1.0 / k)))


_NEUTRAL_SAMPLING = {"temperature": 1.0, "top_k": 0, "top_p": 1.0, "repeat_penalty": 1.0}

# ---------- small TTL cache (the compaction path asks the same question repeatedly) ----------
_CACHE: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
_CACHE_MAX = 512
_CACHE_TTL = float(os.environ.get("LLAMA_MM_DECIDE_TTL", "300"))   # seconds; 0 disables


def cache_key(base, question: str, options: list[str], state: str | None, fmt: str,
              model: str | None, primitive: str) -> tuple:
    return (str(base), model or "", fmt, primitive, question,
            tuple(options), hashlib.sha256((state or "").encode("utf-8")).hexdigest())


def cache_get(key: tuple) -> dict | None:
    if _CACHE_TTL <= 0:
        return None
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    _CACHE.move_to_end(key)
    return value


def cache_put(key: tuple, value: dict) -> None:
    if _CACHE_TTL <= 0:
        return
    _CACHE[key] = (time.time(), value)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def cache_stats() -> dict:
    return {"entries": len(_CACHE), "ttl_s": _CACHE_TTL, "max_entries": _CACHE_MAX}


def extract_letter_probs_from_chat(resp: dict, k: int) -> tuple[dict[str, float], list[str]]:
    """Option-letter distribution from an OAI chat-completions response.

    Mirrors the reference readout (sehs4678-gp training/common.py::SysOneClient):
    take top_logprobs at the answer position, keep single-letter candidates within
    A..K, softmax over what is present. A letter missing from top_logprobs is
    reported instead of fatal — the caller can raise top_logprobs.
    """
    import math

    choices = resp.get("choices") or [{}]
    entries = ((choices[0].get("logprobs") or {}).get("content")) or []
    alts = entries[0].get("top_logprobs") if entries else []
    raw: dict[str, float] = {}
    for alt in alts or []:
        tok = str(alt.get("token", "")).strip().upper()
        if len(tok) == 1 and tok in LETTERS[:k] and tok not in raw:
            raw[tok] = float(alt.get("logprob", -99.0))
    missing = [LETTERS[i] for i in range(k) if LETTERS[i] not in raw]
    if not raw:
        raise ValueError("响应里没有任何候选字母 logprob（logprobs/top_logprobs 未生效？）")
    top = max(raw.values())
    exps = {l: math.exp(v - top) for l, v in raw.items()}
    total = sum(exps.values())
    return {l: p / total for l, p in exps.items()}, missing


def apply_policy(probs_by_name: dict[str, float], choice_name: str, conf: float,
                 policy: dict | None) -> dict:
    """Final action from an optional profile policy.

    rules are evaluated in order and match on the option NAME (text before ':');
    the first rule whose option reaches min_prob wins. Otherwise the argmax
    stands, unless confidence is below min_confidence — then fail_mode applies
    (the safe default when the reflex is not sure).
    """
    policy = policy or {}
    for rule in policy.get("rules") or []:
        name = str(rule.get("option", ""))
        if name in probs_by_name and probs_by_name[name] >= float(rule.get("min_prob", 0.0)):
            return {"action": rule.get("action") or name, "low_confidence": False,
                    "reason": f"rule: P({name})={probs_by_name[name]:.3f} "
                              f">= {float(rule.get('min_prob', 0.0)):g}"}
    min_conf = policy.get("min_confidence")
    if min_conf is not None and conf < float(min_conf):
        fail = policy.get("fail_mode") or choice_name
        return {"action": fail, "low_confidence": True,
                "reason": f"low_confidence: {conf:.3f} < {float(min_conf):g} -> {fail}"}
    return {"action": choice_name, "low_confidence": False, "reason": "argmax"}


def _audit(record: dict, policy: dict | None) -> str:
    """Append one decision to the JSONL audit trail; returns the audit id."""
    audit_id = uuid.uuid4().hex[:12]
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "audit_id": audit_id, **record}
    if (policy or {}).get("audit", True) is False:
        return audit_id
    directory = Path(os.environ.get("LLAMA_MM_AUDIT_DIR", str(DEFAULT_AUDIT_DIR)))
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"decide-{time.strftime('%Y%m%d')}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the audit trail must never break a decision
    return audit_id


def _one_pass(base, question: str, options: list[str], system: str | None,
              n_probs: int, timeout: float, model: str | None = None) -> dict[str, float]:
    k = len(options)
    extra = {"model": model} if model else {}
    last_err: Exception | None = None
    for np_ in (n_probs, 256):           # escalate once: letters can be buried
        resp = llama_client.complete(
            base, build_prompt(question, options, system), n_predict=1,
            timeout=timeout, grammar=build_grammar(k), n_probs=np_,
            cache_prompt=False, **_NEUTRAL_SAMPLING, **extra)
        try:
            return extract_option_probs(resp.get("completion_probabilities") or [], k)
        except ValueError as e:
            last_err = e
            if np_ >= 256:
                break
    raise last_err


def _one_pass_chat(base, question: str, options: list[str], state: str,
                   system: str | None, top_logprobs: int, timeout: float,
                   model: str | None = None) -> tuple[dict[str, float], list[str]]:
    """One sysone pass through /v1/chat/completions (chat template + logprobs)."""
    k = len(options)
    body: dict = {
        "messages": build_messages(question, options, state, system),
        "max_tokens": 1,
        "temperature": 0.0,
        "logprobs": True,
        "top_logprobs": max(int(top_logprobs), k * 4, 20),
    }
    if model:
        body["model"] = model
    resp = llama_client.request(base, "POST", "/v1/chat/completions", body,
                                timeout=timeout)
    probs, missing = extract_letter_probs_from_chat(resp, k)
    return probs, missing


def run_decide(base, question: str, options: list[str], primitive: str = "choice",
               system: str | None = None, n_probs: int | None = None,
               timeout: float = 120.0, model: str | None = None,
               state: str | None = None, fmt: str = "plain",
               policy: dict | None = None, profile_id: str | None = None,
               cache: bool = True) -> dict:
    if primitive == "noul" and len(options) == 2:
        pass
    validate_options(options, primitive)
    if fmt not in FORMATS:
        raise ValueError(f"未知 format '{fmt}'（可用: {', '.join(FORMATS)}）")
    if fmt == "sysone" and state is None:
        raise ValueError("format=sysone 需要 state（[STATE] 是训练契约的一部分）")
    key = cache_key(base, question, options, state, fmt, model, primitive)
    if cache:
        hit = cache_get(key)
        if hit is not None:
            out = dict(hit)
            out["cached"] = True
            out["latency_ms"] = 0
            out["audit_id"] = _audit({**out, "cached": True, "cache_of": hit.get("audit_id")},
                                     policy)
            return out
    k = len(options)
    n_probs = max(int(n_probs or 0), 20, k * 4)
    t0 = time.perf_counter()
    missing: list[str] = []
    degraded_reason: str | None = None
    if fmt == "sysone":
        pass1, missing = _one_pass_chat(base, question, options, state or "", system,
                                        n_probs, timeout, model)
        pass2 = None
        try:
            rev, _ = _one_pass_chat(base, question, list(reversed(options)), state or "",
                                    system, n_probs, timeout, model)
            pass2 = rev
        except (llama_client.LlamaHTTPError, ValueError) as e:
            degraded_reason = f"single_pass: 第二遍失败（{e}）"
    else:
        pass1 = _one_pass(base, question, options, system, n_probs, timeout, model)
        pass2 = None
        try:
            pass2 = _one_pass(base, question, list(reversed(options)), system, n_probs,
                              timeout, model)
        except (llama_client.LlamaHTTPError, ValueError) as e:
            degraded_reason = f"single_pass: 第二遍失败（{e}）"
    degraded = degraded_reason if pass2 is None else None
    avg = average_swaps(pass1, pass2, k) if pass2 else pass1
    best = max(avg, key=lambda l: avg[l])
    idx = LETTERS.index(best)
    p1_choice = best_option(pass1, options)
    probs_by_name = {option_name(options[LETTERS.index(l)]): round(p, 4)
                     for l, p in avg.items()}
    conf = confidence(avg[best], k)
    verdict = apply_policy(probs_by_name, option_name(options[idx]), conf, policy)
    out = {
        "choice": options[idx],
        "choice_name": option_name(options[idx]),
        "index": idx,
        "probabilities": probs_by_name,
        "confidence": round(conf, 4),
        "action": verdict["action"],
        "low_confidence": verdict["low_confidence"],
        "reason": verdict["reason"],
        "pass_choices": [p1_choice] + ([best_option(pass2, list(reversed(options)))]
                                       if pass2 else []),
        "swapped": pass2 is not None,
        "format": fmt,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }
    if missing:
        out["missing_letters"] = missing
        out["missing_note"] = "这些候选字母不在 top_logprobs 内（已按其余候选归一）"
    if pass2:
        # both passes are expressed in the original option space
        out["agree"] = p1_choice == out["choice"]
        if not out["agree"]:
            out["warning"] = "两遍顺序交换结果不一致——位置偏置未收敛，结果仅供参考"
    if degraded:
        out["degraded"] = degraded
    out["audit_id"] = _audit({
        "profile": profile_id, "format": fmt, "primitive": primitive,
        "question": question[:2000], "state_sha256": (
            hashlib.sha256((state or "").encode("utf-8")).hexdigest()[:16] if state else None),
        "state_chars": len(state or "") or None,
        "options": options, "probabilities": probs_by_name, "choice": out["choice"],
        "choice_name": out["choice_name"], "confidence": out["confidence"],
        "action": out["action"], "low_confidence": out["low_confidence"],
        "reason": out["reason"], "swapped": out["swapped"],
        "latency_ms": out["latency_ms"], "degraded": degraded,
    }, policy)
    cache_put(key, {k_: v for k_, v in out.items() if k_ not in ("audit_id", "latency_ms")})
    return out


def _criteria_map(options: list[str]) -> dict[str, str]:
    """'deny: Destructive …' -> {'deny': 'Destructive …'}; a bare option is name only."""
    out: dict[str, str] = {}
    for opt in options:
        name, _, desc = opt.partition(":")
        out[name.strip() or opt.strip()] = desc.strip()
    return out


def _normalize_answer(ans: dict, primitive: str) -> tuple[str | None, dict[str, float], float]:
    """(choice_name, probabilities_by_name, confidence) from one endpoint answer.

    Endpoint shapes (training/sysone_endpoint.py): choice -> {"choice", "probabilities",
    "confidence"}; noul -> {"noul": P(yes)} (confidence is the K=2 Jev formula
    |2p-1|); score -> {"score", "probabilities", "confidence"}."""
    if ans.get("type") == "noul" or "noul" in ans:
        p_yes = min(1.0, max(0.0, float(ans.get("noul") or 0.0)))
        return (("yes" if p_yes >= 0.5 else "no"),
                {"yes": round(p_yes, 4), "no": round(1.0 - p_yes, 4)},
                abs(2.0 * p_yes - 1.0))
    probs = {str(k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
    conf = float(ans.get("confidence") or 0.0)
    if ans.get("type") == "score":
        best = max(probs, key=lambda k: probs[k]) if probs else None
        return best, probs, conf
    return ans.get("choice"), probs, conf


def run_decide_batch(base, state: str, questions: list[dict], model: str | None = None,
                     timeout: float = 300.0, policy: dict | None = None,
                     profile_id: str | None = None) -> dict:
    """N questions over one shared state in a single /v1/systemone round trip.

    questions: [{"id"?: str, "question": str, "options": ["name: desc", ...],
                 "primitive"?: choice|noul|score}]

    Requires a System One schema endpoint (training/sysone_endpoint.py) — plain
    llama.cpp has no /v1/systemone. The endpoint does the two-pass swap-averaging
    server-side; per-question policy (rules / min_confidence / fail_mode) is
    applied here on the returned distributions. Each question consults the
    single-question TTL cache first (the compaction path repeats identical
    state+question pairs), so repeat rounds cost zero network requests.
    """
    if not state:
        raise ValueError("批量判定需要共享 state（[STATE] 是 sysone 契约的一部分）")
    if not questions:
        raise ValueError("questions 不能为空")
    ids: list[tuple[str, dict, list[str], str, tuple]] = []
    payload_questions: dict[str, dict] = {}
    for i, q in enumerate(questions):
        qid = str(q.get("id") or f"q{i + 1}")
        if qid in payload_questions:
            raise ValueError(f"重复的题目 id '{qid}'")
        opts = [str(o) for o in (q.get("options") or [])]
        primitive = str(q.get("primitive") or "choice")
        validate_options(opts, primitive)
        payload_questions[qid] = {
            "type": primitive,
            "instructions": str(q.get("question") or ""),
            "criteria": _criteria_map(opts),
        }
        key = cache_key(str(base), str(q.get("question") or ""), opts, state,
                        "sysone", model, primitive)
        ids.append((qid, q, opts, primitive, key))

    t0 = time.perf_counter()
    answers_out: dict[str, dict] = {}
    pending: list[tuple[str, dict, list[str], str, tuple]] = []
    for qid, q, opts, primitive, key in ids:
        hit = cache_get(key)
        if hit is not None:
            answers_out[qid] = {**hit, "cached": True}
        else:
            pending.append((qid, q, opts, primitive, key))
    batch_id = uuid.uuid4().hex[:12]
    usage: dict = {}
    labels_verified = None
    if pending:
        body = {"state": state,
                "questions": {qid: payload_questions[qid] for qid, *_ in pending}}
        if model:
            body["model"] = model
        resp = llama_client.request(base, "POST", "/v1/systemone", body, timeout=timeout)
        answers_in = resp.get("answers") or {}
        usage = resp.get("usage") or {}
        labels_verified = resp.get("labels_verified")
        for qid, q, opts, primitive, key in pending:
            try:
                raw = answers_in.get(qid)
                if raw is None:
                    raise ValueError("endpoint 未返回该题的答案")
                if raw.get("error"):
                    raise ValueError(str(raw["error"]))
                choice_name, probs, conf = _normalize_answer(raw, primitive)
                verdict = apply_policy(probs, choice_name or "", conf, policy)
                entry: dict = {
                    "primitive": primitive,
                    "probabilities": {k: round(v, 4) for k, v in probs.items()},
                    "confidence": round(conf, 4),
                    "action": verdict["action"],
                    "low_confidence": verdict["low_confidence"],
                    "reason": verdict["reason"],
                    "choice_name": choice_name,
                }
                if primitive == "choice":
                    entry["choice"] = next((o for o in opts if option_name(o) == choice_name),
                                           choice_name)
                elif primitive == "score":
                    entry["score"] = raw.get("score")
                _audit({"batch_id": batch_id, "qid": qid, "profile": profile_id,
                        "format": "sysone", "primitive": primitive,
                        "question": str(q.get("question") or "")[:2000],
                        "state_sha256": hashlib.sha256(state.encode("utf-8")).hexdigest()[:16],
                        "state_chars": len(state), "options": opts, **entry}, policy)
                cache_put(key, {k_: v for k_, v in entry.items()})
                answers_out[qid] = entry
            except (ValueError, llama_client.LlamaHTTPError) as e:
                fail = (policy or {}).get("fail_mode")
                answers_out[qid] = {"error": str(e)[:200], **(
                    {"action": fail, "low_confidence": True} if fail else {})}
    return {
        "batch_id": batch_id, "n_questions": len(ids),
        "answers": {qid: answers_out.get(qid) or out_answers.get(qid) for qid, *_ in ids},
        "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "cached_tokens")},
        "labels_verified": labels_verified,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="llama-decide",
        description="Jev-style decision readout against a local model profile "
                    "(grammar-constrained single token + swap-averaged probabilities). "
                    "Hooks (which cannot call MCP) drive this CLI; --stdin takes "
                    "{question, options, state?, format?, profile_id?} as JSON.")
    tgt = ap.add_mutually_exclusive_group()
    tgt.add_argument("--profile-id", help="profile id from profiles.json")
    tgt.add_argument("--port", type=int, help="local port (127.0.0.1:PORT)")
    tgt.add_argument("--url", help="full base URL, e.g. http://192.168.2.104:8280")
    ap.add_argument("--stdin", action="store_true",
                    help="read the request as JSON on stdin (long states, hook use)")
    ap.add_argument("--question")
    ap.add_argument("--options", nargs="+")
    ap.add_argument("--state", help="the [STATE] block (required for --format sysone)")
    ap.add_argument("--format", default=None, choices=FORMATS)
    ap.add_argument("--primitive", default="choice", choices=PRIMITIVES)
    ap.add_argument("--system")
    ap.add_argument("--n-probs", type=int, default=None)
    ap.add_argument("--top-logprobs", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    req: dict = {}
    if args.stdin:
        try:
            req = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"stdin 不是合法 JSON: {e}"}, ensure_ascii=False))
            sys.exit(2)
    question = args.question or req.get("question")
    options = args.options or req.get("options")
    state = args.state if args.state is not None else req.get("state")
    fmt = args.format or req.get("format")
    profile_id = args.profile_id or req.get("profile_id")
    system = args.system or req.get("system")
    if not question or not options:
        print(json.dumps({"error": "需要 question 与 options（参数或 stdin JSON）"},
                         ensure_ascii=False))
        sys.exit(2)

    base: int | str
    model = None
    policy: dict | None = None
    if profile_id:
        p = find_profile(profile_id)
        base = p.base_url or p.port
        if base is None:
            print(json.dumps({"error": f"profile {p.id} 缺少 port/base_url"}, ensure_ascii=False))
            sys.exit(2)
        if p.router and not p.model:
            print(json.dumps({"error": f"profile {p.id} 是 router 档且未指定 model；"
                                       "decide 需要明确 model（在 profile 增加 model 字段，"
                                       "或改用具体模型档位）"}, ensure_ascii=False))
            sys.exit(2)
        model = p.model or None
        policy = dict(p.decide or {})
        fmt = fmt or policy.get("format")
        system = system or policy.get("system")
    elif args.url:
        base = args.url.rstrip("/")
    else:
        base = args.port
    fmt = fmt or "plain"
    if args.no_audit:
        policy = {**(policy or {}), "audit": False}
    try:
        result = run_decide(base, question, options,
                            primitive=args.primitive, system=system,
                            n_probs=args.n_probs or args.top_logprobs, timeout=args.timeout,
                            model=model, state=state, fmt=fmt, policy=policy,
                            profile_id=profile_id)
    except (ValueError, llama_client.LlamaHTTPError) as e:
        # a hook needs a safe default, not a stack trace: fall back to fail_mode when set
        fail = (policy or {}).get("fail_mode")
        if fail:
            print(json.dumps({"error": str(e), "action": fail, "low_confidence": True,
                              "reason": f"unavailable -> fail_mode {fail}",
                              "degraded": "unavailable"}, ensure_ascii=False))
            sys.exit(0)
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def bench_rows(data: str, profile_id: str | None = None, port: int | None = None,
               url: str | None = None,
               limit: int = 0, family: str | None = None, distractor: bool = False,
               fmt: str | None = None, timeout: float = 120.0, quiet: bool = False) -> dict:
    """Accuracy + calibration of the reflex over a labeled JSONL (one decision per row).

    Row schema (the same one the training pipeline emits):
      {"family","state","instructions","criteria":[{"name","desc"}...],"answer_index"}
    Gold is criteria[answer_index]["name"]; the rendered options are "name: desc", so the
    reported choice_name is directly comparable.
    """
    base: int | str = (url.rstrip("/") if url else port)
    model = None
    policy: dict | None = None
    if profile_id:
        p = find_profile(profile_id)
        base = p.base_url or p.port
        if base is None:
            raise ValueError(f"profile {p.id} 缺少 port/base_url")
        model = p.model or None
        policy = dict(p.decide or {})
        fmt = fmt or policy.get("format")
    fmt = fmt or "plain"

    per_family: dict[str, dict] = {}
    bins = [[0, 0, 0] for _ in range(5)]        # [lower, n, correct] for 0.2-wide bins
    n = correct = low = cached_n = 0
    with open(data, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if family and rec.get("family") != family:
                continue
            if limit and n >= limit:
                break
            crit = list(rec["criteria"])
            if distractor:
                crit = crit + [{"name": "none_of_the_above", "desc": "None of the listed options apply"}]
            gold = rec["criteria"][rec["answer_index"]]["name"]
            options = [f"{c['name']}: {c['desc']}" if c.get("desc") else c["name"] for c in crit]
            try:
                out = run_decide(base, rec["instructions"], options, fmt=fmt,
                                 state=rec["state"], model=model, policy=policy,
                                 profile_id=profile_id, timeout=timeout)
            except (ValueError, llama_client.LlamaHTTPError) as e:
                out = {"choice_name": None, "confidence": 0.0, "error": str(e)[:200]}
            n += 1
            hit = out.get("choice_name") == gold
            correct += hit
            low += bool(out.get("low_confidence"))
            cached_n += bool(out.get("cached"))
            fam = per_family.setdefault(rec.get("family", "?"), {"n": 0, "correct": 0})
            fam["n"] += 1
            fam["correct"] += hit
            conf = float(out.get("confidence") or 0.0)
            b = min(4, int(conf * 5))
            bins[b][0] = b / 5
            bins[b][1] += 1
            bins[b][2] += hit
            if not quiet:
                mark = "ok " if hit else "ERR"
                print(f"  {mark} {rec.get('family','?'):16s} gold={gold:22s} "
                      f"got={str(out.get('choice_name')):22s} conf={conf:.3f}")
    acc = correct / n if n else 0.0
    # ECE over the populated bins
    ece = sum((nb / n) * abs(nc / nb - (lo + 0.1)) for lo, nb, nc in bins if nb) if n else 0.0
    return {
        "data": data, "profile": profile_id, "port": port, "url": url, "format": fmt,
        "distractor": distractor, "n": n, "accuracy": round(acc, 4),
        "low_confidence_rate": round(low / n, 4) if n else 0.0,
        "cached": cached_n, "ece": round(ece, 4),
        "bins": [{"confidence": f"{lo:.1f}-{lo + 0.2:.1f}", "n": nb,
                  "accuracy": round(nc / nb, 3) if nb else None} for lo, nb, nc in bins],
        "per_family": {k: {"n": v["n"], "accuracy": round(v["correct"] / v["n"], 4)}
                       for k, v in sorted(per_family.items())},
    }


def main_bench() -> None:
    ap = argparse.ArgumentParser(
        prog="llama-decide-bench",
        description="Reflex quality regression: run decide over a labeled JSONL and report "
                    "accuracy, per-family accuracy and confidence calibration (ECE).")
    ap.add_argument("--data", required=True, help="JSONL with family/state/instructions/criteria/answer_index")
    ap.add_argument("--profile-id")
    ap.add_argument("--port", type=int, help="local port (127.0.0.1:PORT)")
    ap.add_argument("--url", help="full base URL for a remote endpoint")
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows")
    ap.add_argument("--family", help="only this family")
    ap.add_argument("--distractor", action="store_true",
                    help="append an irrelevant option to every row (robustness check)")
    ap.add_argument("--format", default=None, choices=FORMATS)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--out", help="write the summary JSON here")
    args = ap.parse_args()
    try:
        summary = bench_rows(args.data, profile_id=args.profile_id, port=args.port,
                             url=args.url,
                             limit=args.limit, family=args.family,
                             distractor=args.distractor, fmt=args.format,
                             timeout=args.timeout, quiet=args.quiet)
    except (ValueError, llama_client.LlamaHTTPError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(f"\nn={summary['n']} accuracy={summary['accuracy']:.1%} ECE={summary['ece']:.4f} "
          f"low_conf={summary['low_confidence_rate']:.1%} cached={summary['cached']}")
    for fam, v in summary["per_family"].items():
        print(f"  {fam:18s} n={v['n']:4d} acc={v['accuracy']:.1%}")
    if args.out:
        Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"wrote {args.out}")


def main_batch() -> None:
    ap = argparse.ArgumentParser(
        prog="llama-decide-batch",
        description="Multi-question decide over one shared state: a single "
                    "/v1/systemone round trip against a System One schema endpoint "
                    "(training/sysone_endpoint.py). Stdin JSON: "
                    "{profile_id?|url?, state, questions: [{id?, question, options, "
                    "primitive?}]}")
    tgt = ap.add_mutually_exclusive_group()
    tgt.add_argument("--profile-id", help="profile id from profiles.json (decide policy applies)")
    tgt.add_argument("--port", type=int, help="local port (127.0.0.1:PORT)")
    tgt.add_argument("--url", help="full base URL, e.g. http://127.0.0.1:8301")
    ap.add_argument("--stdin", action="store_true",
                    help="read the request as JSON on stdin (recommended: hooks, compaction)")
    ap.add_argument("--state", help="the shared [STATE] block")
    ap.add_argument("--question", action="append", help="repeatable, aligned with --options")
    ap.add_argument("--options", action="append", nargs="+",
                    help="repeatable: one option list per --question")
    ap.add_argument("--primitive", action="append", choices=PRIMITIVES,
                    help="repeatable, aligned with --question (default choice)")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    req: dict = {}
    if args.stdin:
        try:
            req = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"stdin 不是合法 JSON: {e}"}, ensure_ascii=False))
            sys.exit(2)
    state = args.state if args.state is not None else req.get("state")
    raw_q = req.get("questions") or []
    if isinstance(raw_q, dict):
        # official /v1/systemone shape {id: {question, options, ...}} -> list
        questions = [{"id": k, **v} for k, v in raw_q.items()]
    else:
        questions = list(raw_q)
    if args.question:
        if args.options is None or len(args.options) != len(args.question):
            print(json.dumps({"error": "--options 与 --question 数量不一致"}, ensure_ascii=False))
            sys.exit(2)
        for i, qtext in enumerate(args.question):
            questions.append({"question": qtext, "options": args.options[i],
                              "primitive": (args.primitive[i] if args.primitive
                                            and i < len(args.primitive) else "choice")})
    profile_id = args.profile_id or req.get("profile_id")
    if not state or not questions:
        print(json.dumps({"error": "需要 state 与 questions（参数或 stdin JSON）"},
                         ensure_ascii=False))
        sys.exit(2)

    base: int | str
    model = None
    policy: dict | None = None
    if profile_id:
        p = find_profile(profile_id)
        base = p.base_url or p.port
        if base is None:
            print(json.dumps({"error": f"profile {p.id} 缺少 port/base_url"}, ensure_ascii=False))
            sys.exit(2)
        model = p.model or None
        policy = dict(p.decide or {})
    elif args.url:
        base = args.url.rstrip("/")
    else:
        base = args.port
    if args.no_audit:
        policy = {**(policy or {}), "audit": False}
    try:
        result = run_decide_batch(base, state, questions, model=model,
                                  timeout=args.timeout, policy=policy,
                                  profile_id=profile_id)
    except (ValueError, llama_client.LlamaHTTPError) as e:
        fail = (policy or {}).get("fail_mode")
        if fail:
            print(json.dumps({"error": str(e), "action": fail, "low_confidence": True,
                              "reason": f"unavailable -> fail_mode {fail}",
                              "degraded": "unavailable"}, ensure_ascii=False))
            sys.exit(0)
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
