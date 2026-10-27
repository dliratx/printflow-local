import asyncio
import io
from types import SimpleNamespace
import pytest
from PIL import Image
import httpx
from printflow import calibration as cal,colors,api,assemblies

def run(coro):return asyncio.run(coro)
class Body:
    def __init__(self,value):self.value=value
    async def json(self):return self.value

@pytest.fixture
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(cal,'records',{'sessions':[],'profiles':[]});monkeypatch.setattr(cal,'store',tmp_path/'cal.json');monkeypatch.setattr(cal,'ROOT',tmp_path)
    s={'id':'session','name':'Test','context':{'printer_id':'u1','tool_index':0,'filament_profile':'PLA','material':'PLA','brand':'Snapmaker','color':'#000000','nozzle_diameter':.4},'observations':[],'photos':[],'jobs':[]}
    cal.records['sessions'].append(s);return s

def test_profile_needs_reported_physical_benchmark(isolated):
    b={'name':'Fine','process':{'layer_height':.12},'physically_verified':True}
    with pytest.raises(ValueError,match='physical benchmark'):run(cal.save_profile('session',Body(b)))
    run(cal.observation('session',Body({'stage':'benchmark','notes':'Photo looks clean','physically_observed':False})))
    with pytest.raises(ValueError):run(cal.save_profile('session',Body(b)))
    run(cal.observation('session',Body({'stage':'benchmark','notes':'User checked walls and measured size','physically_observed':True})))
    p=run(cal.save_profile('session',Body(b)));assert p['status']=='user_verified';assert len(p['evidence_ids'])==2
    assert p['context']==isolated['context'];assert p['context'] is not isolated['context']

def test_profile_mismatch_rejected_and_bounds_not_bypassed(isolated):
    printer={'id':'u1','connected':True,'filaments':[dict(isolated['context'],slot=1,loaded=True)]}
    p={'context':isolated['context']}
    assert cal.match_profile(p,printer,'PLA',0)
    printer['filaments'][0]['brand']='Different'
    assert not cal.match_profile(p,printer,'PLA',0)
    for values in [{'layer_height':float('nan')},{'outer_wall_speed':300},{'wall_loops':2.5},{'machine_start_gcode':0}]:
        with pytest.raises(ValueError):cal.bounded(values,cal.PROCESS)

def test_color_mapping_checks_emitted_subset_and_live_inventory():
    slots=[{'material':'PLA','color':'#FF0000'},{'material':'PLA','color':'#000000'}]
    p={'connected':True,'filaments':[{'slot':1,'material':'PLA','color':'#000000','loaded':True,'nozzle_diameter':.4},{'slot':2,'material':'PETG','color':'#FF0000','loaded':True,'nozzle_diameter':.4}]}
    check=colors.assess(slots,p,[1],{1:0});assert check['can_print']
    check=colors.assess(slots,p,[0],{0:0});assert check['materials_match'] and not check['colors_match']
    check=colors.assess(slots,p,[0],{0:1});assert not check['materials_match'] and check['colors_match']
    p['connected']=False;assert not colors.assess(slots,p,[1],{1:0})['can_print']

def test_print_requires_new_bed_confirmation_before_touching_adapter(monkeypatch):
    monkeypatch.setattr(api,'printers',{'u1':object()});monkeypatch.setattr(api,'jobs',[{'id':'j','status':'ready'}])
    with pytest.raises(ValueError,match='bed is clear'):run(api.print_job('u1',Body({'job_id':'j'})))

def test_photos_validated_and_normalized_without_metadata(isolated):
    img=Image.new('RGB',(400,300),'white');buf=io.BytesIO();img.save(buf,format='PNG')
    class Photo:
        async def read(self,n):return buf.getvalue()
    result=run(cal.photos('session',Photo()));assert result['path'].startswith('calibration/session/')
    assert (cal.ROOT/'models'/result['path']).read_bytes().startswith(b'\xff\xd8')
    buf=io.BytesIO(b'<script>invalid</script>')
    with pytest.raises(ValueError,match='Invalid photo'):run(cal.photos('session',Photo()))

def test_completed_test_waits_for_photos_without_duplicate_event(isolated,monkeypatch):
    isolated['jobs']=['parent'];seen=[]
    portal=SimpleNamespace(jobs=[{'id':'parent','status':'ready'},{'id':'child','comparison_id':'parent','printer_id':'u1'}],events=SimpleNamespace(emit=lambda *v:seen.append(v)))
    monkeypatch.setattr(cal,'portal',lambda:portal)
    for p in [{'id':'u1','state':'complete','filename':'unrelated.gcode'},{'id':'u1','state':'offline','filename':'PrintFlow_child.gcode'}]:cal.observe(p)
    assert not seen
    p={'id':'u1','state':'complete','filename':'PrintFlow_child.gcode'};cal.observe(p);cal.observe(p)
    assert len(seen)==1 and isolated['status']=='awaiting_photos'

def test_export_printer_definitions_do_not_claim_live_adapters():
    p=assemblies.validate_target({'name':'Other printer','volume':[220,220,250],'color_system':'ams','color_count':4})
    assert p['delivery']=='export_only' and p['color_system']=='ams'
    with pytest.raises(ValueError):assemblies.validate_target({'name':'Bad','volume':[float('nan'),200,200]})

def test_supports_off_explicitly_overrides_previous_project():
    assert api.finish_changes({'supports':False})['enable_support'] is False

def test_percentages_count_confirmed_checks_not_ai_guesses(isolated):
    assert cal.result_summary(isolated)['pass_rate_percent'] is None
    run(cal.observation('session',Body({'stage':'benchmark','notes':'AI image impression','criteria':{'surface':'pass','bridges':'pass'}})))
    assert cal.result_summary(isolated)['passed']==0
    run(cal.observation('session',Body({'stage':'benchmark','notes':'I checked the hull and bridge','criteria':{'surface':'pass','bridges':'fail'},'physically_observed':True})))
    result=cal.result_summary(isolated)
    assert (result['passed'],result['assessed'],result['total'])==(1,2,6)
    assert result['goals_met_percent']==17 and result['pass_rate_percent']==50 and result['coverage_percent']==33
    run(cal.observation('session',Body({'stage':'benchmark','notes':'Later AI suggestion','criteria':{'bridges':'pass'}})))
    assert cal.result_summary(isolated)['passed']==1
    with pytest.raises(ValueError,match='nominal size'):run(cal.observation('session',Body({'stage':'fit','notes':'Looks accurate','criteria':{'dimensions':'pass'}})))

def test_refinement_preserves_parent_and_does_not_inherit_verification(isolated,monkeypatch):
    run(cal.observation('session',Body({'stage':'benchmark','notes':'Physical test','physically_observed':True,'criteria':{'surface':'pass'}})))
    parent=run(cal.save_profile('session',Body({'name':'Fine','process':{'layer_height':.12,'outer_wall_speed':60},'physically_verified':True})))
    original=parent.copy();child=dict(isolated,id='next',parent_profile_id=parent['id'],observations=[],photos=[])
    cal.records['sessions'].append(child)
    revision=run(cal.save_profile('next',Body({'name':'Fine','process':{'outer_wall_speed':45}})))
    assert parent==original and revision['revision']==2 and revision['family_id']==parent['id']
    assert revision['process']=={'layer_height':.12,'outer_wall_speed':45}
    assert revision['status']=='experimental' and revision['results']['passed']==0

def test_experimental_profiles_are_testable_only_on_matching_original_benchmark(isolated):
    p=run(cal.save_profile('session',Body({'name':'Candidate','process':{'layer_height':.12}})))
    cal.validate_profile_use(p,{'calibration_session_id':'session'},{'path':'calibration-assets/3DBenchy.stl'})
    with pytest.raises(ValueError,match='physical benchmark'):cal.validate_profile_use(p,{}, {'path':'calibration-assets/3DBenchy.stl'})
    with pytest.raises(ValueError,match='physical benchmark'):cal.validate_profile_use(p,{'calibration_session_id':'session'},{'path':'library/another.stl'})

def test_guided_assistant_passes_real_context_without_starting_print(isolated,monkeypatch):
    calls=[]
    async def status():return {'id':'u1','name':'U1','connected':True,'state':'printing'}
    async def host(*args,**kw):calls.append((args,kw));return SimpleNamespace(json=lambda:{'started':True})
    portal=SimpleNamespace(printers={'u1':SimpleNamespace(status=status)},host_status={'codex':{'connected':True,'authenticated':True}},host=host)
    monkeypatch.setattr(cal,'portal',lambda:portal)
    run(cal.assistant(Body({'session_id':'session'})))
    assert calls[0][0]==('POST','/chat')
    assert calls[0][1]['json']['context']['calibration']['id']=='session'
    assert 'current clear-bed confirmation' in calls[0][1]['json']['message']
    portal.host_status['codex']['busy']=True
    with pytest.raises(ValueError,match='already working'):run(cal.assistant(Body({'session_id':'session'})))
    assert len(calls)==1


def test_assistant_receives_only_selected_test_jobs_for_review(isolated,monkeypatch):
    isolated.update(jobs=['overhang-parent','benchy-parent'],active_test_run_id='overhang-run',test_runs=[
        {'id':'overhang-run','test_id':'overhang','jobs':['overhang-parent']},
        {'id':'benchy-run','test_id':'benchy','jobs':['benchy-parent']}])
    calls=[]
    async def status():return {'id':'u1','connected':True}
    async def host(*args,**kw):calls.append(kw['json']);return SimpleNamespace(json=lambda:{'started':True})
    jobs=[{'id':'o','comparison_id':'overhang-parent','file_id':'of','status':'ready'},
          {'id':'b','comparison_id':'benchy-parent','file_id':'bf','status':'ready'}]
    monkeypatch.setattr(cal,'portal',lambda:SimpleNamespace(printers={'u1':SimpleNamespace(status=status)},jobs=jobs,
        host_status={'codex':{'connected':True,'authenticated':True}},host=host))
    run(cal.assistant(Body({'session_id':'session'})))
    assert calls[-1]['context']['selected_test']['id']=='overhang'
    assert [p['job_id'] for p in calls[-1]['context']['available_preparations']]==['o']
    assert calls[-1]['context']['available_preparations'][0]['project_link']=='/api/jobs/o/download?kind=project'
    assert 'without calling preparation again' in calls[-1]['message']
    run(cal.assistant(Body({'session_id':'session','test_id':'benchy'})))
    assert [p['job_id'] for p in calls[-1]['context']['available_preparations']]==['b']
    assert len(calls)==2


def test_calibration_print_setup_selects_existing_fine_job_and_material(isolated,monkeypatch):
    isolated['jobs']=['comparison']
    printer={'id':'u1','state':'standby','connected':True,'filaments':[dict(isolated['context'],slot=1,loaded=True)]}
    async def status():return printer
    jobs=[{'id':str(h),'status':'ready','comparison_id':'comparison','variant_name':f'Benchmark · {h} mm',
           'result':{'plates':[{'tools_zero_based':[0],'estimated_print_time':'1h','total_filament_grams':11}]}} for h in (.16,.12)]
    module=SimpleNamespace(printers={'u1':SimpleNamespace(status=status)},jobs=jobs)
    monkeypatch.setattr(cal,'portal',lambda:module)
    value=run(cal.print_setup('session'))
    assert value['recommended_job_id']=='0.12' and value['choices'][0]['mapping']=={'0':0}
    assert value['bed_clear_confirmation_required'] and all(j['status']=='ready' for j in jobs)
    printer['state']='printing'
    with pytest.raises(ValueError,match='not ready'):run(cal.print_setup('session'))
    printer['state']='standby';printer['filaments'][0]['brand']='Different'
    with pytest.raises(ValueError,match='changed'):run(cal.print_setup('session'))


def test_calibration_print_rejects_wrong_tool_before_upload(isolated):
    p={'id':'u1','filaments':[dict(isolated['context'],slot=1,loaded=True)]}
    cal.validate_print_context(isolated,p,[0],{0:0})
    with pytest.raises(ValueError,match='physical hotend'):cal.validate_print_context(isolated,p,[0],{0:1})
    p['id']='other'
    with pytest.raises(ValueError,match='selected printer'):cal.validate_print_context(isolated,p,[0],{0:0})
