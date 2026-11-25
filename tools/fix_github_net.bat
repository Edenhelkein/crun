@echo off
setlocal
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
if defined CRUN_HOSTS set "HOSTS=%CRUN_HOSTS%"

if not defined CRUN_NOELEV (
    net session >nul 2>&1
    if errorlevel 1 (
        echo Requesting administrator rights ... click YES in the popup.
        powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
        exit /b
    )
)

echo.
echo [1/4] backup hosts
if not exist "%HOSTS%.bak_crun" copy /y "%HOSTS%" "%HOSTS%.bak_crun" >nul
echo       saved: %HOSTS%.bak_crun

echo.
echo [2/4] write GitHub resolution entries
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%HOSTS%'; $l=Get-Content $p -ErrorAction SilentlyContinue; $keep=$l | Where-Object { $_ -notmatch 'crun-fix' -and $_ -notmatch '20\.205\.243\.(166|165|168)' -and $_ -notmatch '^185\.199\.108\.133 (raw|objects)\.githubusercontent\.com$' }; $add=@('# crun-fix','20.205.243.166 github.com','20.205.243.166 codeload.github.com','20.205.243.168 api.github.com','185.199.108.133 objects.githubusercontent.com','185.199.108.133 raw.githubusercontent.com','# crun-fix-end'); Set-Content -Path $p -Value ($keep + $add) -Encoding ascii"

echo.
echo [3/4] flush dns
ipconfig /flushdns >nul

echo.
echo [4/4] connectivity test
curl -s -o nul -w "  github.com      HTTP %%{http_code}  %%{time_total}s\n" --max-time 12 https://github.com/
curl -s -o nul -w "  api.github.com  HTTP %%{http_code}  %%{time_total}s\n" --max-time 12 https://api.github.com/
curl -s -o nul -w "  codeload        HTTP %%{http_code}  %%{time_total}s\n" --max-time 12 https://codeload.github.com/

echo.
echo If you see 200 / 301 above, it works. Tell me "ok".
echo To undo: copy %HOSTS%.bak_crun back over %HOSTS% (needs admin).
echo.
pause
