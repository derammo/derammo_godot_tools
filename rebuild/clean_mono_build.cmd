@REM adjust if you installed Mono else where
call "C:\Program Files\Mono\\bin\setmonopath.bat"
if ERRORLEVEL 1 (
    @echo Please install Mono and make sure this script calls it correctly.
    exit /b 1
)

@REM must have clean build so everything is in the XML
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug module_mono_enabled=yes tests=yes -c -Q
if ERRORLEVEL 1 (
    @echo Clean failed.
    exit /b 4
)

@REM make XML named after this directory, because I have many of them
@for %%I in (.) do @set BASE_NAME=%%~nxI
@set XML_PATH=..\%BASE_NAME%_console_debug_mono.xml
@echo XML build data will be %XML_PATH%

@REM build (note vsproj is broken with mono)
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug xml=yes module_mono_enabled=yes tests=yes > %XML_PATH%.txt
if ERRORLEVEL 1 (
    @echo Mono build failed.
    exit /b 5
)

call ..\derammo_godot_tools\rebuild\create_build_from_log.cmd console_debug_mono vs22

@REM generate mono glue
if exist "bin\godot.windows.tools.64.mono" (
    bin\godot.windows.tools.64.mono --generate-mono-glue modules\mono\glue
) else (
    bin\godot.windows.tools.x86_64.mono --generate-mono-glue modules\mono\glue
)

@REM generate solutions
@for %%I in (.) do @set NUGET_SOURCE=%%~fI\bld\nuget
if exist "nuget.config" (
    @echo "nuget.config already exists, not adding additional source"
) else (
    dotnet new nugetconfig
    dotnet nuget add source %NUGET_SOURCE% --name Godot --configfile .\nuget.config
)
mkdir bld\nuget
python modules/mono/build_Scripts/build_assemblies.py --godot-output-dir ./bin --push-nupkgs-local %NUGET_SOURCE%