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
Write-Host "仓库根：$repo"

# 选择解释器：优先项目 venv
$py = if (Test-Path ".venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" }
      elseif (Test-Path "venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" }
      else { "python" }
Write-Host "使用解释器：$py"

if ($Clean) {
    Write-Host "清理 build/ 与 dist/ ..."
    Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
}

Write-Host "安装/更新打包依赖 ..."
& $py -m pip install --upgrade pip
& $py -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
& $py -m pip install -r requirements.txt

Write-Host "开始打包 ..."
& $py -m PyInstaller "packaging\vibelight.spec" --noconfirm

$exe = Join-Path $repo "dist\VibeLight\VibeLight.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "构建成功：$exe" -ForegroundColor Green
    Write-Host "冒烟测试（子命令分发）：" -ForegroundColor Green
    & $exe switch-agent status
    Write-Host ""
    Write-Host "分发：把整个 dist\VibeLight 文件夹拷给用户即可（onedir，含运行所需全部文件）。"
} else {
    Write-Error "未找到产物 $exe，构建可能失败，请查看上方日志。"
}
