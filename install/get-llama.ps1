# get-llama.ps1 - Download the latest official llama.cpp prebuilt binaries for
# Windows (from ggml-org/llama.cpp GitHub releases). Genericized for
# llama-multimodel-workflow; adapted from the author's personal updater.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File get-llama.ps1                        # vulkan → ~\.llama-mm\bin
#   powershell -ExecutionPolicy Bypass -File get-llama.ps1 -Backend cuda12.4
#   powershell -ExecutionPolicy Bypass -File get-llama.ps1 -Backend cpu -InstallDir D:\llm\bin
#
# After install, point config at it (~/.llama-mm/config.json):
#   { "server_exe": "<InstallDir>\current\llama-server.exe" }
# (config.server_exe / profiles exe accept absolute paths.)

param(
    [string]$Backend = 'vulkan',                # asset pattern part: vulkan | cpu | cuda12.4 | ...
    [string]$InstallDir = "$env:USERPROFILE\.llama-mm\bin"
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo      = 'ggml-org/llama.cpp'
$stateFile = Join-Path $InstallDir '.version'
$rollDir   = Join-Path $InstallDir 'current'
$assetRe   = "bin-win-$Backend-x64\.zip$"

Write-Host "[get-llama] 查询 $repo 最新带 $Backend 二进制的 release ..."

# vX.Y.Z stable releases carry no binaries; b[NUM] nightlies do — scan the list.
$releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases?per_page=20" -Headers @{ 'User-Agent' = 'llama-mm-getllama' }
$release = $releases | Where-Object {
    $_.tag_name -match '^b\d+$' -and ($_.assets | Where-Object { $_.name -match $assetRe })
} | Select-Object -First 1
if (-not $release) {
    Write-Host "[get-llama] 最近 20 个 release 中未找到匹配 $assetRe 的资产，退出"; exit 1
}
$tag = $release.tag_name
$ver = $tag -replace '^b', ''

$installed = if (Test-Path $stateFile) { (Get-Content $stateFile -Raw).Trim() } else { '' }
if ($installed -eq $ver -and (Test-Path (Join-Path $rollDir 'llama-server.exe'))) {
    Write-Host "[get-llama] 已是最新（$tag），跳过"; exit 0
}

$asset = $release.assets | Where-Object { $_.name -match $assetRe } | Select-Object -First 1
$zip = Join-Path $env:TEMP $asset.name
Write-Host "[get-llama] 下载 $($asset.name) ..."
if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    curl.exe -L -sS -o $zip $asset.browser_download_url
}
if (-not (Test-Path $zip) -or (Get-Item $zip).Length -eq 0) {
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
}

$verDir = Join-Path $InstallDir "b$ver"
New-Item -ItemType Directory -Force -Path $verDir | Out-Null
Write-Host "[get-llama] 解压到 $verDir ..."
Expand-Archive -Path $zip -DestinationPath $verDir -Force
Remove-Item $zip -Force -ErrorAction SilentlyContinue
if (-not (Test-Path (Join-Path $verDir 'llama-server.exe'))) {
    Write-Host "[get-llama] 解压后未找到 llama-server.exe，疑似 zip 结构变化，中止"; exit 1
}

if (Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue) {
    Write-Host "[get-llama] llama-server 正在运行，未同步 current 目录；停机后重跑即可同步"
} else {
    New-Item -ItemType Directory -Force -Path $rollDir | Out-Null
    Copy-Item (Join-Path $verDir '*') $rollDir -Recurse -Force
    Write-Host "[get-llama] 已同步到 $rollDir（current = $tag）"
}
Set-Content -Path $stateFile -Value $ver -Encoding ASCII
Write-Host "[get-llama] 完成: $tag。config.json 里把 server_exe 指向 $rollDir\llama-server.exe"
