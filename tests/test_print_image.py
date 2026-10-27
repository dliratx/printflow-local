import pytest
from PIL import Image
from printflow import print_image

def gcode(tmp_path,text):
    p=tmp_path/'plate.gcode';p.write_text(text);return p

def test_image_uses_extrusion_features_not_travel(tmp_path,monkeypatch):
    monkeypatch.setattr(print_image,'DATA',tmp_path)
    p=gcode(tmp_path,'G90\nM83\n; filament_colour = #FFFFFF\n; layer_height = 0.12\nEXCLUDE_OBJECT_DEFINE NAME=part_1\n; FEATURE: Outer wall\nG0 X20 Y20 Z0.2\nG1 X30 E1\nG0 Y30\n; FEATURE: Support\nG1 X40 E1\n;TYPE:Brim\nG1 X50 E1\n; FEATURE: Prime tower\nG1 X60 E1\n')
    info={};s=list(print_image.segments(p,info))
    assert [x[2] for x in s]==['model','support','brim','tower']
    assert info['objects']=={'part_1'}
    output=print_image.render(p)
    assert Image.open(output).size==(1600,1040)
    assert print_image.render(p)==output

def test_absolute_and_relative_extrusion_and_retraction(tmp_path):
    p=gcode(tmp_path,'G90\nM82\n;TYPE:External perimeter\nG1 X10 E1\nG1 X20 E0\nG92 E0\nG1 X30 E1\nM83\nG91\nG1 X5 E0.2\n')
    s=list(print_image.segments(p,{}))
    assert len(s)==3 and s[-1][1][0]==35

def test_arcs_are_expanded_not_drawn_as_endpoint_chords(tmp_path):
    p=gcode(tmp_path,'M83\n;TYPE:Outer wall\nG0 X10 Y0\nG3 X0 Y10 I-10 J0 E1\n')
    s=list(print_image.segments(p,{}))
    assert len(s)>20 and s[0][0][0]==10
    assert s[-1][1][:2]==pytest.approx([0,10])

def test_unsupported_arc_is_reported_honestly(tmp_path):
    p=gcode(tmp_path,'M83\n;TYPE:Outer wall\nG2 X10 Y10 R5 E1\n')
    with pytest.raises(ValueError,match='native Orca'):list(print_image.segments(p,{}))

def test_footer_palette_is_used_for_the_first_extrusion(tmp_path,monkeypatch):
    monkeypatch.setattr(print_image,'DATA',tmp_path)
    p=gcode(tmp_path,'M83\n;TYPE:Outer wall\nG0 X20 Y20\nG1 X40 E1\nT1\nG0 Y40\nG1 X20 E1\n; filament_colour = #FFFFFF;#080A0D\n')
    with Image.open(print_image.render(p)) as image:
        assert image.getpixel((145,798))==(255,255,255)
        assert image.getpixel((145,751))==(8,10,13)
