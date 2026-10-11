@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

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
if !errorlevel! neq 0 (
    echo.
    echo   uv is not installed.
    echo   Installing uv...
    echo.
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if !errorlevel! neq 0 (
        echo.
        echo   [ERROR] Failed to install uv.
        echo   Please install manually: https://docs.astral.sh/uv/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   uv installed successfully!
    echo.

    :: Refresh PATH to pick up new uv installation
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"

    :: Verify again
    where uv >nul 2>&1
    if !errorlevel! neq 0 (
        echo   [WARNING] uv not found in PATH after install.
        echo   Checking common install locations...
        if exist "%USERPROFILE%\.local\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.local\bin;!PATH!"
            echo   Found uv at %USERPROFILE%\.local\bin
        ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
            echo   Found uv at %USERPROFILE%\.cargo\bin
        ) else (
            echo.
            echo   [ERROR] Cannot find uv. Please restart this script after installation.
            pause
            exit /b 1
        )
    )
) else (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
    echo   uv is installed: !UV_VER!
)

echo.
echo  [2/4] Checking FFmpeg installation...
where ffmpeg >nul 2>&1
if !errorlevel! neq 0 (
    echo   [NOTICE] FFmpeg was not found in PATH.
    echo   Note: FFmpeg is required for video probing and splitting.
    echo   If you only need motion stitching, you can proceed without it.
    echo   To install FFmpeg, run: winget install Gyan.FFmpeg
) else (
    for /f "tokens=*" %%v in ('ffmpeg -version 2^>nul') do (
        set FFMPEG_VER=%%v
        goto :FFMPEG_FOUND_EN
    )
    :FFMPEG_FOUND_EN
    echo   FFmpeg is installed: !FFMPEG_VER!
)

echo.
echo  [3/4] Synchronizing dependencies with uv sync...
echo.
uv sync
if !errorlevel! neq 0 (
    echo.
    echo   [ERROR] uv sync failed.
    echo   Please check the error messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo   Dependencies synchronized successfully!

echo.
echo  [4/4] Starting Split ^& Stitch GUI...
echo.

uv run splitstitch gui

echo.
echo Application closed.
goto :END


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
if !errorlevel! neq 0 (
    echo.
    echo   uv がインストールされていません。
    echo   uv をインストールします...
    echo.
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if !errorlevel! neq 0 (
        echo.
        echo   [エラー] uv のインストールに失敗しました。
        echo   手動でインストールしてください: https://docs.astral.sh/uv/
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   uv のインストールが完了しました！
    echo.

    :: PATHを更新してインストールされたuvを認識
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;!PATH!"

    :: 再確認
    where uv >nul 2>&1
    if !errorlevel! neq 0 (
        echo   [警告] インストール後もuvがPATHに見つかりません。
        echo   既知のインストール先を確認中...
        if exist "%USERPROFILE%\.local\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.local\bin;!PATH!"
            echo   %USERPROFILE%\.local\bin に見つかりました
        ) else if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
            set "PATH=%USERPROFILE%\.cargo\bin;!PATH!"
            echo   %USERPROFILE%\.cargo\bin に見つかりました
        ) else (
            echo.
            echo   [エラー] uv が見つかりません。インストール完了後にスクリプトを再起動してください。
            pause
            exit /b 1
        )
    )
) else (
    for /f "tokens=*" %%v in ('uv --version 2^>nul') do set UV_VER=%%v
    echo   uv インストール済み: !UV_VER!
)

echo.
echo  [2/4] FFmpeg のインストール確認中...
where ffmpeg >nul 2>&1
if !errorlevel! neq 0 (
    echo   [お知らせ] FFmpeg が PATH に見つかりませんでした。
    echo   ※ 動画の解析・分割を行うには FFmpeg が必要です。
    echo   ※ モーション結合（Stitch）のみを行う場合はこのまま続行可能です。
    echo   インストール方法: winget install Gyan.FFmpeg または https://ffmpeg.org/
) else (
    for /f "tokens=*" %%v in ('ffmpeg -version 2^>nul') do (
        set FFMPEG_VER=%%v
        goto :FFMPEG_FOUND_JA
    )
    :FFMPEG_FOUND_JA
    echo   FFmpeg インストール済み: !FFMPEG_VER!
)

echo.
echo  [3/4] uv sync で依存パッケージを同期中...
echo.
uv sync
if !errorlevel! neq 0 (
    echo.
    echo   [エラー] uv sync に失敗しました。
    echo   上記のエラーメッセージを確認してください。
    echo.
    pause
    exit /b 1
)

echo.
echo   依存パッケージの同期が完了しました！

echo.
echo  [4/4] Split ^& Stitch GUI を起動中...
echo.

uv run splitstitch gui

echo.
echo アプリケーションが終了しました。

:END
endlocal
