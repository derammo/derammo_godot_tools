@REM must have clean build so everything is in the XML
scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug no_progress=yes tests=yes -c -Q

@REM make XML named after this directory, because I have many of them
@for %%I in (.) do @set BASE_NAME=%%~nxI
@set XML_PATH=..\%BASE_NAME%_console_debug.xml
@echo XML build data will be %XML_PATH%

scons -j16 vulkan=yes opengl3=yes platform=windows windows_subsystem=console target=debug vsproj=yes xml=yes tests=yes > %XML_PATH%.txt

call ..\derammo_godot_tools\rebuild\create_build_from_log.cmd console_debug