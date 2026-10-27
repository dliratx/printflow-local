import asyncio
from types import SimpleNamespace
import pytest
from printflow import calibration as cal
from printflow.calibration_catalog import catalog,recipe,get_test,validate_emitted_test

class Body:
    def __init__(self,body):self.body=body
    async def json(self):return self.body

def test_catalog_separates_native_sweeps_and_varies_only_one_process_setting():
    value=catalog();assert len(value['tests'])==16
    assert len({t['id'] for t in value['tests']})==16
    for t in value['tests']:
        assert t['measures'] and t['readout'] and t['limits'] and t['sources']
        if t['mode']=='native':
            with pytest.raises(ValueError,match='native'):recipe(t['id'])
            continue
        r=recipe(t['id']);first=r['variants'][0]['changes']
        for v in r['variants'][1:]:
            assert {k for k in first.keys()|v['changes'].keys() if first.get(k)!=v['changes'].get(k)}=={r['variable']}
        assert r['supports']==(t['id']=='support_removal')
    assert 'FROM VERTICAL' in get_test('overhang')['readout']
    assert 'DIAMETRAL' in get_test('clearance')['readout']

def test_preparation_reuses_run_and_preserves_trials_and_support_recipe(monkeypatch,tmp_path):
    s={'id':'s','context':{'printer_id':'u1','tool_index':0,'filament_profile':'PLA','material':'PLA'},'jobs':[],'observations':[]}
    monkeypatch.setattr(cal,'records',{'sessions':[s],'profiles':[]});monkeypatch.setattr(cal,'store',tmp_path/'state.json');monkeypatch.setattr(cal,'preparation_locks',{})
    calls=[];jobs=[]
    async def status():return {'id':'u1','connected':True,'filaments':[{'slot':1,'loaded':True,'material':'PLA'}]}
    async def load(id):return {'id':'f','path':'calibration-assets/v1/'+id+'.stl'}
    async def prepare(request):
        b=await request.json();calls.append(b);j={'id':str(len(calls)),'status':'ready','file_id':'f','comparison_parent':True};jobs.append(j);return j
    monkeypatch.setattr(cal,'portal',lambda:SimpleNamespace(printers={'u1':SimpleNamespace(status=status)},jobs=jobs,prepare_job=prepare))
    monkeypatch.setattr(cal,'load_test_model',load)
    async def scenario():
        a=await cal.prepare_test('s','support_removal',Body({}));b=await cal.prepare_test('s','support_removal',Body({}));c=await cal.prepare_test('s','support_removal',Body({'repeat':True}))
        assert a['run']['id']==b['run']['id'] and b['reused'] and c['run']['id']!=a['run']['id']
    asyncio.run(scenario())
    assert len(calls)==2 and len(s['test_runs'])==2 and calls[0]['supports']
    assert all(v['changes']['enable_support'] for v in calls[0]['variants'])
    assert len(calls[0]['variants'])==3 and s['jobs']==['1','2']

def test_test_evidence_cannot_assess_unrelated_goals(monkeypatch,tmp_path):
    s={'id':'s','observations':[],'test_runs':[{'id':'r','test_id':'overhang'}]}
    monkeypatch.setattr(cal,'records',{'sessions':[s],'profiles':[]});monkeypatch.setattr(cal,'store',tmp_path/'state.json')
    with pytest.raises(ValueError,match='goals covered'):
        asyncio.run(cal.observation('s',Body({'stage':'fit','test_run_id':'r','notes':'Photo looks fine','criteria':{'supports':'pass'}})))
    observation=asyncio.run(cal.observation('s',Body({'stage':'fit','test_run_id':'r','notes':'55 degrees clean, 65 curls','criteria':{'bridges':'pass'}})))
    assert observation['test_id']=='overhang' and observation['source']=='provisional_analysis'
    assert cal.result_summary(s)['passed']==0


def test_support_coupon_needs_actual_support_toolpaths():
    assert not recipe('support_removal')['variants'][0]['changes']['support_on_build_plate_only']
    result={'plates':[{'extrusion_moves_by_feature':{'Outer wall':100}}]}
    with pytest.raises(ValueError,match='no support extrusion'):validate_emitted_test('support_removal',result)
    validate_emitted_test('overhang',result)
    result['plates'][0]['extrusion_moves_by_feature']['Support interface']=50
    validate_emitted_test('support_removal',result)
    with pytest.raises(ValueError,match='without supports'):validate_emitted_test('bridges',result)
