@echo off
title Scale Slimy Fish - Auto Bot
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo An error occurred while running the bot.
    pause
)
