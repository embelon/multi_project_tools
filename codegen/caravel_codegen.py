from typing import List, Dict, Optional
from tabulate import tabulate
import shutil
import os
import logging

def generate_openlane_files(
    projects, 
    shared_projects,
    interface_definitions: Dict[str, Dict[str, int]],
    target_user_project_wrapper_path: Optional[str],
    target_user_project_includes_path: Optional[str],
    target_caravel_includes_path: Optional[str],
    target_caravel_obstructions_path: Optional[str],
    openram,
    gl,
    config # this is getting silly now. These generators should be objects and get the config by default.
) -> None:

    ### user project wrapper ###
    user_project_wrapper_filename = "user_project_wrapper.v"

    logging.info(f"generating {user_project_wrapper_filename} locally")
    generate_openlane_user_project_wrapper(projects, interface_definitions, user_project_wrapper_filename, openram, config)

    if target_user_project_wrapper_path:
        logging.info(f"{user_project_wrapper_filename} to {target_user_project_wrapper_path}")
        shutil.move(user_project_wrapper_filename, target_user_project_wrapper_path)
    else:
        logging.info(f"leaving {user_project_wrapper_filename} here")
    
    ### user project includes ###
    ### used for blackboxing the projects for the openlane config.tcl
    user_project_includes_filename = "user_project_includes.v"

    logging.info(f"generating {user_project_includes_filename} locally")
    generate_openlane_user_project_include(projects, shared_projects, user_project_includes_filename)

    if target_user_project_includes_path:
        logging.info(f"{user_project_includes_filename} to {target_user_project_includes_path}")
        shutil.move(user_project_includes_filename, target_user_project_includes_path)
    else:
        logging.info(f"leaving {user_project_includes_filename} here")
    
    ### caravel includes ###
    ### for simulation - this needs to be altered for gate level sims
    caravel_includes_filename = "uprj_netlists.v"

    logging.info(f"generating {caravel_includes_filename} locally")
    generate_caravel_includes(projects, shared_projects, caravel_includes_filename, openram, gl)

    if target_caravel_includes_path:
        logging.info(f"{caravel_includes_filename} to {target_caravel_includes_path}")
        shutil.move(caravel_includes_filename, target_caravel_includes_path)
    else:
        logging.info(f"leaving {caravel_includes_filename} here")

    ### obstructions ###
    ### for openlane
    
    logging.info(f"generating obstructions")
    caravel_obstructions_path = "obstruction.tcl"
    generate_caravel_obstructions(config, projects, shared_projects, caravel_obstructions_path)
    if target_caravel_obstructions_path:
        logging.info(f"{caravel_obstructions_path} to {target_caravel_obstructions_path}")
        shutil.move(caravel_obstructions_path, target_caravel_obstructions_path)
    else:
        logging.info(f"leaving {caravel_obstructions_path} here")

def generate_caravel_obstructions(config, projects, shared_projects, caravel_obstructions_path):
    with open(caravel_obstructions_path, "w") as f:
        f.write('set ::env(GLB_RT_OBS)  "li1  0    0   2920    3520')
        for project in projects + shared_projects:
            if 'obstruction' in project.config:
                for layer in config['configuration']['gds']['layers']:
                    if layer in project.config['obstruction']:
                        x1, y1 = project.get_macro_pos_from_caravel()
                        x2, y2 = project.get_gds_size()
                        x2 += x1
                        y2 += y1
                        f.write(f",\n       {layer} {x1} {y1} {x2} {y2}")
        f.write('"\n') 
 
def generate_openlane_user_project_include(projects, shared_projects, outfile):
    include_snippets: List[str] = []

    headers = ["project id", "title", "author", "repo", "commit"]
    table = [headers]
    for project in projects:
        table.append([project.id, project.title, project.author, project.repo, project.commit])

    for row in tabulate(
        table, 
        headers='firstrow', 
        tablefmt="pretty",
        colalign=("left" for _ in headers)
    ).split("\n"):
        include_snippets.append(f"// {row}")

    for project in projects:
        top_module = project.get_top_module()
        top_path = os.path.join(os.path.basename(project.directory), top_module)
        include_snippets.append(f"`include \"{top_path}\" // {project.id}")

    include_snippets.append(f"// shared projects")
    for project in shared_projects:
        for path in project.get_module_source_paths(absolute=False):
            path = os.path.join(os.path.basename(project.directory), path)
            include_snippets.append('`include "%s"' % path)

    with open(outfile, "w") as f:
        f.write("\n".join(include_snippets))

def generate_caravel_includes(projects, shared_projects, outfile, openram, gl):
    with open("codegen/uprj_netlists.txt", "r") as f:
        filedata = f.read()

    gl_includes = ""
    project_includes = ""
    shared_project_includes = ""
    for project in projects:
        project_includes += ("// %s\n" % project)
        for path in project.get_module_source_paths(absolute=False):
            path = os.path.join(os.path.basename(project.directory), path)
            project_includes += ('`include "%s"\n' % path)

        gl_includes += ('`include "%s"\n' % project.config['gds']['lvs_filename'])

    for project in shared_projects:
        project_includes += ("// %s\n" % project)
        for path in project.get_module_source_paths(absolute=False):
            path = os.path.join(os.path.basename(project.directory), path)
            shared_project_includes += ('`include "%s"\n' % path)

    # GL takes too long for all of Caravel, so just use the GL instead of all the normal RTL includes
    # also, don't use GL files for shared projects yet
    if gl == True:
        gl_includes += shared_project_includes
        filedata = filedata.replace('RTL_INCLUDES', gl_includes)
    else:
        project_includes += shared_project_includes
        filedata = filedata.replace('RTL_INCLUDES', project_includes)

    with open(outfile, "w") as f:
        f.write(filedata)


def generate_openlane_user_project_wrapper(projects, interface_definitions, outfile, openram, config):
    verilog_snippets: List[str] = []

    ### generate header ###
    with open("codegen/caravel_iface_header.txt", "r") as f:
        for line in f.read().split("\n"):
            verilog_snippets.append(line)
    verilog_snippets.append("")

    ### include openram stuff ###
    if openram:
        with open("codegen/caravel_iface_openram.txt", "r") as f:
            for line in f.read().split("\n"):
                verilog_snippets.append(line)

    ### generate project includes ###

    verilog_snippets.append("    // start of user project module instantiation")
    for project in projects:
        verilog_snippets.append(
            generate_openlane_user_project_wrapper_instance(
                project.module_name,
                project.id,
                project.instance_name,
                project.interfaces,
                interface_definitions,
                config,
                openram
            )
        )
    
    ### append footer ###
    verilog_snippets.append("    // end of module instantiation")
    verilog_snippets.append("")
    verilog_snippets.append("endmodule	// user_project_wrapper")
    verilog_snippets.append("`default_nettype wire")

    with open(outfile, "w") as f:
        f.write("\n".join(verilog_snippets))

def generate_openlane_user_project_wrapper_instance(
    macro_name: str,
    macro_id: str,    
    macro_instance_name: str,
    interfaces: List[str],
    interface_defs: Dict[str, Dict[str, int]],
    config,
    openram
) -> str:
    verilog_name = macro_name
    
    verilog_snippet: List[str] = []
    verilog_snippet.append(f"    {verilog_name} {macro_instance_name}(")

    
    for macro_interface in interfaces:
        if macro_interface == "power":
            verilog_snippet.append("        `ifdef USE_POWER_PINS")

        for wire_name, width in interface_defs[macro_interface].items():
            dst_wire_name = wire_name
            if openram:
                # translate the signal names so the wb_bridge is used
                if wire_name in config['openram_support']['wb_uprj_bus']:
                    dst_wire_name = config['openram_support']['wb_uprj_bus'][wire_name]

            if wire_name == "active":
                verilog_snippet.append(f"        .{wire_name} ({dst_wire_name}[{macro_id}]),")
            elif width == 1:
                verilog_snippet.append(f"        .{wire_name} ({dst_wire_name}),")
            else:
                verilog_snippet.append(f"        .{wire_name} ({dst_wire_name}[{width - 1}:0]),")

        if macro_interface == "power":
            verilog_snippet.append("        `endif")

    # werilog likes complaining about trailing commas, remove the last one
    verilog_snippet[-1] = verilog_snippet[-1][:-1]

    verilog_snippet.append(f"    );")
    verilog_snippet.append("")

    return "\n".join(verilog_snippet)
