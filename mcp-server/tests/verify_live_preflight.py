# -*- coding: utf-8 -*-
"""Live verification: context preflight dual-path against x99 tiel-q6.
Manual only — requires a reachable x99 router and wakes the model:
    LLAMA_MM_LIVE=1 python tests/verify_live_preflight.py
Skipped otherwise.
"""
import os
if os.environ.get("LLAMA_MM_LIVE") != "1":
    print("SKIP: set LLAMA_MM_LIVE=1 to run against the live x99 router")
    raise SystemExit(0)


Path 1 (over-limit): ~500K chars filler -> heuristic ~166K tokens > 131072
slot -> instant structured context_exceeded (heuristic leg, no slot entry).
Path 2 (normal): small request -> normal completion (model wakes from sleep).
"""
import json
import os
import subprocess
import sys
import time

REPO = r"D:\onedrive\project\vscode-copilot-local\llama-multimodel-workflow"
PY = os.path.join(REPO, ".venv-test", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = r"D:\project\llama-amd\.venv\Scripts\python.exe"

env = dict(os.environ, LLAMA_MM_PROFILES=os.path.join(os.environ["USERPROFILE"], ".llama-mm", "profiles.json"))
proc = subprocess.Popen([PY, "-m", "llama_multimodel_mcp.server"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                        cwd=REPO, env=env)

def send(o):
    proc.stdin.write(json.dumps(o) + "\n")
    proc.stdin.flush()

def call(req_id, name, args):
    send({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    t0 = time.time()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        resp = json.loads(line)
        if resp.get("id") == req_id:
            return resp, time.time() - t0

send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                 "clientInfo": {"name": "preflight-verify", "version": "0"}}})
proc.stdout.readline()
send({"jsonrpc": "2.0", "method": "notifications/initialized"})

filler = ("以下是用于上下文预检超限验证的填充材料，内容本身无意义。"
          "系统采用分层设计，模块之间通过显式接口通信，依赖方向固定为单向；"
          "每个组件负责单一职责，错误沿调用链向上传播并在边界处记录；"
          "配置集中管理，路径与端口启动时注入，运行期不重新解析。") * 6400  # ~499K chars

print(f"filler chars: {len(filler)}  (heuristic ~{len(filler)//3} tokens vs slot 131072)")

resp, elapsed = call(2, "chat", {
    "profile_id": "x99-tiel-q6",
    "model": "2x-tiel-q6-262k-n2",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": filler}],
})
body = resp["result"]
text = body["content"][0]["text"] if body.get("content") else ""
print(f"\n[超限路径] elapsed={elapsed:.2f}s isError={body.get('isError')}")
print("response:", text[:400])
ok1 = ("context_exceeded" in text and "slot_ctx" in text and "131072" in text)
print("结构化预检拒绝:", "PASS" if ok1 else "FAIL")

resp, elapsed = call(3, "chat", {
    "profile_id": "x99-tiel-q6",
    "model": "2x-tiel-q6-262k-n2",
    "max_tokens": 32,
    "messages": [{"role": "user", "content": "请只回复：ok"}],
})
body = resp["result"]
text = body["content"][0]["text"] if body.get("content") else ""
print(f"\n[正常路径] elapsed={elapsed:.2f}s isError={body.get('isError')}")
print("response:", text[:200])
ok2 = not body.get("isError") and "ok" in text.lower()
print("正常推理:", "PASS" if ok2 else "FAIL")

proc.kill()
print("\nVERIFICATION:", "PASS" if (ok1 and ok2) else "FAIL")
