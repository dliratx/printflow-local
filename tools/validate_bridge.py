"""Exercise actual MCP stdio tools and real native slices. Never contacts a printer."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import u1_server as bridge
from make_multicolor_fixture import make_fixture

def overhang_fixture():
    lines=["solid overhang"]
    for x0,y0,z0,sx,sy,sz in [(12,0,0,6,12,20),(0,0,20,30,12,4)]:
        v=[(x+x0,y+y0,z+z0) for x,y,z in [(0,0,0),(sx,0,0),(sx,sy,0),(0,sy,0),(0,0,sz),(sx,0,sz),(sx,sy,sz),(0,sy,sz)]]
        for face in [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]:
            lines += ["facet normal 0 0 0","outer loop"]+["vertex %g %g %g"%v[i] for i in face]+["endloop","endfacet"]
    path=ROOT/"models/validation/overhang.stl"
    path.write_text("\n".join(lines+["endsolid overhang"]),encoding="ascii")

async def main():
    evidence={"binary_sha256":bridge.sha(bridge.BIN),"installed_version":"2.4.0","validation_timezone":"UTC","test_material":"Snapmaker PLA Basic @U1 factory profile; physical loaded material unknown","physical_print_tested":False,"full_spectrum_creation_tested":False}
    params=StdioServerParameters(command=str(ROOT/".venv/Scripts/python.exe"),args=[str(ROOT/"u1_server.py")],cwd=str(ROOT))
    async with stdio_client(params) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            init=await session.initialize()
            tools=await session.list_tools()
            evidence["mcp_initialize"]=init.serverInfo.model_dump()
            evidence["mcp_tool_names"]=[t.name for t in tools.tools]
            async def call(name,args={}):
                response=await session.call_tool(name,args)
                if response.isError: raise RuntimeError(str(response.content))
                value=response.structuredContent
                if value is None: value=json.loads(response.content[0].text)
                return value
            prepared=await call("u1_prepare_stl",{"model":"validation/cube.stl","filament":"Snapmaker PLA Basic @U1"})
            compared=await call("u1_compare_variants",{"project":prepared["project"],"variants":[{"name":"fine_012","changes":{"layer_height":.12,"top_surface_speed":40}},{"name":"fine_016","changes":{"layer_height":.16,"top_surface_speed":40}}]})
            for variant in compared["variants"]:
                assert variant["status"]=="ok",variant
            assert compared["variants"][0]["plates"][0]["effective_settings"]["layer_height"]=="0.12"
            assert compared["variants"][1]["plates"][0]["effective_settings"]["layer_height"]=="0.16"
            evidence["quality_comparison"]=compared
            print("MCP initialization and quality comparison passed",flush=True)
            original=ROOT/"models/validation/two-color.3mf"
            multicolor=await call("u1_slice_project",{"project":"validation/two-color.3mf","changes":{"layer_height":.16,"top_surface_speed":40}})
            assert multicolor["status"]=="ok",multicolor
            assert multicolor["plates"][0]["tools_zero_based"]==[0,1]
            assert multicolor["plates"][0]["extrusion_moves_by_feature"]["Prime tower"]>0
            with zipfile.ZipFile(original) as zi,zipfile.ZipFile(multicolor["project"]) as zo:
                for n in zi.namelist():
                    if n!="Metadata/project_settings.config": assert zi.read(n)==zo.read(n)
            evidence["multicolor_two_tools"]=multicolor
            evidence["multicolor_geometry_and_assignments_unchanged"]=True
            print("Two tools, priming and project preservation passed",flush=True)
            four_fixture=make_fixture(4)
            four=await call("u1_slice_project",{"project":"validation/four-color.3mf"})
            assert four["status"]=="ok" and four["plates"][0]["tools_zero_based"]==[0,1,2,3],four
            evidence["multicolor_four_tools"]=four
            print("All four U1 tools passed",flush=True)
            assigned=await call("u1_assign_object_filament",{"project":"validation/two-color.3mf","object_id":2,"filament_slot":1})
            reassigned=await call("u1_slice_project",{"project":assigned["project"]})
            assert reassigned["status"]=="ok" and reassigned["plates"][0]["tools_zero_based"]==[0],reassigned
            evidence["object_assignment_verified"]=True
            materials=await call("u1_set_filament_slots",{"project":"validation/two-color.3mf","filaments":["Snapmaker PLA Basic @U1","Snapmaker PLA Matte @U1"],"colors":["#FF0000","#00FF00"]})
            material_slice=await call("u1_slice_project",{"project":materials["project"]})
            assert material_slice["status"]=="ok" and material_slice["plates"][0]["tools_zero_based"]==[0,1],material_slice
            evidence["filament_slot_replacement"]=material_slice
            print("Object assignment and native filament slot edits passed",flush=True)
            overhang_fixture()
            roof=await call("u1_prepare_stl",{"model":"validation/overhang.stl","filament":"Snapmaker PLA Basic @U1"})
            supported=await call("u1_slice_project",{"project":roof["project"],"changes":{"enable_support":True,"support_type":"tree(auto)","support_top_z_distance":.24,"support_bottom_z_distance":.24,"support_interface_top_layers":3,"support_interface_spacing":.3,"support_object_xy_distance":.35,"top_surface_speed":40}})
            assert supported["status"]=="ok",supported
            settings=supported["plates"][0]["effective_settings"]
            assert settings["support_top_z_distance"]=="0.24"
            assert settings["support_interface_top_layers"]=="3"
            assert any("support" in k.lower() and v>0 for k,v in supported["plates"][0]["extrusion_moves_by_feature"].items()),supported
            evidence["tree_supports_and_effective_settings"]=supported
            print("Tree support extrusion and contact settings passed",flush=True)
    from datetime import datetime,timezone
    evidence["validated_at_utc"]=datetime.now(timezone.utc).isoformat()
    evidence["status"]="passed"
    (ROOT/"validation/bridge-results.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    print("All real MCP validation passed",flush=True)

if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not (ROOT/"validation/smoke.json").exists():
        import subprocess
        subprocess.run([sys.executable,str(ROOT/"tools/validate_installation.py")],check=True)
    if not (ROOT/"models/validation/two-color.3mf").exists(): make_fixture(2)
    anyio.run(main)
