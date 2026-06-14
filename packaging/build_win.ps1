<#
  一键打包 VibeLight（Windows / PyInstaller onedir）。

  用法（在任意位置）：
    powershell -ExecutionPolicy Bypass -File packaging\build_win.ps1
    powershell -ExecutionPolicy Bypass -File packaging\build_win.ps1 -Clean   # 先清理 build/dist

  产物：dist\VibeLight\VibeLight.exe（连同 dist\VibeLight 整个文件夹一起分发）。
#>
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# 切到仓库根（本脚本在 packaging\ 下）
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
Write-Host "Repo root: $repo"

# 选择解释器：优先项目 venv
$py = if (Test-Path ".venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" }
      elseif (Test-Path "venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" }
      else { "python" }
Write-Host "Python: $py"

if ($Clean) {
    Write-Host "Cleaning build/ and dist/ ..."
    Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
}

Write-Host "Installing/updating packaging dependencies ..."
& $py -m pip install --upgrade pip
& $py -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
& $py -m pip install -r requirements.txt

Write-Host "Building VibeLight ..."
& $py -m PyInstaller "packaging\vibelight.spec" --noconfirm

$exe = Join-Path $repo "dist\VibeLight\VibeLight.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "Build succeeded: $exe" -ForegroundColor Green
    Write-Host "Smoke test (subcommand dispatch):" -ForegroundColor Green
    & $exe switch-agent status
    Write-Host ""
    Write-Host "Distribute the whole dist\VibeLight folder (onedir, includes runtime dependencies)."
} else {
    Write-Error "Artifact not found: $exe. Build may have failed; inspect the log above."
}
