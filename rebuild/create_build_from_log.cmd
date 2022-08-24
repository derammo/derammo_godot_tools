@REM the XML is named after this directory, because I have many of them
@for %%I in (.) do @set BASE_NAME=%%~nxI
@set XML_PATH=..\%BASE_NAME%_%1.xml
@echo XML build data will be %XML_PATH%

@REM filter just the lines that have our XML, to eliminate warnings etc.
@REM WARNING: can't do this with a pipe, because findstr only reads 8KB line buffers on piped input
findstr __BUILD_DATA_MAGIC_COOKIE__ %XML_PATH%.txt > %XML_PATH%

@REM generate the equivalent Visual Studio build in a folder that is already gitignored anyway
pushd ..\derammo_godot_tools\rebuild\
python create_build_from_log.py ..\%XML_PATH% -S ..\..\%BASE_NAME% -B ..\..\%BASE_NAME% -M %2 --closed --edit-and-continue
popd