@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set QT_QPA_PLATFORM=
pushd "%~dp0"
"F:\anaconda3\python.exe" main.py --debug %*
popd
pause
