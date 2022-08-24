# Visual Studio Rebuild

This script creates alternative Visual Studio project files and a solution file to allow native Visual Studio build without SCons.

Project files are placed out-of-tree (anywhere you like) and use separate properties files for all shared settings.  Using the `--closed` option on the generator (as I do) flattens these shared files back into normal .vcxproj files that can be edited in the IDE.

The tool has many important limitations that you must read before using:

## Resulting build are not official

The resulting builds are compiled just as they were by SCons.  However, they should be considered a dirty build for debugging or developement only, and you must not file bugs against such builds, as they may be corrupted in some cases.  Always use the SCons build for confirming your final versions of the code or filing any bugs.

## Must first run SCons

Not all outputs are created by the alternative projects.  The equivalent SCons build must be run at least once.  Resources for example are not compiled and can't be re-compiled using the alternative projects.  This tool is intended for rapid prototyping on top of a good SCons build, to selectively recompile pieces of Godot and even use Edit and Continue.

## Must patch SConstruct

The patch to the Godot SConstruct file must be applied first

```
cd ..\..\godot
git apply ..\derammo_godot_tools\rebuild\scons_xml.patch
```

This will change if the relevant PR is approved and the xml log feature is added to Godot.

## Many options are not implemented (yet)

This is a work in progress.

## Only 64 bit Debug builds supported

The code for release_debug builds will follow soon.  I have no plans to support 32 bit, but contributions are welcome.

- `clean_console_build.cmd` shows the procedure for making a console build without Mono (C#)
- `clean_mono_build.cmd` does the compilation procedure to support `modules\mono` (C#)

## Only Visual Studio 2019 supported

Templates for 2022 have not yet been added.

## Some files are not yet added to projects

- natvis
- rulesets

# Instructions

To learn about options, run 
```
python create_build_from_log.py --help
```

To use it the way that I do, run the included script or adapt the script to your preferences:

```
cd ..\..\godot
..\derammo_godot_tools\rebuild\clean_console_build.cmd
```

This will create a clean debug console build (the only config supported so far) and create the build report XML.  This part will take a long time, so go drink coffee.  Then it creates the closed form projects with edit and continue enabled.  You can then open the godot_rebuild_vs19.sln solution and start working on code.

## Mono Instructions

- `clean_mono_build.cmd` does the compilation procedure to support `modules\mono` (C#)
- it also creates a `nuget.config` file in the current folder (Godot root) that you can copy to your Godot project's folder to set up paths
