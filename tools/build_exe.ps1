# 构建 crun.exe（onedir + 版本资源 + manifest + 图标，不压缩）
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#   参数: -Python <解释器路径> -Clean
param(
  [string]$Python = "C:\Users\senyu\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe",
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONPATH = Join-Path $Root ".pylibs"
$env:TMP  = Join-Path $Root ".tmp"
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null

$args = @("packaging\crun.spec", "--noconfirm", "--distpath", "dist\win", "--workpath", "build")
if ($Clean) { $args += "--clean" }

& $Python -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }

$exe = Join-Path $Root "dist\win\crun\crun.exe"
if (-not (Test-Path $exe)) { throw "未生成 $exe" }

# 自检：版本号 + 一次 dry-run 会话（不落盘业务数据）
& $exe version
Write-Host "`n构建完成: $exe"
Write-Host ("目录大小: {0:N1} MB" -f ((Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))
Write-Host "下一步: tools\sign.ps1 -Path `"$exe`"  （签名后再打包发布）"
