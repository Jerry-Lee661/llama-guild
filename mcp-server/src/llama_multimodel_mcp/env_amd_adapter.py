"""Optional adapter: parse a PowerShell launch-command library (".env-amd"
style) into profiles.

Many people keep a curated file of tuned llama-server launch commands with
backtick continuations and comment banners carrying measured performance data.
This adapter turns such a file into profiles so that prior tuning work is not
lost. Primary config stays profiles.json (see README for why).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .profiles import Profile


@dataclass
class AdapterIssue:
    kind: str          # orphaned_flags / malformed_line / missing_field
    line: int
    detail: str


@dataclass
class AdapterResult:
    profiles: list[Profile]
    issues: list[AdapterIssue]


_BOOL_FLAGS = {"--jinja", "--no-spec-draft-backend-sampling", "--no-mmap"}

_EXE_RE = re.compile(
    r"^(?:[A-Za-z]:[\\/])?(?:[\w.\-/\\ ]*[\\/])?llama-server(\.exe)?\s*(`)?\s*$")


def _tokens(line: str) -> list[str]:
    return [q if q else b for q, b in re.findall(r'"([^"]*)"|(\S+)', line)]


def _scenario(text: str | list[str]) -> str:
    if isinstance(text, list):
        text = " ".join(text)
    if re.search(r"代码|Agent|agent|code", text):
        return "code"
    if "写作" in text or "writing" in text.lower():
        return "writing"
    if re.search(r"识图|OCR|vision", text):
        return "vision"
    return "general"


def _base_id(model_path: str, aliases: dict) -> tuple[str, float | None]:
    name = os.path.basename(model_path)
    for token, meta in aliases.items():
        if token in name:
            if isinstance(meta, dict):
                return meta.get("id", token.lower()), meta.get("weight_gb")
            return str(meta), None
    m = re.search(r"([A-Za-z][\w.]*-\d+(?:\.\d+)?B)", name)
    return (m.group(1).lower().rstrip("b") + "b" if m
            else re.sub(r"\.gguf$", "", name).lower()), None


def _nearest_banner(lines: list[str], start_line: int) -> tuple[str, str] | None:
    texts: list[str] = []
    j = start_line - 2
    while j >= 0 and len(texts) < 40:
        s = lines[j].strip()
        if not s:
            j -= 1
            continue
        if not s.startswith("#"):
            break
        texts.append(s.lstrip("# ").strip())
        if set(s) <= {"#", "=", " "} and "=" in s and len(texts) > 1:
            title = next((t for t in reversed(texts[:-1]) if t), "")
            return (title, " ".join(reversed(texts[:-1])))
        j -= 1
    if texts:
        return (texts[-1], " ".join(reversed(texts)))
    return None


def parse_env_amd(path: str, aliases: dict | None = None) -> AdapterResult:
    aliases = aliases or {}
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    profiles: list[Profile] = []
    issues: list[AdapterIssue] = []
    comment_buf: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            comment_buf = []
            i += 1
            continue
        if stripped.startswith("#"):
            comment_buf.append(stripped)
            i += 1
            continue

        if _EXE_RE.match(stripped):
            single_line = not stripped.endswith("`")
            block_lines = [stripped]
            start_line = i + 1
            i += 1
            if not single_line:
                while i < n and lines[i].rstrip().endswith("`"):
                    block_lines.append(lines[i].strip())
                    i += 1
                if i < n:
                    nxt = lines[i].strip()
                    if nxt and not nxt.startswith("#"):
                        block_lines.append(nxt)
                        i += 1
            joined = " ".join(re.sub(r"`\s*$", "", ln).strip() for ln in block_lines)
            toks = _tokens(joined)
            exe, args = toks[0], toks[1:]

            flags: dict = {}
            model = port = ctx = None
            j = 0
            while j < len(args):
                t = args[j]
                if t.startswith("-") and not re.fullmatch(r"-?\d+(\.\d+)?", t):
                    if t in _BOOL_FLAGS or j + 1 >= len(args) or args[j + 1].startswith("-"):
                        flags[t] = None
                        j += 1
                    else:
                        flags[t] = args[j + 1]
                        j += 2
                else:
                    issues.append(AdapterIssue("malformed_line", start_line,
                                               f"裸 token 未挂到 flag: {t}"))
                    j += 1

            model = flags.get("-m")
            port = int(flags["--port"]) if "--port" in flags else None
            ctx = int(flags["-c"]) if "-c" in flags else None
            banner = _nearest_banner(lines, start_line)
            desc = " ".join(ln.lstrip("# ").strip() for ln in comment_buf)
            full_desc = ((banner[0] + " ") if banner else "") + desc
            scen = _scenario(comment_buf + ([banner[1]] if banner else [""]))
            removed = any(k in (banner[1] if banner else "") + desc
                          for k in ("已移除", "勿启动", "removed"))

            base, weight = _base_id(model or exe, aliases)
            pid0 = f"{base}-{scen}" if scen != "general" else base
            if "llama-hip" in exe.lower():
                pid0 += "-hip"
            candidates = [pid0]
            if ctx is not None and ctx >= 131072:
                candidates.append(pid0 + "-128k")
            pid = next((c for c in candidates
                        if not any(p.id == c for p in profiles)), None)
            if pid is None:
                k = 2
                while any(p.id == f"{pid0}-{k}" for p in profiles):
                    k += 1
                pid = f"{pid0}-{k}"

            orphaned: list[str] = []
            while i < n:
                nxt = lines[i].strip()
                if not nxt or nxt.startswith("#"):
                    break
                if nxt.startswith("-") or nxt.startswith("—"):
                    issues.append(AdapterIssue(
                        "orphaned_flags", i + 1,
                        f"profile {pid}: 上一行缺少续行反引号，以下 flag 被孤立未生效: {nxt}"))
                    orphaned.extend(_tokens(re.sub(r"`\s*$", "", nxt)))
                    i += 1
                    while i < n and lines[i].rstrip().endswith("`"):
                        orphaned.extend(_tokens(re.sub(r"`\s*$", "", lines[i].strip())))
                        i += 1
                    continue
                break

            profiles.append(Profile(
                id=pid, provider="llama-server", exe=exe,
                model=model or "", draft_model=flags.get("-md") or flags.get("--spec-draft-model"),
                mmproj=flags.get("--mmproj"), port=port, ctx=ctx, flags=flags,
                raw_args=args, description=full_desc[:600],
                line=start_line, removed=removed,
                needs_rocm_path="llama-hip" in exe.lower(),
                weight_gb=weight, orphaned_flags=orphaned,
            ))
            comment_buf = []
            continue

        issues.append(AdapterIssue("malformed_line", i + 1,
                                   f"疑似残缺命令行: {stripped[:120]}"))
        comment_buf = []
        i += 1

    for p in profiles:
        if not p.model:
            issues.append(AdapterIssue("missing_field", p.line,
                                       f"profile {p.id}: 缺少 -m 模型路径"))
        if p.port is None:
            issues.append(AdapterIssue("missing_field", p.line,
                                       f"profile {p.id}: 缺少 --port"))
    return AdapterResult(profiles=profiles, issues=issues)
