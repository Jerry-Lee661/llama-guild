# Synthetic launch-command library example for the optional env-amd adapter.
# Replace paths with your real model files. Format: PowerShell backtick
# continuations; the LAST line of each command has no backtick; '#' comment
# banners above each block become the profile description.

# ============================================================
# Example-9B-Q8 (~9GB) general chat/OCR fallback, port 8080
# ============================================================
llama-server.exe `
  -m "/models/example-9b-instruct-q8_0.gguf" `
  --host 127.0.0.1 --port 8080 `
  -c 65536 -np 1 --flash-attn on `
  --cache-type-k q8_0 --cache-type-v q8_0 `
  --n-predict 4096 `
  --spec-type draft-mtp,ngram-simple --spec-draft-n-max 4 `
  --temp 0.8 --top-p 0.9 --top-k 40 `
  -lv 3

# ---- Scenario: code / Agent (port 8081) ----
llama-server.exe `
  -m "/models/example-27b-coder-q4_k_s.gguf" `
  --host 127.0.0.1 --port 8081 `
  -c 65536 -np 1 -ngl 99 `
  --flash-attn on -b 2048 -ub 512 `
  --cache-type-k q4_0 --cache-type-v q4_0 `
  --n-predict 8192 `
  --spec-type draft-mtp --spec-draft-n-max 4 `
  --reasoning on --reasoning-format deepseek --reasoning-budget 8192 `
  --temp 0.6 --top-p 0.95 --top-k 20 `
  -lv 3

# ---- Scenario: creative writing (port 8081, pick one) ----
llama-server.exe `
  -m "/models/example-27b-coder-q4_k_s.gguf" `
  --host 127.0.0.1 --port 8081 `
  -c 32768 -np 1 -ngl 99 `
  --flash-attn on -ub 512 -b 2048 `
  --n-predict 8192 `
  --temp 1.0 --top-p 0.9 --top-k 40 --min-p 0.05 `
  --repeat-penalty 1.08 --repeat-last-n 128 `
  -lv 3
