@REM must have clean build so everything is in the XML
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug no_progress=yes tests=yes -c -Q

@REM make XML named after this directory, because I have many of them
@for %%I in (.) do @set BASE_NAME=%%~nxI
@set XML_PATH=..\%BASE_NAME%_console_debug.xml
@echo XML build data will be %XML_PATH%

scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug vsproj=yes xml=yes tests=yes > %XML_PATH%.txt

@REM filter just the lines that have our XML, to eliminate warnings etc.
@REM WARNING: can't do this with a pipe, because findstr only reads 8KB lines on piped input
findstr __BUILD_DATA_MAGIC_COOKIE__ %XML_PATH%.txt > %XML_PATH%

@REM generate the equivalent Visual Studio build in a folder that is already gitignored anyway
pushd ..\derammo_godot_tools\rebuild\
python create_build_from_log.py ..\%XML_PATH% -S ..\..\%BASE_NAME% -B ..\..\%BASE_NAME% -M vs19 --closed --edit-and-continue
popd