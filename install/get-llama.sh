#!/usr/bin/env bash
# get-llama.sh - Download the latest official llama.cpp prebuilt binaries
# (macOS arm64 / Ubuntu x64) from ggml-org/llama.cpp releases.
#
# Usage:
#   bash get-llama.sh                     # auto-detect os/arch → ~/.llama-mm/bin/current
#   bash get-llama.sh macos-arm64
#   bash get-llama.sh ubuntu-x64 ~/bin/llama
set -euo pipefail

# SECURITY: downloads and runs prebuilt binaries from the official ggml-org/
# llama.cpp releases. Pin VERSION= and pass EXPECTED_SHA256 for a verifiable
# install; otherwise you trust the latest upstream release as-is.
REPO="ggml-org/llama.cpp"
TARGET="${1:-}"
INSTALL_DIR="${2:-$HOME/.llama-mm/bin}"
VERSION="${3:-}"
EXPECTED_SHA256="${4:-}"

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
    if VERSION and rel['tag_name'] != VERSION:
        continue
    for a in rel.get('assets', []):
        if re.search(r'$ASSET_RE', a['name']):
            print(rel['tag_name'] + ' ' + a['browser_download_url'])
            sys.exit(0)
" || true)
  if [ -n "$TAG" ]; then break; fi
done
if [ -z "$TAG" ]; then echo "[get-llama] 未找到匹配 $ASSET_RE 的资产"; exit 1; fi

VER="${TAG%% *}"; VER="${VER#b}"   # b4233 -> 4233（版本目录统一不带 b 前缀）
URL="${TAG#* }"
ROLL="$INSTALL_DIR/current"
VERDIR="$INSTALL_DIR/b$VER"
SYNC_MARK="$INSTALL_DIR/.current"

# .current 记录已同步进 current/ 的版本；只完成下载不算最新（可能因 server
# 运行中跳过了同步），否则"停机后重跑同步"永远不会发生。
if [ -f "$SYNC_MARK" ] && [ "$(cat "$SYNC_MARK")" = "$VER" ] \
   && [ -x "$ROLL/llama-server" ]; then
  echo "[get-llama] 已是最新（$TAG），跳过"; exit 0
fi

if [ ! -x "$VERDIR/llama-server" ]; then
  TMP=$(mktemp -d)
  echo "[get-llama] 下载 $URL ..."
  curl -L -sS -o "$TMP/llama.zip" "$URL"
  if [ -n "$EXPECTED_SHA256" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
      SHA=$(sha256sum "$TMP/llama.zip" | cut -d' ' -f1)
    else
      SHA=$(shasum -a 256 "$TMP/llama.zip" | cut -d' ' -f1)
    fi
    if [ "$SHA" != "$(echo "$EXPECTED_SHA256" | tr 'A-Z' 'a-z')" ]; then
      echo "[get-llama] SHA256 mismatch: $SHA"; exit 1
    fi
    echo "[get-llama] SHA256 verified"
  fi
  mkdir -p "$VERDIR"
  unzip -oq "$TMP/llama.zip" -d "$VERDIR"
  rm -rf "$TMP"
  if [ ! -f "$VERDIR/llama-server" ]; then
    echo "[get-llama] 解压后未找到 llama-server，疑似 zip 结构变化，中止"; exit 1
  fi
fi
echo "$VER" > "$INSTALL_DIR/.version"
if pgrep -x llama-server >/dev/null 2>&1; then
  echo "[get-llama] llama-server 正在运行，未同步 current；停机后重跑即可同步（不会重复下载）"
else
  mkdir -p "$ROLL"
  cp -R "$VERDIR/." "$ROLL/"
  echo "$VER" > "$SYNC_MARK"
  echo "[get-llama] 已同步到 $ROLL（current = $TAG）"
fi
echo "[get-llama] 完成: $TAG。config.json 里把 server_exe 指向 $ROLL/llama-server"
