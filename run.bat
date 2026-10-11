@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: Move to script directory safely
cd /d "%~dp0"

:: ============================================================
:: Split & Stitch for QuickMagicMotion — Launcher (Windows)
:: ============================================================

title Split & Stitch for QuickMagicMotion

echo.
echo  ============================================================
echo   Split ^& Stitch for QuickMagicMotion - Launcher
echo  ============================================================
echo.
echo   Please select your language / 言語を選択してください
echo.
echo     [1] English
echo     [2] 日本語
echo.
set /p LANG_CHOICE="  Select [1/2]: "

if "%LANG_CHOICE%"=="2" goto :LANG_JA
goto :LANG_EN

:: ============================================================
:: ENGLISH
:: ============================================================
:LANG_EN
cls
echo.
echo  ============================================================
echo   Split ^& Stitch for QuickMagicMotion - Setup ^& Launcher
echo  ============================================================
echo.

echo  [1/4] Checking uv installation...
where uv >nul 2>&1
if !errorlevel! equ 0 goto :UV_OK_EN

echo.
echo   uv is not installed.
echo   Installing uv...
echo.
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
if !errorlevel! neq 0 goto :UV_INSTALL_FAIL_EN

echo.
echo   uv installed successfully!
echo.

set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"
where uv >nul 2>&1
if !errorlevel! equ 0 goto :UV_OK_EN

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;!PATH!"
    goto :UV_OK_EN
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
    goto :UV_OK_EN
)

:UV_INSTALL_FAIL_EN
echo.
echo   [ERROR] Cannot find or install uv. Please install manually: https://docs.astral.sh/uv/
echo.
pause
exit /b 1

:UV_OK_EN
for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
echo   uv is installed: !UV_VER!

echo.
echo  [2/4] Checking FFmpeg installation...
where ffmpeg >nul 2>&1
if !errorlevel! neq 0 (
    echo   [NOTICE] FFmpeg was not found in PATH.
    echo   Note: FFmpeg is required for video probing and splitting.
    echo   If you only need motion stitching, you can proceed without it.
    echo   To install FFmpeg, run: winget install Gyan.FFmpeg
    goto :FFMPEG_DONE_EN
)
for /f "tokens=*" %%v in ('ffmpeg -version 2^>nul') do (
    echo   FFmpeg is installed: %%v
    goto :FFMPEG_DONE_EN
)
:FFMPEG_DONE_EN

echo.
echo  [3/4] Synchronizing dependencies with uv sync...
echo.
uv sync
if !errorlevel! neq 0 goto :SYNC_FAIL_EN

echo.
echo   Dependencies synchronized successfully!

echo.
echo  [4/4] Starting Split ^& Stitch GUI...
echo.
uv run splitstitch gui

echo.
echo Application closed.
goto :END

:SYNC_FAIL_EN
echo.
echo   [ERROR] uv sync failed. Please check error messages above.
echo.
pause
exit /b 1


:: ============================================================
:: 日本語
:: ============================================================
:LANG_JA
cls
echo.
echo  ============================================================
echo   Split ^& Stitch for QuickMagicMotion - セットアップ ＆ ランチャー
echo  ============================================================
echo.

echo  [1/4] uv のインストール確認中...
where uv >nul 2>&1
if !errorlevel! equ 0 goto :UV_OK_JA

echo.
echo   uv がインストールされていません。
echo   uv をインストールします...
echo.
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
if !errorlevel! neq 0 goto :UV_INSTALL_FAIL_JA

echo.
echo   uv のインストールが完了しました！
echo.

set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"
where uv >nul 2>&1
if !errorlevel! equ 0 goto :UV_OK_JA

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;!PATH!"
    goto :UV_OK_JA
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
    goto :UV_OK_JA
)

:UV_INSTALL_FAIL_JA
echo.
echo   [エラー] uv が見つからないか、インストールに失敗しました。
echo   手動でインストールしてください: https://docs.astral.sh/uv/
echo.
pause
exit /b 1

:UV_OK_JA
for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
echo   uv インストール済み: !UV_VER!

echo.
echo  [2/4] FFmpeg のインストール確認中...
where ffmpeg >nul 2>&1
if !errorlevel! neq 0 (
    echo   [お知らせ] FFmpeg が PATH に見つかりませんでした。
    echo   ※ 動画の解析・分割を行うには FFmpeg が必要です。
    echo   ※ モーション結合（Stitch）のみを行う場合はこのまま続行可能です。
    echo   インストール方法: winget install Gyan.FFmpeg または https://ffmpeg.org/
    goto :FFMPEG_DONE_JA
)
for /f "tokens=*" %%v in ('ffmpeg -version 2^>nul') do (
    echo   FFmpeg インストール済み: %%v
    goto :FFMPEG_DONE_JA
)
:FFMPEG_DONE_JA

echo.
echo  [3/4] uv sync で依存パッケージを同期中...
echo.
uv sync
if !errorlevel! neq 0 goto :SYNC_FAIL_JA

echo.
echo   依存パッケージの同期が完了しました！

echo.
echo  [4/4] Split ^& Stitch GUI を起動中...
echo.
uv run splitstitch gui

echo.
echo アプリケーションが終了しました。
goto :END

:SYNC_FAIL_JA
echo.
echo   [エラー] uv sync に失敗しました。上記のエラーメッセージを確認してください。
echo.
pause
exit /b 1

:END
endlocal
