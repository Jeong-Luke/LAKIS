@echo off
if /i "%~1"=="--spinner" goto :spinner
setlocal EnableExtensions DisableDelayedExpansion
chcp 949 >nul
title LAKIS Studio Setup ^| CMD Version
color 0F
for /F "delims=" %%E in ('echo prompt $E^| cmd') do set "ESC=%%E"
set "RESET=%ESC%[0m"
set "PURPLE=%ESC%[38;2;151;108;255m"
set "BLUE=%ESC%[38;2;84;145;255m"
set "MUTED=%ESC%[38;2;145;155;180m"
set "GREEN=%ESC%[38;2;91;219;151m"
set "RED=%ESC%[38;2;255;105;120m"
set "BOLD=%ESC%[1m"

set "SCRIPT_DIR=%~dp0"
set "MANIFEST=%SCRIPT_DIR%cmd-installer-manifest.json"
set "INSTALLER=%SCRIPT_DIR%lakis_cmd_installer.py"
set "SPINNER=%~f0"
set "SEVEN_URL=https://www.7-zip.org/a/7zr.exe"
set "SEVEN_SHA=AD4C82FADCBDF93C03B4FC440F300509C7D60C5C2F4D183E35D9D70D6957037D"
set "BASE_URL=https://github.com/Comfy-Org/ComfyUI/releases/download/v0.21.1/ComfyUI_windows_portable_nvidia.7z"
set "BASE_SHA=7C380D4309BBDA395366C49564EDF8996181FD45E61B6F353EA417F32BC3B970"
set "TARGET=%LOCALAPPDATA%\Programs\LAKIS"
if not "%~1"=="" set "TARGET=%~f1"
set "CACHE=%LOCALAPPDATA%\LAKIS Studio\installer-cache"
for %%P in ("%TARGET%") do set "STAGE=%%~dpP.LAKIS-cmd-stage-%RANDOM%-%RANDOM%"

cls
call :header
echo   %MUTED%설치 위치%RESET%
echo   %BOLD%%TARGET%%RESET%
echo.
echo   %PURPLE%[##########..............................]%RESET%  설치 준비 완료
echo.

if not exist "%MANIFEST%" goto :missing_files
if not exist "%INSTALLER%" goto :missing_files
where curl.exe >nul 2>nul || goto :missing_curl
where certutil.exe >nul 2>nul || goto :missing_certutil
if exist "%TARGET%\*" goto :target_not_empty
if not exist "%CACHE%" mkdir "%CACHE%" || goto :failed
if exist "%STAGE%" goto :failed
mkdir "%STAGE%" || goto :failed

call :step "01" "설치 도구 준비"
call :download "%SEVEN_URL%" "%CACHE%\7zr.exe" "%SEVEN_SHA%" || goto :failed
call :step "02" "LAKIS 실행 파일 준비"
call :download "%BASE_URL%" "%CACHE%\ComfyUI_windows_portable_nvidia.7z" "%BASE_SHA%" || goto :failed

call :step "03" "실행 파일 압축 해제"
set "EXTRACT_MARKER=%STAGE%\extract.done"
if exist "%EXTRACT_MARKER%" del /q "%EXTRACT_MARKER%"
start "" /b cmd.exe /d /c call "%SPINNER%" --spinner "%EXTRACT_MARKER%" "압축 해제 중  ComfyUI_windows_portable_nvidia.7z"
"%CACHE%\7zr.exe" x -y -o"%STAGE%" "%CACHE%\ComfyUI_windows_portable_nvidia.7z" >"%STAGE%\extract.log" 2>&1
set "EXTRACT_EXIT=%ERRORLEVEL%"
>"%EXTRACT_MARKER%" echo done
if not "%EXTRACT_EXIT%"=="0" goto :failed
if not exist "%STAGE%\ComfyUI_windows_portable\python_embeded\python.exe" goto :failed
echo   %GREEN%확인%RESET%  LAKIS 실행 환경 준비 완료

call :step "04" "LAKIS 설치 및 파일 확인"
"%STAGE%\ComfyUI_windows_portable\python_embeded\python.exe" -s "%INSTALLER%" --manifest "%MANIFEST%" --portable-root "%STAGE%\ComfyUI_windows_portable" --target "%TARGET%" --cache "%CACHE%"
if errorlevel 1 goto :failed

cls
call :header
echo   %GREEN%%BOLD%[########################################]%RESET%
echo.
echo   %GREEN%%BOLD%설치가 완료되었습니다%RESET%
echo   모든 공식 파일의 무결성 검사를 통과했습니다.
echo.
echo   %MUTED%LAKIS를 실행합니다. 이 창은 잠시 후 자동으로 닫힙니다.%RESET%
echo.
start "" /d "%TARGET%" "%TARGET%\LAKIS.exe"
timeout /t 3 /nobreak >nul
exit /b 0

:header
echo.
echo   %PURPLE%%BOLD% _          _       _  __%BLUE%  ___   ____  %RESET%
echo   %PURPLE%%BOLD%^| ^|        / \     ^| ^|/ /%BLUE% ^|_ _^| / ___^| %RESET%
echo   %PURPLE%%BOLD%^| ^|       / _ \    ^| ' / %BLUE%  ^| ^|  \___ \ %RESET%
echo   %PURPLE%%BOLD%^| ^|___   / ___ \   ^| . \ %BLUE%  ^| ^|   ___) ^|%RESET%
echo   %PURPLE%%BOLD%^|_____^| /_/   \_\  ^|_^|\_\%BLUE% ^|___^| ^|____/ %RESET%
echo.
echo   %BOLD%LAKIS STUDIO SETUP%RESET%  %MUTED%CMD VERSION%RESET%
echo   %MUTED%--------------------------------------------------------%RESET%
echo.
exit /b 0

:step
echo.
echo   %PURPLE%%BOLD%[%~1 / 04]%RESET%  %BOLD%%~2%RESET%
echo   %MUTED%--------------------------------------------------------%RESET%
exit /b 0

:download
set "DL_URL=%~1"
set "DL_FILE=%~2"
set "DL_SHA=%~3"
if exist "%DL_FILE%" call :verify "%DL_FILE%" "%DL_SHA%" && exit /b 0
if exist "%DL_FILE%" del /q "%DL_FILE%"
if exist "%DL_FILE%.part" (
  certutil.exe -hashfile "%DL_FILE%.part" SHA256 | findstr /i /c:"%DL_SHA%" >nul
  if not errorlevel 1 (
    move /y "%DL_FILE%.part" "%DL_FILE%" >nul || exit /b 1
    call :verify "%DL_FILE%" "%DL_SHA%"
    exit /b
  )
)
echo   %BLUE%다운로드%RESET%  %~nx2
set "DL_RANGE_RESET=0"
:download_transfer
curl.exe --fail --location --retry 5 --retry-all-errors --retry-delay 3 --connect-timeout 30 --continue-at - --progress-bar --write-out "%%{http_code}\n" --output "%DL_FILE%.part" "%DL_URL%" >"%DL_FILE%.http"
set "DL_EXIT=%ERRORLEVEL%"
if "%DL_EXIT%"=="33" goto :download_range_reset
findstr /x /c:"416" "%DL_FILE%.http" >nul
if not errorlevel 1 goto :download_range_reset
if not "%DL_EXIT%"=="0" goto :download_failed
goto :download_received
:download_range_reset
if "%DL_RANGE_RESET%"=="1" goto :download_failed
del /q "%DL_FILE%.part" 2>nul
if exist "%DL_FILE%.part" goto :download_failed
set "DL_RANGE_RESET=1"
goto :download_transfer
:download_received
del /q "%DL_FILE%.http" 2>nul
move /y "%DL_FILE%.part" "%DL_FILE%" >nul || exit /b 1
call :verify "%DL_FILE%" "%DL_SHA%" || exit /b 1
exit /b 0

:download_failed
echo.
echo   %RED%다운로드 연결이 중간에 끊겼습니다.%RESET%
echo   인터넷 연결을 확인한 뒤 설치기를 다시 실행해 주세요.
echo   이미 받은 부분은 보관되며 다음 실행에서 이어서 다운로드합니다.
exit /b 1

:verify
certutil.exe -hashfile "%~1" SHA256 | findstr /i /c:"%~2" >nul
if errorlevel 1 (
  echo   %RED%실패%RESET% SHA-256 파일 검증 실패: %~nx1
  exit /b 1
)
echo   %GREEN%확인%RESET%  %~nx1
exit /b 0

:missing_files
echo   %RED%설치 파일이 일부 누락되었습니다.%RESET%
echo   ZIP 파일의 압축을 완전히 푼 뒤 다시 실행해 주세요.
goto :failed
:missing_curl
echo   %RED%Windows 다운로드 기능을 사용할 수 없습니다.%RESET%
echo   Windows 10 버전 1803 이상이 필요합니다.
goto :failed
:missing_certutil
echo   %RED%Windows 파일 검증 기능을 사용할 수 없습니다.%RESET%
goto :failed
:target_not_empty
echo   %RED%설치 폴더가 비어 있지 않습니다.%RESET%
echo   이 설치 방법은 현재 신규 설치만 지원합니다.
echo   기존 LAKIS가 있다면 공식 복구 또는 업데이트 기능을 이용해 주세요.
goto :failed
:failed
echo.
echo   %RED%%BOLD%설치가 중단되었습니다%RESET%
echo   기존 사용자 파일은 변경하지 않았습니다.
echo.
echo   %MUTED%문제 확인용 임시 폴더:%RESET%
echo   %STAGE%
echo.
pause
exit /b 1
:spinner
setlocal EnableExtensions DisableDelayedExpansion
chcp 949 >nul
for /F "delims=" %%E in ('echo prompt $E^| cmd') do set "ESC=%%E"
set "MARKER=%~2"
set "MESSAGE=%~3"
set /a FRAME=0
:spinner_loop
if exist "%MARKER%" goto :spinner_done
set /a FRAME=(FRAME+1)%%4
if %FRAME%==0 set "GLYPH=|"
if %FRAME%==1 set "GLYPH=/"
if %FRAME%==2 set "GLYPH=-"
if %FRAME%==3 set "GLYPH=\"
<nul set /p "=%ESC%[2K%ESC%[1G  %MESSAGE%  %GLYPH%"
ping.exe -n 2 127.0.0.1 >nul
goto :spinner_loop
:spinner_done
<nul set /p "=%ESC%[2K%ESC%[1G"
exit /b 0