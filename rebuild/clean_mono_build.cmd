@REM adjust if you installed Mono else where
call "C:\Program Files\Mono\\bin\setmonopath.bat"
if ERRORLEVEL 1 (
    @echo Please install Mono and make sure this script calls it correctly.
    exit /b 1
)

@REM build temporary (note vsproj is broken with mono)
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug no_progress=yes module_mono_enabled=yes mono_glue=false -Q
if ERRORLEVEL 1 (
    @echo Generator build failed.
    exit /b 2
)

@REM generate glue
bin\godot.windows.tools.64.mono --generate-mono-glue modules\mono\glue
@REM REVISIT used for debugging, remove
tar -cvzf bld\vs19\mono_glue.tar.gz modules\mono\glue
if ERRORLEVEL 1 (
    @echo Glue generation failed.
    exit /b 3
)

@REM must have clean build so everything is in the XML
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug module_mono_enabled=yes mono_glue=false tests=yes no_progress=yes -c -Q
if ERRORLEVEL 1 (
    @echo Clean failed.
    exit /b 4
)

@REM make XML named after this directory, because I have many of them
@for %%I in (.) do @set BASE_NAME=%%~nxI
@set XML_PATH=..\%BASE_NAME%_console_debug_mono.xml
@echo XML build data will be %XML_PATH%

scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug xml=yes module_mono_enabled=yes mono_glue=yes tests=yes > %XML_PATH%.txt
if ERRORLEVEL 1 (
    @echo Final build failed.
    exit /b 5
)

@REM filter just the lines that have our XML, to eliminate warnings etc.
@REM WARNING: can't do this with a pipe, because findstr only reads 8KB line buffers on piped input
findstr __BUILD_DATA_MAGIC_COOKIE__ %XML_PATH%.txt > %XML_PATH%

@REM generate the equivalent Visual Studio build in a folder that is already gitignored anyway
pushd ..\derammo_godot_tools\rebuild\
python create_build_from_log.py ..\%XML_PATH% -S ..\..\%BASE_NAME% -B ..\..\%BASE_NAME% -M vs19 --closed --edit-and-continue
popd