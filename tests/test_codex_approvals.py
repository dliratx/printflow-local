import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from printflow.codex import CodexClient
from printflow.codex_approvals import request_view, response_for
from printflow.common import Events


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr('printflow.codex.DATA', tmp_path)
    return CodexClient(Events())


def question(request_id='q1'):
    return {'id': request_id, 'method': 'item/tool/requestUserInput', 'params': {
        'threadId': 'thread', 'turnId': 'turn', 'itemId': 'tool',
        'questions': [{'id': 'decision', 'header': 'Permission', 'question': 'Allow this tool?',
                       'options': [{'label': 'Allow once', 'description': 'Only this request'},
                                   {'label': 'Decline', 'description': 'Do not run it'}]}]}}


def command(request_id=1):
    return {'id': request_id, 'method': 'item/commandExecution/requestApproval', 'params': {
        'threadId': 'thread', 'turnId': 'turn', 'command': 'echo test', 'cwd': 'C:/test',
        'availableDecisions': ['accept', 'acceptForSession', 'decline', {'acceptWithExecpolicyAmendment': {}}]}}


def test_one_time_command_decisions_only():
    request=command()
    assert request_view(request)['decisions']==['accept', 'decline']
    assert response_for(request, 'accept')=={'decision':'accept'}
    for decision in ['acceptForSession', {'acceptWithExecpolicyAmendment':{}}, None]:
        with pytest.raises(ValueError):response_for(request, decision)


def test_tool_questions_use_exact_answer_protocol():
    request=question()
    assert request_view(request)['kind']=='questions'
    assert response_for(request, answers={'decision':'Allow once'})=={'answers':{'decision':{'answers':['Allow once']}}}
    assert response_for(request, decision='decline')=={'answers':{'decision':{'answers':[]}}}
    for answers in [None, {}, {'decision':'accept'}, {'decision':'Allow once','extra':'value'}]:
        with pytest.raises(ValueError):response_for(request, answers=answers)
    with pytest.raises(ValueError):response_for(request, decision='accept')


def test_free_text_answers_and_secrets_are_not_approval_flags():
    request=question();request['params']['questions']=[{'id':'size','question':'Size?', 'isSecret':False}]
    assert response_for(request, answers={'size':'120 mm'})=={'answers':{'size':{'answers':['120 mm']}}}
    for value in ['', '   ', 'x'*4001, True]:
        with pytest.raises(ValueError):response_for(request, answers={'size':value})


def test_policy_is_opt_in_and_does_not_send_or_replay(client, tmp_path):
    sent=[];client.send=sent.append
    assert client.state['approval_policy']=='never'
    assert not (tmp_path/'codex-preferences.json').exists()
    client.set_approval_policy('on-request')
    assert CodexClient(Events()).state['approval_policy']=='on-request'
    assert sent==[]
    client.begin_turn('t')
    with pytest.raises(ValueError):client.set_approval_policy('never')
    client.finish_turn()
    with pytest.raises(ValueError):client.set_approval_policy({'anything':'else'})


def test_reader_preserves_pending_request_without_granting(client):
    async def scenario():
        sent=[];client.send=sent.append;client.begin_turn('turn')
        stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
        stream.feed_data((json.dumps(question())+'\n'+json.dumps(command())+'\n').encode());stream.feed_eof()
        await client.read_messages()
        assert sent==[] and len(client.state['pending_approvals'])==2
        assert client.state['progress']['phase']=='waiting'
        question_id,command_id=[v['id'] for v in client.state['pending_approvals']]
        with pytest.raises(ValueError):await client.approve(question_id,'accept')
        assert question_id in client.approvals and sent==[]
        await client.approve(question_id,answers={'decision':'Decline'})
        assert sent==[{'id':'q1','result':{'answers':{'decision':{'answers':['Decline']}}}}]
        assert client.state['progress']['phase']=='waiting'
        await client.approve(command_id,'decline')
        assert sent[-1]=={'id':1,'result':{'decision':'decline'}}
        assert client.state['pending_approvals']==[]
        assert (await client.approve(command_id,'accept'))['status']=='expired'
    asyncio.run(scenario())


def test_resolved_and_completed_requests_cannot_be_approved(client):
    async def scenario():
        sent=[];client.send=sent.append;client.begin_turn('turn')
        stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
        records=[question(), {'method':'serverRequest/resolved','params':{'requestId':'q1'}}]
        stream.feed_data(('\n'.join(map(json.dumps, records))+'\n').encode());stream.feed_eof()
        await client.read_messages()
        assert (await client.approve('q1',answers={'decision':'Allow once'}))['status']=='expired'
        client.approvals['1']=command();client.finish_turn()
        assert (await client.approve(1,'accept'))['status']=='expired'
        assert sent==[]
    asyncio.run(scenario())


def test_unsupported_permission_requests_fail_closed(client):
    async def scenario():
        sent=[];client.send=sent.append
        stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
        stream.feed_data((json.dumps({'id':2,'method':'item/permissions/requestApproval','params':{}})+'\n').encode());stream.feed_eof()
        await client.read_messages()
        assert 'error' in sent[0] and 'result' not in sent[0]
        assert client.approvals=={}
    asyncio.run(scenario())


def test_next_turn_uses_saved_policy_without_weakening_sandbox(client):
    async def scenario():
        calls=[];client.state.update(authenticated=True,connected=True,model='test-model',reasoning_effort='high')
        client.models=[{'model':'test-model','supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]
        async def request(method, params):
            calls.append((method,params));return {'thread':{'id':'thread'}} if method=='thread/start' else {}
        client.request=request;client.set_approval_policy('on-request')
        assert calls==[]
        await client.chat('Prepare a model',{})
        assert calls[0][1]['approvalPolicy']=='on-request'
        assert calls[0][1]['sandbox']=='workspace-write'
        assert calls[-1][0]=='turn/start' and calls[-1][1]['approvalPolicy']=='on-request'
    asyncio.run(scenario())


def mcp_confirmation():
    # Captured from the installed app-server in a read-only, ephemeral probe.
    return json.loads((Path(__file__).parent/'fixtures/codex-mcp-approval.json').read_text())


def test_real_mcp_confirmation_is_not_a_generic_decision():
    request=mcp_confirmation()
    assert request_view(request)['kind']=='mcp_confirmation'
    assert request_view(request)['server']=='snapmaker-u1'
    assert response_for(request,'accept')=={'action':'accept','content':{}}
    assert response_for(request,'decline')=={'action':'decline','content':None}
    assert response_for(request,'cancel')=={'action':'cancel','content':None}
    with pytest.raises(ValueError):response_for(request,'acceptForSession')


def test_real_mcp_request_waits_then_replies_once_with_action_content(client):
    async def scenario():
        sent=[];client.send=sent.append;client.begin_turn('diagnostic-turn')
        stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
        stream.feed_data((json.dumps(mcp_confirmation())+'\n').encode());stream.feed_eof()
        await client.read_messages()
        assert sent==[], 'Receiving a request must never automatically accept or reject it.'
        assert client.state['progress']['phase']=='waiting'
        assert client.state['pending_approvals'][0]['kind']=='mcp_confirmation'
        public_id=client.state['pending_approvals'][0]['id']
        assert public_id!=0
        await client.approve(public_id,'accept')
        assert sent==[{'id':0,'result':{'action':'accept','content':{}}}]
        assert client.state['pending_approvals']==[]
        assert (await client.approve(public_id,'accept'))['status']=='expired'
    asyncio.run(scenario())


def test_reused_runtime_id_never_accepts_an_old_browser_decision(client):
    async def scenario():
        sent=[];client.send=sent.append;client.begin_turn('test')
        async def receive(records):
            stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
            stream.feed_data(('\n'.join(map(json.dumps,records))+'\n').encode());stream.feed_eof()
            await client.read_messages()
        await receive([mcp_confirmation()])
        old=client.state['pending_approvals'][0]['id'];first_revision=client.state['approval_revision']
        await receive([{'method':'serverRequest/resolved','params':{'requestId':0}},mcp_confirmation()])
        new=client.state['pending_approvals'][0]['id']
        assert old!=new and client.state['approval_revision']>first_revision
        result=await client.approve(old,'accept')
        assert result['status']=='expired' and sent==[]
        assert result['pending_approvals'][0]['id']==new
        client.progress('thinking','Thinking')
        assert client.state['progress']['phase']=='waiting'
        await client.approve(new,'decline')
        assert sent==[{'id':0,'result':{'action':'decline','content':None}}]
    asyncio.run(scenario())


def test_web_and_host_routes_send_one_exact_mcp_reply_and_retire_stale_requests(client,monkeypatch):
    import httpx
    from printflow import api,host_bridge
    monkeypatch.setattr(host_bridge,'codex',client)
    async def scenario():
        sent=[];client.send=sent.append;client.begin_turn('route-test')
        stream=asyncio.StreamReader();client.proc=SimpleNamespace(stdout=stream)
        stream.feed_data((json.dumps(mcp_confirmation())+'\n').encode());stream.feed_eof()
        await client.read_messages()
        token=client.state['pending_approvals'][0]['id']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host_bridge.app),base_url='http://host.test') as host:
            async def forward(method,path,**kwargs):
                return await host.request(method,path,headers={'X-PrintFlow-Token':host_bridge.TOKEN},**kwargs)
            monkeypatch.setattr(api,'host',forward)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://web.test') as browser:
                payload={'id':token,'decision':'accept'};headers={'X-PrintFlow':'local'}
                accepted=await browser.post('/api/codex/approval',json=payload,headers=headers)
                assert accepted.status_code==200 and accepted.json()['status']=='answered'
                expired=await browser.post('/api/codex/approval',json=payload,headers=headers)
                assert expired.json()['status']=='expired' and expired.json()['pending_approvals']==[]
        assert sent==[{'id':0,'result':{'action':'accept','content':{}}}]
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,schema',[
    ('url',None),('openai/userVerification',None),('form',{'type':'object','properties':{'approve':{'type':'boolean'}}}),
    ('form',{'type':'object','properties':{},'required':['missing']}),
])
def test_mcp_authentication_and_nonempty_forms_cannot_be_accepted_as_confirmation(mode,schema):
    request=mcp_confirmation();request['params'].update(mode=mode,requestedSchema=schema)
    assert request_view(request) is None
    with pytest.raises(ValueError):response_for(request,'accept')
