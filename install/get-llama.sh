#!/usr/bin/env bash
# get-llama.sh - Download the latest official llama.cpp prebuilt binaries
# (macOS arm64 / Ubuntu x64) from ggml-org/llama.cpp releases.
#
# Usage:
#   bash get-llama.sh                     # auto-detect os/arch → ~/.llama-mm/bin/current
#   bash get-llama.sh macos-arm64
#   bash get-llama.sh ubuntu-x64 ~/bin/llama
set -euo pipefail

REPO="ggml-org/llama.cpp"
TARGET="${1:-}"
INSTALL_DIR="${2:-$HOME/.llama-mm/bin}"

case "$TARGET" in
  macos-arm64) ASSET_RE='bin-macos-arm64\.zip$' ;;
  ubuntu-x64)  ASSET_RE='bin-ubuntu-x64\.zip$' ;;
  '')
    case "$(uname -s)/$(uname -m)" in
      Darwin/arm64)  ASSET_RE='bin-macos-arm64\.zip$' ;;
      Linux/x86_64)  ASSET_RE='bin-ubuntu-x64\.zip$' ;;
      *) echo "[get-llama] 未识别的平台 $(uname -s)/$(uname -m)；显式传 macos-arm64 或 ubuntu-x64"; exit 1 ;;
    esac ;;
  *) echo "[get-llama] 未知目标: $TARGET"; exit 1 ;;
esac

echo "[get-llama] 查询 $RE 最新带预编译二进制的 release ..."
# vX.Y.Z stable releases carry no binaries; b[NUM] nightlies do — scan the list.
TAG=""
ASSET_URL=""
for page in 1 2; do
  json=$(curl -sS -H 'User-Agent: llama-mm-getllama' "https://api.github.com/repos/$REPO/releases?per_page=20&page=$page")
  TAG=$(echo "$json" | python3 -c "
import json, sys, re
for rel in json.load(sys.stdin):
    if not re.match(r'^b\d+$', rel['tag_name']):
        continue
    for a in rel.get('assets', []):
        if re.search(r'$ASSET_RE', a['name']):
            print(rel['tag_name'] + ' ' + a['browser_download_url'])
            sys.exit(0)
" || true)
  if [ -n "$TAG" ]; then break; fi
done
if [ -z "$TAG" ]; then echo "[get-llama] 未找到匹配 $ASSET_RE 的资产"; exit 1; fi

VER="${TAG%% *}"
URL="${TAG#* }"
ROLL="$INSTALL_DIR/current"

if [ -f "$INSTALL_DIR/.version" ] && [ "$(cat "$INSTALL_DIR/.version")" = "$VER" ] \
   && [ -x "$ROLL/llama-server" ]; then
  echo "[get-llama] 已是最新（$TAG），跳过"; exit 0
fi

TMP=$(mktemp -d)
echo "[get-llama] 下载 $URL ..."
curl -L -sS -o "$TMP/llama.zip" "$URL"
mkdir -p "$INSTALL_DIR/b$VER"
unzip -oq "$TMP/llama.zip" -d "$INSTALL_DIR/b$VER"
rm -rf "$TMP"
if [ ! -f "$INSTALL_DIR/b$VER/llama-server" ]; then
  echo "[get-llama] 解压后未找到 llama-server，疑似 zip 结构变化，中止"; exit 1
fi
if pgrep -x llama-server >/dev/null 2>&1; then
  echo "[get-llama] llama-server 正在运行，未同步 current；停机后重跑即可同步"
else
  mkdir -p "$ROLL"
  cp -R "$INSTALL_DIR/b$VER/." "$ROLL/"
  echo "[get-llama] 已同步到 $ROLL（current = $VER）"
fi
echo "$VER" > "$INSTALL_DIR/.version"
echo "[get-llama] 完成: b$VER。config.json 里把 server_exe 指向 $ROLL/llama-server"
