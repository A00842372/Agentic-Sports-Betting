@echo off
setlocal

set "TASK_NAME=Generate instance"
set "RUNNER=%~dp0run_generate_instance.bat"

if not exist "%RUNNER%" (
    echo ERROR: Cannot find "%RUNNER%". >&2
    exit /b 1
)

rem Task Scheduler's graphical editor only lists intervals of 5 minutes or more.
rem SCHTASKS supports a one-minute interval. /F replaces a task with this name.
schtasks.exe /Create /F /SC MINUTE /MO 1 /TN "%TASK_NAME%" /TR "%RUNNER%" /IT
if errorlevel 1 (
    echo.
    echo The task could not be created. Try running this file as administrator.
    pause
    exit /b 1
)

echo.
echo Created "%TASK_NAME%". It will run every minute while you are logged in.
echo Windows will skip a new launch if the previous launch is still running.
pause
