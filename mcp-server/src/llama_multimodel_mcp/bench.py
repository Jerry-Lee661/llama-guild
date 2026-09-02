"""Benchmark modes for llama-server: speed / ttft / prefill / longctx.

Runs in-process (no script paths, no hardcoded ports).
"""

from __future__ import annotations

import time

from . import llama_client

_FILLER = (
    "以下是系统设计与实现说明。模块之间通过显式接口通信，依赖方向固定为单向；"
    "每个组件负责单一职责，错误沿调用链向上传播并在边界处记录。"
    "配置项集中管理，路径与端口在启动时注入，运行期不重新解析。"
    "日志分级别输出，关键字段包含请求标识与耗时统计。"
)


def _filler_prompt(target_tokens: int) -> str:
    # Chinese text ≈ 0.6-0.8 token/char for Qwen tokenizers; overshoot then
    # correct once using the server-reported prompt_n.
    chars = int(target_tokens * 1.5)
    reps = max(1, chars // len(_FILLER) + 1)
    return (_FILLER * reps)[:chars]


def run(port: int, mode: str = "speed", runs: int = 3, gen_tokens: int = 256,
        target_tokens: int = 32768, temperature: float = 0.6,
        timeout: float = 600.0) -> dict:
    mode = mode.lower()
    if mode == "speed":
        return _speed(port, runs, gen_tokens, temperature, timeout)
    if mode == "ttft":
        return _ttft(port, runs, timeout)
    if mode == "prefill":
        return _prefill(port, target_tokens, timeout)
    if mode == "longctx":
        return _longctx(port, target_tokens, gen_tokens, temperature, timeout)
    raise ValueError(f"未知 bench 模式: {mode}（可用 speed/ttft/prefill/longctx）")


def _speed(port: int, runs: int, gen_tokens: int, temperature: float,
           timeout: float) -> dict:
    prompt = ("用 C++ 写一个 LRU 缓存类，包含 get/put，给出完整实现和简要注释。"
              "直接给代码。")
    results = []
    for i in range(runs):
        r = llama_client.complete(port, prompt, n_predict=gen_tokens,
                                  temperature=temperature, timeout=timeout)
        results.append({
            "run": i + 1,
            "decode_tps": r["decode_tps"],
            "predicted_n": r["predicted_n"],
            "prefill_tps": r["prefill_tps"],
            "draft": r.get("draft"),
            "total_ms": r["total_ms"],
        })
    tps_list = [x["decode_tps"] for x in results if x["decode_tps"]]
    accs = [x["draft"]["acceptance"] for x in results
            if x.get("draft") and x["draft"].get("acceptance")]
    return {
        "port": port, "mode": "speed", "runs": results,
        "decode_tps_mean": round(sum(tps_list) / len(tps_list), 1) if tps_list else None,
        "mtp_acceptance_mean": round(sum(accs) / len(accs), 3) if accs else None,
    }


def _ttft(port: int, runs: int, timeout: float) -> dict:
    prefix = _filler_prompt(1000)
    results = []
    for i in range(runs):
        r = llama_client.chat(port, [{"role": "system", "content": prefix},
                                     {"role": "user", "content": "请只回复：ok"}],
                              max_tokens=8, temperature=0.0, timeout=timeout)
        results.append({"run": i + 1, "ttft_ms": r["ttft_ms"],
                        "total_ms": r["total_ms"]})
    ttfts = [x["ttft_ms"] for x in results if x["ttft_ms"] is not None]
    return {"port": port, "mode": "ttft", "runs": results,
            "ttft_ms_mean": round(sum(ttfts) / len(ttfts)) if ttfts else None}


def _prefill(port: int, target_tokens: int, timeout: float) -> dict:
    r = llama_client.complete(port, _filler_prompt(target_tokens), n_predict=1,
                              timeout=timeout)
    return {"port": port, "mode": "prefill", "target_tokens": target_tokens,
            "prompt_n": r["prompt_n"], "prefill_tps": r["prefill_tps"]}


def _longctx(port: int, target_tokens: int, gen_tokens: int, temperature: float,
             timeout: float) -> dict:
    # One correction pass: measure actual prompt_n, rescale filler length.
    prompt = _filler_prompt(target_tokens)
    r = llama_client.complete(port, prompt, n_predict=gen_tokens,
                              temperature=temperature, timeout=timeout)
    actual = r.get("prompt_n") or 0
    if actual and abs(actual - target_tokens) / target_tokens > 0.15:
        scale = target_tokens / actual
        prompt = _filler_prompt(int(target_tokens * scale))
        r = llama_client.complete(port, prompt, n_predict=gen_tokens,
                                  temperature=temperature, timeout=timeout)
        actual = r.get("prompt_n")
    return {"port": port, "mode": "longctx", "target_tokens": target_tokens,
            "prompt_n": actual, "decode_tps": r["decode_tps"],
            "prefill_tps": r["prefill_tps"],
            "mtp_acceptance": (r.get("draft") or {}).get("acceptance"),
            "predicted_n": r["predicted_n"], "total_ms": r["total_ms"]}
