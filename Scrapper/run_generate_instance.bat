@echo off
setlocal

rem Resolve CSV inputs and output files relative to this batch file.
pushd "%~dp0"
if errorlevel 1 exit /b 1

rem Use the project's Windows virtual environment without activating it.
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Cannot find .venv\Scripts\python.exe in the project folder. >&2
    popd
    exit /b 1
)

rem Append output and errors so scheduled runs can be inspected later.
echo [%date% %time%] Starting generate_instance.py >> "generate_instance.log"
".venv\Scripts\python.exe" -u "generate_instance.py" >> "generate_instance.log" 2>&1
set "RUN_EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] Finished with exit code %RUN_EXIT_CODE% >> "generate_instance.log"

popd
exit /b %RUN_EXIT_CODE%
