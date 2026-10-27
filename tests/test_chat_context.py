import asyncio
import json

import pytest

from printflow.chat_context import chat_context, job_summary
from printflow import api, portal_mcp


def test_context_preserves_selected_jobs_inventory_and_output_but_not_large_geometry():
    output={'status':'ok','project':'copy.3mf','plates':[{'gcode':'plate.gcode',
        'tools_zero_based':[0,2],'total_filament_grams':42,'effective_settings':{'large':'x'*20000}}]}
    jobs=[{'id':'selected-job','file_id':'selected','status':'ready','result':output}]
    jobs += [{'id':str(i),'file_id':'other','status':'ready','inspection':{'data':'x'*20000}} for i in range(5)]
    file={'id':'selected','name':'Model.3mf','preview':{'triangles':['x'*20000],'triangle_count':2000000}}
    printer={'id':'u1','updated_at':'fresh','state':'standby','filaments':[{'material':'PLA','color':'#000000'}],'raw':'x'*20000}
    result=chat_context([printer],file,jobs,{'available':True})
    assert len(json.dumps(result))<2000
    assert result['printers'][0]['filaments']==printer['filaments']
    assert result['printers'][0]['updated_at']=='fresh'
    assert result['selected_file']['preview']['triangle_count']==2000000
    selected=next(j for j in result['recent_jobs'] if j['id']=='selected-job')
    assert selected['result']['plates'][0]['tools_zero_based']==[0,2]
    assert output['plates'][0]['effective_settings']['large']=='x'*20000
    assert '0' not in [j['id'] for j in result['recent_jobs']]


def test_long_errors_are_marked_as_summaries():
    result=job_summary({'id':'failed','error':'x'*2000,'status':'error'})
    assert result['error_truncated'] and len(result['error'])==1000


def test_direct_job_wait_returns_full_comparison_and_exits_when_ready(monkeypatch):
    async def scenario():
        parent={'id':'p','status':'running'}
        child={'id':'c','status':'ready','result':{'effective_settings':{'preserved':True}}}
        monkeypatch.setattr(api,'jobs',[parent,child])
        async def complete():
            await asyncio.sleep(.01)
            parent.update(status='ready',child_job_ids=['c'])
        task=asyncio.create_task(complete())
        result=await asyncio.wait_for(api.get_job('p',20),1)
        await task
        assert result['comparison_jobs']==[child]
        assert result['status']=='ready'
    asyncio.run(scenario())


def test_mcp_job_status_does_not_download_entire_farm(monkeypatch):
    async def fake(method,path,body=None):
        assert method=='GET' and path=='/api/jobs/job?wait_seconds=20'
        return {'id':'job','status':'running'}
    monkeypatch.setattr(portal_mcp,'api',fake)
    assert asyncio.run(portal_mcp.job_status('job',20))['id']=='job'
    with pytest.raises(ValueError):asyncio.run(portal_mcp.job_status('job',100))


def test_farm_summaries_keep_raw_diagnostics_available(monkeypatch):
    value={'printers':[{'id':'u1','state':'standby','raw':{'private':'diagnostic'}}],
        'jobs':[{'id':'j','inspection':{'geometry':'big'}}],'slicer':{},'preferences':{}}
    async def fake(*args,**kwargs):return value
    monkeypatch.setattr(portal_mcp,'api',fake)
    assert 'raw' not in asyncio.run(portal_mcp.farm_status())['printers'][0]
    assert asyncio.run(portal_mcp.farm_status(True))['printers'][0]['raw']=={'private':'diagnostic'}
