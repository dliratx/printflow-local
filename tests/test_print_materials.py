"""Orca may omit display colors while preserving real print material metadata."""
import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from printflow import calibration, colors


def project(**settings):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('Metadata/project_settings.config',json.dumps({
            'printer_model':'Snapmaker U1','filament_type':['PLA'],
            'filament_settings_id':['Snapmaker PLA SnapSpeed @U1'],**settings}))
    return output.getvalue()


def test_material_slot_survives_missing_or_short_color_array():
    slots=colors.project_palette(project())
    assert len(slots)==1 and slots[0]['material']=='PLA'
    assert slots[0]['profile']=='Snapmaker PLA SnapSpeed @U1' and slots[0]['color'] is None
    slots=colors.project_palette(project(filament_colour=['#ffffff'],filament_type=['PLA','PETG'],filament_settings_id=['PLA','PETG']))
    assert len(slots)==2 and slots[1]['material']=='PETG' and slots[1]['color'] is None


@pytest.fixture
def setup(monkeypatch):
    job={'id':'test','comparison_id':'comparison','status':'ready','result':{'project':'runs/test/project.3mf','plates':[{'tools_zero_based':[0]}]}}
    context={'printer_id':'u1','printer_name':'U1','tool_index':0,'material':'PLA','brand':'Snapmaker',
             'color':'#080A0D','nozzle_diameter':.4,'filament_profile':'Snapmaker PLA SnapSpeed @U1'}
    session={'id':'session','context':context,'jobs':['comparison']}
    printer={'id':'u1','connected':True,'filaments':[dict(context,slot=1,loaded=True),dict(context,slot=4,loaded=True,color='#F4C032')]}
    data={'project':project()}
    async def host(*args,**kwargs):
        assert args==('GET','/artifact')
        return SimpleNamespace(content=data['project'])
    async def status():return printer
    module=SimpleNamespace(host=host,find_job=lambda _:job,printers={'u1':SimpleNamespace(status=status)})
    monkeypatch.setattr(colors,'portal',lambda:module)
    monkeypatch.setattr(calibration,'records',{'sessions':[session],'profiles':[]})
    return job,session,printer,data


def test_calibration_uses_recorded_color_only_when_project_has_none(setup):
    job,session,printer,data=setup
    slots=asyncio.run(colors.job_slots(job))
    assert slots[0]['color']=='#080A0D' and slots[0]['color_source']=='calibration_session'
    printer['filaments'][0]['color']='#FFFFFF'
    assert asyncio.run(colors.job_slots(job))[0]['color']=='#080A0D'
    data['project']=project(filament_colour=['#E72F1D'])
    slots=asyncio.run(colors.job_slots(job))
    assert slots[0]['color']=='#E72F1D' and 'color_source' not in slots[0]
    session['jobs']=[];data['project']=project()
    slots=asyncio.run(colors.job_slots(job))
    assert slots[0]['color'] is None
    assessment=colors.assess(slots,printer,[0],{0:0})
    assert assessment['materials_match'] and not assessment['can_print']  # No silently assigned color.


def test_material_check_matches_print_context_without_starting_printer(setup):
    job,session,printer,data=setup
    class Body:
        def __init__(self,tool):self.tool=tool
        async def json(self):return {'printer_id':'u1','mapping':{'0':self.tool}}
    check=asyncio.run(colors.check_job_materials('test',Body(0)))
    assert check['can_print'] and check['required_mapping']=={'0':0}
    check=asyncio.run(colors.check_job_materials('test',Body(3)))
    assert not check['materials_match'] and not check['can_print']
    assert any('physical hotend' in e for e in check['errors'])
    printer['filaments'][0]['brand']='Changed'
    assert not asyncio.run(colors.check_job_materials('test',Body(0)))['materials_match']
    printer['filaments'][0]['brand']='Snapmaker';data['project']=project(filament_type=[''])
    assert not asyncio.run(colors.check_job_materials('test',Body(0)))['materials_match']
    assert job['status']=='ready'
