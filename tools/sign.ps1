# 给 crun.exe 做 Authenticode 签名（消除 "未知发布者" + 让 SmartScreen/AV 云信誉站得住）
#
# 用法:
#   # 1) PFX 方式
#   $env:CRUN_PFX_PASS = "PFX_PASSWORD"
#   powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Path dist\win\crun\crun.exe -Pfx cert.pfx
#
#   # 2) 证书存储方式（EV 证书装进证书库后，用指纹）
#   powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Path dist\win\crun\crun.exe -Thumbprint THUMBPRINT
param(
  [Parameter(Mandatory=$true)][string]$Path,
  [string]$Pfx = "",
  [string]$Thumbprint = "",
  [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
  $roots = @(
    "C:\Program Files (x86)\Windows Kits\10\bin",
    "C:\Program Files\Windows Kits\10\bin"
  )
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $f = Get-ChildItem $r -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName -match 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
      if ($f) { return $f.FullName }
    }
  }
  return $null
}

$signtool = Find-SignTool
if (-not $signtool) {
  Write-Warning "没找到 signtool.exe（需要 Windows SDK）。装 SDK 后重跑，或手动执行："
  Write-Host '  signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p <PFX_PASSWORD> "crun.exe"'
  exit 1
}

if ($Pfx) {
  if (-not $env:CRUN_PFX_PASS) { throw "请先设置环境变量 CRUN_PFX_PASS" }
  & $signtool sign /fd SHA256 /tr $Timestamp /td SHA256 /f $Pfx /p $env:CRUN_PFX_PASS $Path
} elseif ($Thumbprint) {
  & $signtool sign /fd SHA256 /tr $Timestamp /td SHA256 /sha1 $Thumbprint /sm $Path
} else {
  throw "必须给 -Pfx 或 -Thumbprint 之一"
}

if ($LASTEXITCODE -ne 0) { throw "签名失败，退出码 $LASTEXITCODE" }

& $signtool verify /pa /v $Path
Write-Host "`n签名完成，可用 Get-AuthenticodeSignature 复核。"
