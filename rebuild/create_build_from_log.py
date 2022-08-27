# MIT License
#
# Copyright (c) 2022 Ammo Goettsch
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
import argparse
import os
import pathlib
import re
import shutil
import uuid
import bisect
from dataclasses import dataclass, field
from typing import Dict, Any, List
from xml.etree import ElementTree as xml

command_line = argparse.ArgumentParser(
    description="Generate Visual Studio native project files outside the source tree",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
command_line.add_argument('build_report_path', type=str,
                          help='path to the XML build report (output from "scons xml=true platform=windows target=debug") to read')
command_line.add_argument('--source-repo-path', '-S', type=str, default='../godot/',
                          help='path to the repo; only the new solution file and binaries will be placed here')
command_line.add_argument('--build-path', '-B', type=str, default='../godot_build/',
                          help='path to the build tree to generate; all project files and temporary output go here')
command_line.add_argument('--closed', default=False, action='store_true', help='create one self-contained project file per module instead of the default inheritance tree')
command_line.add_argument('--build-flavor', '-F', type=str, default=".windows.tools.x86_64",
                          help='the decoration for binaries created by the build for which XML is provided')
command_line.add_argument('--verbose', default=False, action='store_true', help='prints some more verbose output')
command_line.add_argument('--vs-version', '-M', type=str, default='vs19',
                          help='version of Visual Studio templates to use, see templates folder')
command_line.add_argument('--edit-and-continue', '-E', default=False, action='store_true',
                          help='build all modules with /ZI for edit and continue support in Visual Studio')
command_line.add_argument('--dry-run', default=False, action='store_true',
                          help='runs the parser and generators without producing any files, for testing')
command_line.add_argument('--dirty', default=False, action='store_true',
                          help='only overwrite certain files, don not recreate the build tree, for testing')
command_line.add_argument('--in-tree', default=False, action='store_true',
                          help='place the project files directly in the source tree to help out certain tools that expect that; NOTE: you have to modify .gitignore to exclude them from source control')
command_line.add_argument('--flat-filters', default=False, action='store_true',
                          help='place files in "Source Files" and "Header Files" solution folders instead of according to file system hierarchy')
command_line.add_argument('--merge', action='append',
                          help='each instance of this option will merge the specified module into a new module called "merged", to compile them together to make certain tools work (e.g. Visual Studio Class Diagrams)')

options = command_line.parse_args()

# need trailing slashes, but don't make a root access by mistake!
def sanitize_directory_path(path: str) -> str:
    if len(path) < 1:
        return path

    if path.endswith('/') or path.endswith('\\') or path.endswith('..'):
        return path

    return f'{path}\\'


options.source_repo_path = sanitize_directory_path(options.source_repo_path)
options.build_path = sanitize_directory_path(options.build_path)
options.repo_name = pathlib.Path(options.source_repo_path).name
options.project_guid_namespace = uuid.UUID(int=0x1337)

# Set up flags/settings processing, which only changes the build when requested, so that by default
# it will be the same as what SCons made.
@dataclass
class SettingsProcessing:
    remove_flags: list[str] = field(default_factory=list)
    module_compile_xml: dict[str, str] = field(default_factory=dict)
settings_processing: SettingsProcessing = SettingsProcessing()

if options.edit_and_continue:
    settings_processing.remove_flags.append('/Z7')
    settings_processing.remove_flags.append('/Zi')
    settings_processing.remove_flags.append('/ZI')
    settings_processing.module_compile_xml['DebugInformationFormat'] = 'EditAndContinue'

if options.in_tree:
    raise NotImplementedError("--in-tree")

if options.merge:
    raise NotImplementedError("--merge")

if options.build_flavor != ".windows.tools.x86_64":
    raise NotImplementedError("--build-flavor")


# create all nodes in this namespace
PROJECT_NAMESPACE = "http://schemas.microsoft.com/developer/msbuild/2003"
xml.register_namespace("", PROJECT_NAMESPACE)

# magic GUID that says "this project is a C++ project" when used in a Solution file
CXX_PROJECT_TYPE = "{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}"

# MS XML values for -W0|-w, -W1, ...
WARNING_LEVELS = ['TurnOffAllWarnings', 'Level1', 'Level2', 'Level3', 'Level4', 'Level5']

# master info read from XML
cc = {}
cxx = {}
ar = {}
link = {}


def get_root_dir(version: str) -> str:
    return f'bld/{options.vs_version}/'


output_path = pathlib.Path(f"{options.build_path}{get_root_dir(options.vs_version)}")


@dataclass
class TargetInfo:
    path: pathlib.Path

    name: str

    # raw data from XML
    data: Dict[str, Any]

    includes: Dict[str, Dict] = field(default_factory=dict)
    libpaths: Dict[str, Dict] = field(default_factory=dict)
    defines: Dict[str, Dict] = field(default_factory=dict)
    compile_settings: Dict[str, Dict] = field(default_factory=dict)
    lib_settings: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class ModuleInfo(TargetInfo):
    # XXX port to single Dict[str, TargetInfo]
    # NOTE: this is the master collection
    sources: Dict[str, Dict] = field(default_factory=dict)
    headers: List[str] = field(default_factory=list)
    opaque_objects: List[str] = field(default_factory=list)
    src_includes: Dict[str, Dict[str, Dict]] = field(default_factory=dict)
    src_defines: Dict[str, Dict[str, Dict]] = field(default_factory=dict)
    obj_lib_settings: Dict[str, Dict[str, Dict]] = field(default_factory=dict)


def recreate_build_tree():
    if options.dry_run:
        return
    if os.path.exists(output_path):
        shutil.rmtree(output_path)
    if not os.path.exists(output_path.parent):
        os.makedirs(output_path.parent)
    shutil.copytree(f'templates/{options.vs_version}/{get_root_dir(options.vs_version)}', output_path)


# master db
modules: Dict[str, ModuleInfo] = {}


def create_project():
    return xml.parse(f'templates/{options.vs_version}/include_project.xml')


def write_to_file(path, doc):
    xml.indent(doc)
    if options.dry_run:
        return
    with open(path, "wb") as output:
        output.write('<?xml version="1.0" encoding="utf-8"?>\n'.encode('utf-8'));
        # WARNING: don't let this write the xml header, because Visual Studio won't like the
        # single quotes and will change them, making the project file dirty.
        doc.write(
            output,
            encoding='utf-8',
            method='xml')
    fix_line_endings_in_place(path)


def fix_line_endings_in_place(path):
    with open(path, 'rb') as open_file:
        content = open_file.read()
    content = content.replace(b'\r\r', b'\r')
    content = content.replace(b'\r\n', b'\n')
    content = content.replace(b'\n', b'\r\n')
    with open(path, 'wb') as open_file:
        open_file.write(content)


# XXX doesn't quite work in open mode, looks like we need to edit the project guid in there,
# because otherwise IDE will add it and want to save the project file
# TODO CHECK if this still happens since we fixed the guid capitalization and quotes
def write_project(path, path_relative_to_source_repo, project_namespace):
    doc = create_project()
    project = doc.getroot()
    property_group = xml.SubElement(project, 'PropertyGroup')
    guid_element = xml.SubElement(property_group, 'ProjectGuid')
    guid = str(uuid.uuid5(options.project_guid_namespace, "%s/%s" % (options.repo_name, path_relative_to_source_repo))).upper()
    guid_element.text = f'{{{guid}}}'
    namespace = xml.SubElement(property_group, 'RootNamespace')
    namespace.text = project_namespace
    source_tree_path = xml.SubElement(property_group, 'ParentPathInSourceTree')
    source_tree_path.text = f'$(SolutionDir)\\{pathlib.Path(path_relative_to_source_repo).parent}\\'
    write_to_file(path, doc)


def build_additional(parent, element_tag, flags_dictionary, condition=None):
    if len(flags_dictionary) < 1:
        return
    all_settings = ""
    for flags, settings in flags_dictionary.items():
        all_settings += settings
        all_settings += " "

    # fix special cases that happen all the time and have no impact:
    if element_tag == 'AdditionalOptions':
        warning_level_element = None
        warning_level = re.search('/W([0-9]) ', all_settings)
        if warning_level:
            # don't pointlessly set /w or /W0 and then override with higher warning level
            all_settings = re.sub('/w |/W[0-9] ', '', all_settings)

            # convert to XML setting to avoid override warnings
            warning_level_element = xml.SubElement(parent, "WarningLevel")
            warning_level_element.text = f'{WARNING_LEVELS[int(warning_level.group(1))]}'
        if re.search('/w ', all_settings):
            # must have been present without any /W
            all_settings = re.sub('/w ', '', all_settings)
            # convert to XML setting to avoid override warnings
            warning_level_element = xml.SubElement(parent, "WarningLevel")
            warning_level_element.text = f'{WARNING_LEVELS[0]}'
        if condition and warning_level_element != None:
            warning_level_element.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")

    additional_options = xml.SubElement(parent, element_tag)
    if condition:
        additional_options.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    additional_options.text = all_settings


# NOTE: this includes both compiled and opaque obj sources as well as headers
def write_sources(path, module: ModuleInfo, condition=None):
    doc = create_project()
    project = doc.getroot()
    item_group = xml.SubElement(project, 'ItemGroup')
    if condition:
        item_group.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    solution_root = pathlib.Path(os.path.relpath(options.source_repo_path, str(pathlib.Path(path).parent)))
    for compile_path, override_flags in module.sources.items():
        clcompile = xml.SubElement(item_group, 'ClCompile')
        clcompile.set('Include', str(solution_root / compile_path))
        if compile_path in module.src_defines:
            build_additional(clcompile, 'PreprocessorDefinitions', module.src_defines[compile_path])
        if len(override_flags) > 0:
            build_additional(clcompile, 'AdditionalOptions', override_flags)
        if compile_path in module.src_includes:
            build_additional(clcompile, 'AdditionalIncludeDirectories', module.src_includes[compile_path])

    headers = xml.SubElement(project, 'ItemGroup')
    if condition:
        headers.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    for header_path in module.headers:
        xml.SubElement(headers, 'ClInclude', { 'Include': str(solution_root / header_path) })

    objects = xml.SubElement(project, 'ItemGroup')
    if condition:
        objects.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    for obj_path in module.opaque_objects:
        xml.SubElement(objects, 'Object', { 'Include': str(solution_root / obj_path) })
    write_to_file(path, doc)


def write_module_settings(path, module: ModuleInfo, condition=None):
    doc = create_project()
    project = doc.getroot()
    item_definition_group = xml.SubElement(project, 'ItemDefinitionGroup')
    if condition:
        item_definition_group.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    clcompile = xml.SubElement(item_definition_group, 'ClCompile')
    build_additional(clcompile, 'PreprocessorDefinitions', module.defines)
    if module.compile_settings:
        build_additional(clcompile, 'AdditionalOptions', module.compile_settings)
    if module.includes:
        build_additional(clcompile, 'AdditionalIncludeDirectories', module.includes)
    for compile_setting_name, compile_setting_value in settings_processing.module_compile_xml.items():
        compile_setting = xml.SubElement(clcompile, compile_setting_name)
        compile_setting.text = compile_setting_value
    if len(module.lib_settings) > 0:
        lib = xml.SubElement(item_definition_group, 'Lib')
        build_additional(lib, 'AdditionalOptions', module.lib_settings)
    xml.indent(doc)
    write_to_file(path, doc)


def write_module_libraries(path, module: ModuleInfo, condition=None):
    doc = create_project()
    project = doc.getroot()
    item_definition_group = xml.SubElement(project, 'ItemDefinitionGroup')
    if condition:
        item_definition_group.set('Condition', f"'$(Configuration)|$(Platform)'=='{condition}'")
    link = xml.SubElement(item_definition_group, 'Link')
    additional_dependencies = xml.SubElement(link, 'AdditionalDependencies')
    additional_dependencies.text = ';'.join(module.other_libraries)
    # NOTE: no %(AdditionalDependencies) since we don't use the defaults, just what the xml says

    # attach linker flags
    if 'linkflags' in module.data:
        build_additional(link, 'AdditionalOptions', {'linkflags': module.data['linkflags']})

    if len(module.libpaths) > 0:
        additional_library_directories = xml.SubElement(link, 'AdditionalLibraryDirectories')
        additional_library_directories.text = module.libpaths

    write_to_file(path, doc)


# REVISIT this doesn't work too well for options that aren't overridden, like /TD.  vs19
# for now we don't use this for compile settings and just always set all options per file, since we do that anyway for many many cases?
def calculate_overrride_flags(objs, flags_names, process_text=None) -> (Dict, Dict):
    unique_counts = {
    }

    for flags in flags_names:
        unique_counts[flags] = {}

    for obj in objs:
        data: dict = cxx.get(obj)
        if not data:
            data = cc.get(obj)
            if not data:
                # must be resource
                continue
            if 'cxxflags' in data:
                # don't use C++ flags since the compiler doesn't
                data.pop('cxxflags')
        for flags in flags_names:
            if not flags in data:
                continue
            if process_text:
                settings = process_text(data[flags], False)
            else:
                settings = data[flags]
            if settings in unique_counts[flags]:
                unique_counts[flags][settings] += 1
            else:
                unique_counts[flags][settings] = 1

    module_settings = {}
    item_settings = {}

    for flags in flags_names:
        most_popular = sorted(unique_counts[flags], key=lambda record: unique_counts[flags][record], reverse=True)
        if len(most_popular) > 0:
            if process_text:
                module_settings[flags] = process_text(most_popular[0], True)
            else:
                module_settings[flags] = most_popular[0]
            if options.verbose:
                print(" ", flags, ":", module_settings[flags])

    for obj in objs:
        data = cxx.get(obj) or cc.get(obj)
        if not data:
            # must be resource
            continue
        override_flags = {}
        for flags in flags_names:
            if not flags in data:
                continue
            if process_text:
                settings = process_text(data[flags], False)
            else:
                settings = data[flags]
            if settings != module_settings[flags]:
                override_flags[flags] = settings
        item_settings[data['source']] = override_flags

    return module_settings, item_settings


def calculate_item_settings(objs, flags_names, process_text=None) -> (Dict, List[str]):
    obj_settings = {}
    opaque_objects = []
    for obj in objs:
        data = cxx.get(obj)
        if not data:
            data = cc.get(obj)
            if not data:
                # must be a resource, just link the obj and don't recompile it for now while we don't compile those
                opaque_objects.append(obj)
                continue
            if 'cxxflags' in data:
                # don't use C++ flags since the compiler doesn't
                data.pop('cxxflags')
        obj_flags = {}
        for flags in flags_names:
            if not flags in data:
                continue
            if process_text:
                obj_flags[flags] = process_text(data[flags], False)
            else:
                obj_flags[flags] = data[flags]
        obj_settings[data['source']] = obj_flags

    return obj_settings, opaque_objects


def process_include(text: str, is_module: bool):
    includes = text.split('/I')
    processed = []
    for include in includes:
        clean = include.strip()
        if len(clean) < 1:
            continue
        if pathlib.Path(clean).is_absolute():
            processed.append(clean)
        else:
            processed.append(f'$(SolutionDir)\\{clean}')
    return ';'.join(processed)


def process_libpath(text: str, is_module: bool):
    libpaths = text.split('/LIBPATH:')
    processed = []
    for libpath in libpaths:
        clean = libpath.strip()
        if len(clean) < 1:
            continue
        if pathlib.Path(clean).is_absolute():
            processed.append(clean)
        else:
            processed.append(f'$(SolutionDir)\\{clean}')
    return ';'.join(processed)


def process_flags(text: str, is_module: bool):
    filtered = text
    for remove_flag in settings_processing.remove_flags:
        filtered = re.sub(f'( |^){remove_flag}( |$)', ' ', filtered)
    return filtered


def process_define(text:str, is_module: bool):
    # XXX TODO special case DPCRE2_CODE_UNIT_WIDTH to keep from having to override all defines
    # return re.sub('DPCRE2_CODE_UNIT_WIDTH; ', '', re.sub(r' */D([^ ]+) ', r'\1; ', text))
    return re.sub(r' */D([^ ]+)( |$)', r'\1; ', text)


def populate_intermediate_dirs(name):
    template = pathlib.Path(f'templates/{options.vs_version}/intermediate_dir/')
    intermediates = pathlib.Path(name).parent
    while intermediates.stem != "":
        for file in template.glob("*.properties"):
            target = output_path / intermediates / file.relative_to(template)
            if not target.exists() and not options.dry_run:
                shutil.copy(file, target)
        intermediates = intermediates.parent


def write_project_references(path: pathlib.Path, module: ModuleInfo) -> List[str]:
    doc = create_project()
    project = doc.getroot()
    # for some reason these are linked with ALL libraries in the build, regardless of dependencies
    if module.data['target'].endswith('.lib'):
        write_to_file(path, doc)
        return []
    item_group = xml.SubElement(project, 'ItemGroup')
    libraries = []
    if 'libs' in module.data:
        for lib in module.data['libs'].split(" "):
            project_match = re.match(f' *(.*){options.build_flavor}.lib *', lib)
            if project_match:
                project = project_match.group(1)
                if project == module.name:
                    print(
                        f'ignoring module dependency from "{module.path}" on "{project}" (itself).  Apparently the build links this file to itself.')
                    continue
                referenced_module_path = pathlib.Path(output_path / project)
                referenced_project_file = referenced_module_path / 'Project.properties'
                rel_path = os.path.relpath(f'{str(referenced_module_path / referenced_module_path.name)}.vcxproj',
                                           str(path.parent.resolve()))
                if referenced_project_file.exists():
                    project_reference = xml.SubElement(item_group, 'ProjectReference', {'Include': rel_path})
                    project_guid = xml.SubElement(project_reference, 'Project')
                    project_xml = xml.parse(referenced_project_file).getroot()
                    referenced_guid = project_xml.find(
                        f'{{{PROJECT_NAMESPACE}}}PropertyGroup/{{{PROJECT_NAMESPACE}}}ProjectGuid')
                    project_guid.text = f'{referenced_guid.text}'
                else:
                    if not options.dry_run:
                        raise NotImplementedError(
                            f'{project} not found at {str(referenced_project_file)} and references to projects not included in solution are not supported')
            else:
                libraries.append(lib)
    other_libraries = libraries
    write_to_file(path, doc)
    return other_libraries


def build_module(name, module_data) -> ModuleInfo:
    if options.verbose:
        print(name)

    module: ModuleInfo = ModuleInfo(pathlib.Path(output_path / name), name, module_data)

    base_name = module.path.name
    if not os.path.exists(module.path):
        os.makedirs(module.path)
    if not (module.path / 'Project.properties').exists():
        write_project(module.path / 'Project.properties', name, module.path.name)
    populate_intermediate_dirs(name)

    if 'libpath' in module_data:
        module.libpaths = process_libpath(module_data['libpath'], True)

    if 'sources' in module_data:
        module.sources, module.opaque_objects = calculate_item_settings(module_data['sources'].split(" "),
                                                                        ['cflags', 'ccflags', 'cxxflags', 'cppflags'],
                                                                        process_flags)
        module.includes, module.src_includes = calculate_overrride_flags(module_data['sources'].split(" "), ['include'],
                                                                         process_include)
        module.defines, module.src_defines = calculate_overrride_flags(module_data['sources'].split(" "), ['define'],
                                                                       process_define)

        # we build out of tree, so we need to explicitly allow local includes
        if 'include' in module.includes:
            module.includes['include'] = f'$(SolutionDir)\\{name};{module.includes["include"]}'
        else:
            module.includes['include'] = f'$(SolutionDir)\\{name}'
    else:
        module.includes = {'include': ''}
        module.defines = {'define': ''}
        module.sources = {}
        module.src_includes = {}
        module.src_defines = {}

    write_module_settings(module.path / 'DebugOptions.properties', module, 'Debug|x64')
    return module


def clean_build_report(input_path):
    # reading through pipe directly into parser didn't work on Windows for unknown reason
    os.system(
        f'powershell -noprofile -Command "get-content \"{input_path}\" | Select-String -Pattern \'__BUILD_DATA_MAGIC_COOKIE__\' | %{{$_ -replace \\"__BUILD_DATA_MAGIC_COOKIE__\\",\\"\\"}}  > {options.build_path}_build_report.xml"')
    tree = xml.parse(f'{options.build_path}_build_report.xml')
    return tree.getroot()


def write_solution():
    solution_path = f'{options.source_repo_path}godot_rebuild_{options.vs_version}.sln'
    if options.dry_run:
        assert ((pathlib.Path(options.source_repo_path) / 'SConstruct').exists())
    else:
        shutil.copy(f'templates/{options.vs_version}/solution/sln.header.txt', solution_path)

    guids = {}
    if options.dry_run:
        solution = None
    else:
        solution = open(solution_path, 'a+')
        solution.write('\n')
        for path_str in list(ar.keys()) + list(link.keys()):
            path = pathlib.Path(path_str)
            project_xml = xml.parse(output_path / path / "Project.properties")
            guid = project_xml.getroot().find(f'{{{PROJECT_NAMESPACE}}}PropertyGroup/{{{PROJECT_NAMESPACE}}}ProjectGuid')
            guids[path_str] = guid.text
            style: str = "" if options.closed else "_open"
            solution.write(
                f'Project("{CXX_PROJECT_TYPE}") = "{path.name}", "{output_path / path / path.name}{style}.vcxproj", "{guid.text}"\nEndProject\n')
    middle = open(f'templates/{options.vs_version}/solution/sln.middle.txt', 'rb')
    trailer = open(f'templates/{options.vs_version}/solution/sln.trailer.txt', 'rb')
    if not options.dry_run:
        input = middle.read()
        content = input.decode("utf-8-sig")
        solution.write(content)

        for path_str in list(ar.keys()) + list(link.keys()):
            solution.write(f'		{guids[path_str]}.Debug|x64.ActiveCfg = Debug|x64\n')
            solution.write(f'		{guids[path_str]}.Debug|x64.Build.0 = Debug|x64\n')

        input = trailer.read()
        content = input.decode("utf-8-sig")
        solution.write(content)
        solution.close()
    trailer.close()
    middle.close()
    fix_line_endings_in_place(solution_path)

def resolve(reference: pathlib.Path, parent: xml.Element, location: int, child: xml.Element):
    tag: str = child.tag
    new_location: int = location
    if tag == f'{{{PROJECT_NAMESPACE}}}Import':
        relative = child.attrib['Project']
        if re.match('(\\.\\.|[A-Z]).*\\.properties', relative):
            # one of ours
            parent.remove(child)
            import_path = (reference / relative).resolve()
            if options.verbose:
                print(f'closed project render included {import_path} from {reference}')
            imported = xml.parse(str(import_path)).getroot()
            for imported_child in list(imported):
                imported.remove(imported_child)
                parent.insert(new_location, imported_child)
                # recurse into imported content with new relative path
                resolve(import_path.parent, parent, new_location, imported_child)
                new_location += 1
            return new_location
    inner_location: int = 0
    for grandchild in list(child):
        inner_location = resolve(reference, child, inner_location, grandchild)
    return new_location + 1

def render(target_path: str, source_path: str):
    reference: pathlib.Path = pathlib.Path(source_path).parent
    doc: xml.ElementTree = xml.parse(source_path)
    project: xml.Element = doc.getroot()
    location: int = 0
    for child in list(project):
        location = resolve(reference, project, location, child)
    write_to_file(target_path, doc)


def write_flat_filters(path: str, module: ModuleInfo):
    doc = create_project()
    project = doc.getroot()
    filter_item_group = xml.SubElement(project, 'ItemGroup')
    solution_root = pathlib.Path(os.path.relpath(options.source_repo_path, str(pathlib.Path(path).parent)))
    SOURCE_FILES = 'Source Files'
    HEADER_FILES = 'Header Files'
    OBJECT_FILES = 'Object Files from SCons Build'

    write_filter_decl(filter_item_group, SOURCE_FILES, 'cpp;c;cc;cxx;c++;cppm;ixx;def;odl;idl;hpj;bat;asm;asmx')
    item_group = xml.SubElement(project, 'ItemGroup')
    for compile_path in module.sources.keys():
        clcompile = xml.SubElement(item_group, 'ClCompile')
        clcompile.set('Include', str(solution_root / compile_path))
        filter = xml.SubElement(clcompile, 'Filter')
        filter.text = SOURCE_FILES

    write_filter_decl(filter_item_group, HEADER_FILES, 'h;hh;hpp;hxx;h++;hm;inl;inc;ipp;xsd')
    item_group = xml.SubElement(project, 'ItemGroup')
    for compile_path in module.headers:
        clinclude = xml.SubElement(item_group, 'ClInclude')
        clinclude.set('Include', str(solution_root / compile_path))
        filter = xml.SubElement(clinclude, 'Filter')
        filter.text = HEADER_FILES

    if module.opaque_objects and len(module.opaque_objects) > 0:
        write_filter_decl(filter_item_group, OBJECT_FILES, 'obj')
        item_group = xml.SubElement(project, 'ItemGroup')
        for obj_path in module.opaque_objects:
            object = xml.SubElement(item_group, 'Object')
            object.set('Include', str(solution_root / obj_path))
            filter = xml.SubElement(object, 'Filter')
            filter.text = OBJECT_FILES

    write_to_file(path, doc)


def write_file_system_filters(path: str, module: ModuleInfo):
    doc = create_project()
    project = doc.getroot()
    filter_item_group = xml.SubElement(project, 'ItemGroup')
    solution_root = pathlib.Path(os.path.relpath(options.source_repo_path, str(pathlib.Path(path).parent)))
    OBJECT_FILES = 'Object Files from SCons Build'

    filters = {}

    item_group = xml.SubElement(project, 'ItemGroup')
    for compile_path in module.sources.keys():
        clcompile = xml.SubElement(item_group, 'ClCompile')
        clcompile.set('Include', str(solution_root / compile_path))
        filter_path = pathlib.Path(compile_path).parent
        walk = filter_path
        while len(walk.parts) > 0:
            if walk in filters:
                break
            filters[walk] = walk
            write_filter_decl(filter_item_group, str(walk), '')
            walk = walk.parent
        filter = xml.SubElement(clcompile, 'Filter')
        filter.text = str(filter_path)

    item_group = xml.SubElement(project, 'ItemGroup')
    for compile_path in module.headers:
        clinclude = xml.SubElement(item_group, 'ClInclude')
        clinclude.set('Include', str(solution_root / compile_path))
        filter_path = pathlib.Path(compile_path).parent
        walk = filter_path
        while len(walk.parts) > 0:
            if walk in filters:
                break
            filters[walk] = walk
            write_filter_decl(filter_item_group, str(walk), '')
            walk = walk.parent
        filter = xml.SubElement(clinclude, 'Filter')
        filter.text = str(filter_path)

    if module.opaque_objects and len(module.opaque_objects) > 0:
        write_filter_decl(filter_item_group, OBJECT_FILES, 'obj')
        item_group = xml.SubElement(project, 'ItemGroup')
        for obj_path in module.opaque_objects:
            object = xml.SubElement(item_group, 'Object')
            object.set('Include', str(solution_root / obj_path))
            filter = xml.SubElement(object, 'Filter')
            filter.text = OBJECT_FILES

    write_filter_decl(filter_item_group, 'Lost and Found', 'cpp;c;cc;cxx;c++;cppm;ixx;def;odl;idl;hpj;bat;asm;asmx;h;hh;hpp;hxx;h++;hm;inl;inc;ipp;xsd')
    write_to_file(path, doc)


def write_filter_decl(item_group, filter_name, extensions_text):
    filter = xml.SubElement(item_group, 'Filter', {'Include': filter_name})
    unique_identifier = xml.SubElement(filter, 'UniqueIdentifer')
    unique_identifier.text = f'{{{str(uuid.uuid4()).upper()}}}'
    extensions = xml.SubElement(filter, 'Extensions')
    extensions.text = extensions_text

# XXX this is gross, we should know this from template tree somehow? put markers in the template XML?
def is_module_path(module_name) -> bool:
    if module_name.startswith('modules\\'):
        return True
    if module_name.startswith('platform\\'):
        return True
    return False

def main():
    if not options.dirty:
        recreate_build_tree()

    for child in clean_build_report(options.build_report_path):
        data = {}
        for element in child:
            if element.text:
                # remove SCons magic parentheses
                data[element.tag] = re.sub(r' +\$\)($| +)|(^| +)\$\( +', ' ', element.text)
        match child.tag:
            case "cc":
                cc[child.find("target").text] = data
                pass
            case "cxx":
                cxx[child.find("target").text] = data
                pass
            case "ar":
                data.pop('libpath', None)
                data.pop('linkflags', None)
                data.pop('libs', None)
                ar[get_project_basename(child)] = data
            case "link":
                link[get_project_basename(child)] = data
            case _:
                raise NotImplementedError(f'unsupported build report tag {child.tag}')

    # XXX merge modules

    for name, module_data in ar.items():
        module = build_module(name, module_data)
        modules[name] = module
        template_path = f'templates/{options.vs_version}/static_library/_static_library_.vcxproj'
        if not options.dry_run:
            shutil.copy(template_path, module.path / f'{module.path.name}_open.vcxproj')

    for name, module_data in link.items():
        module = build_module(name, module_data)
        modules[name] = module
        if module.data['target'].endswith(".exe") and not options.dry_run:
            shutil.copy(f'templates/{options.vs_version}/executable/_executable_.vcxproj',
                        module.path / f'{module.path.name}_open.vcxproj')

    # second pass: sort headers to modules
    module_list: list = list(modules.keys())
    prefix_list: list = [str(pathlib.Path(key).parent if not is_module_path(key) else key) for key in module_list]

    # XXX this is gross, we should know the difference between paths and module names
    prefix_list = [key.replace('\\module_', '\\') for key in prefix_list]

    # remember mapping to modules, because we are now putting them in a different order
    module_prefix_index = {}
    for index in range(0, len(prefix_list)-1):
        module_prefix_index[prefix_list[index]] = modules[module_list[index]]

    # sort for binary searches below
    prefix_list.sort()

    for header_long_path in pathlib.Path(options.source_repo_path).glob('**/*.h'):
        header_path = header_long_path.relative_to(options.source_repo_path)
        header_str = str(header_path)
        search_str = str(header_path.parent)
        index = bisect.bisect_right(prefix_list, search_str)
        if index >= len(prefix_list) or index < 1:
            last = len(prefix_list) - 1
            if index > 0 and search_str.startswith(prefix_list[last]):
                # fell off the end but has valid prefix
                module_prefix_index[prefix_list[last]].headers.append(header_str)
                continue
            if header_str.startswith('thirdparty\\'):
                # ignore these not being assigned, since that is currently normal
                continue
            if header_str.startswith('tests\\'):
                # TODO: implement tests
                # ignore these not being assigned, since that is currently normal
                continue
            print(f'header not assigned to any module: {header_str}')
            continue
        module_prefix_index[prefix_list[index-1]].headers.append(header_str)

    # third pass: write sources, resolve dependencies, write solution, write filters
    for name, module in modules.items():
        write_sources(module.path / 'DebugSources.properties', module, 'Debug|x64')
        module_path = pathlib.Path(output_path / name)
        module.other_libraries = write_project_references(module_path / 'ProjectReferences.properties', module)
        write_module_libraries(module_path / 'DebugLibraries.properties', module, 'Debug|x64')
        base_path = str(module_path / module_path.name)
        if options.flat_filters:
            write_flat_filters(f'{base_path}_open.vcxproj.filters', module)
        else:
            write_file_system_filters(f'{base_path}_open.vcxproj.filters', module)
        if options.closed:
            render(f'{base_path}.vcxproj', f'{base_path}_open.vcxproj')
            shutil.copy(f'{base_path}_open.vcxproj.filters', f'{base_path}.vcxproj.filters')
    write_solution()

def get_project_basename(child):
    return child.find("target").text.split(".windows.")[0]


main()
