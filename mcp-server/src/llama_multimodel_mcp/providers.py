"""Provider feature matrix.

'llama-server' exposes the full llama.cpp HTTP surface (lifecycle, native
/completion, router mode, metrics, MTP telemetry). Any other backend that
speaks the OpenAI API (LM Studio, Ollama /v1, vLLM, llama-swap, ...) is
'openai-compatible': inference + usage stats only. Unsupported features raise
UnsupportedFeature so the calling agent gets an explicit message instead of a
silent failure.
"""

from __future__ import annotations

FEATURES = {
    "llama-server": {
        "start", "stop", "switch", "complete_native", "bench", "router",
        "metrics", "props", "slots", "draft_telemetry", "log",
    },
    "openai-compatible": set(),  # inference + stats only; always available
}

_ALL = {"start", "stop", "switch", "complete_native", "bench", "router",
        "metrics", "props", "slots", "draft_telemetry", "log"}


class UnsupportedFeature(RuntimeError):
    pass


def supports(provider: str, feature: str) -> bool:
    if provider == "llama-server":
        return feature in _ALL
    return feature in FEATURES.get(provider, set())


def require(provider: str, feature: str) -> None:
    if not supports(provider, feature):
        raise UnsupportedFeature(
            f"profile provider '{provider}' 不支持 {feature} 功能。"
            f"该功能仅 llama-server 提供；openai-compatible 后端"
            f"（LM Studio/Ollama/vLLM/llama-swap）仅支持推理(chat)与统计(usage_stats)。"
        )
