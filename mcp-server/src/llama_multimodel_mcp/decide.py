"""Jev-style decision primitives over constrained decoding.

A typed atomic question ("which of these K options?") is answered with a
single grammar-constrained token; per-option probabilities come from
`completion_probabilities`; two passes with the option order swapped are
averaged to cancel position bias; confidence uses the Jev formula
c = (pmax - 1/K) / (1 - 1/K).

Primitives: choice (K-way), noul (yes/no), score (ordered K-way, same
mechanism). Runnable without MCP via the `llama-decide` console script.

Known limits (from the Jev/OpenJEV evaluation): probabilities are uncalibrated
inheritances of the base model — use them for *ranking*, not as calibrated
certainty; the swap-average cancels order bias, not miscalibration.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import llama_client
from .profiles import find_profile

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_OPTIONS = len(LETTERS)
PRIMITIVES = ("choice", "noul", "score")


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


def run_decide(base, question: str, options: list[str], primitive: str = "choice",
               system: str | None = None, n_probs: int | None = None,
               timeout: float = 120.0, model: str | None = None) -> dict:
    if primitive == "noul" and len(options) == 2:
        pass
    validate_options(options, primitive)
    k = len(options)
    n_probs = max(int(n_probs or 0), 20, k * 4)
    t0 = time.perf_counter()
    pass1 = _one_pass(base, question, options, system, n_probs, timeout, model)
    degraded = None
    try:
        pass2 = _one_pass(base, question, list(reversed(options)), system, n_probs,
                          timeout, model)
    except (llama_client.LlamaHTTPError, ValueError) as e:
        pass2 = None
        degraded = f"single_pass: 第二遍失败（{e}）"
    avg = average_swaps(pass1, pass2, k) if pass2 else pass1
    best = max(avg, key=lambda l: avg[l])
    idx = LETTERS.index(best)
    p1_choice = best_option(pass1, options)
    out = {
        "choice": options[idx],
        "index": idx,
        "probabilities": {options[LETTERS.index(l)]: round(p, 4) for l, p in avg.items()},
        "confidence": round(confidence(avg[best], k), 4),
        "pass_choices": [p1_choice] + ([best_option(pass2, list(reversed(options)))]
                                       if pass2 else []),
        "swapped": pass2 is not None,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }
    if pass2:
        # both passes are expressed in the original option space
        out["agree"] = p1_choice == out["choice"]
        if not out["agree"]:
            out["warning"] = "两遍顺序交换结果不一致——位置偏置未收敛，结果仅供参考"
    if degraded:
        out["degraded"] = degraded
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="llama-decide",
        description="Jev-style decision readout against a local model profile "
                    "(grammar-constrained single token + swap-averaged probabilities).")
    tgt = ap.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--profile-id", help="profile id from profiles.json")
    tgt.add_argument("--port", type=int, help="direct port (or full base URL ignored)")
    ap.add_argument("--question", required=True)
    ap.add_argument("--options", nargs="+", required=True)
    ap.add_argument("--primitive", default="choice", choices=PRIMITIVES)
    ap.add_argument("--system")
    ap.add_argument("--n-probs", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    base: int | str
    model = None
    if args.profile_id:
        p = find_profile(args.profile_id)
        base = p.base_url or p.port
        if base is None:
            print(json.dumps({"error": f"profile {p.id} 缺少 port/base_url"}, ensure_ascii=False))
            sys.exit(2)
        if p.host and not p.model:
            print(json.dumps({"error": f"profile {p.id} 是 router 档且未指定 model；"
                                       "decide 需要明确 model（在 profile 增加 model 字段，"
                                       "或改用具体模型档位）"}, ensure_ascii=False))
            sys.exit(2)
        model = p.model or None
    else:
        base = args.port
    try:
        result = run_decide(base, args.question, args.options,
                            primitive=args.primitive, system=args.system,
                            n_probs=args.n_probs, timeout=args.timeout, model=model)
    except (ValueError, llama_client.LlamaHTTPError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
