import asyncio
import pytest
from printflow.codex import CodexClient
from printflow.common import Events,read_json

def client(monkeypatch,tmp_path):
    monkeypatch.setattr('printflow.codex.DATA',tmp_path)
    c=CodexClient(Events());c.models=[{'model':'gpt-6.1-sol','displayName':'GPT-6.1 Sol','supportedReasoningEfforts':[{'reasoningEffort':'max'},{'reasoningEffort':'high'}]}]
    return c

def test_model_preference_survives_permission_changes(monkeypatch,tmp_path):
    c=client(monkeypatch,tmp_path);c.set_model('gpt-6.1-sol','max');c.set_approval_policy('on-request')
    assert read_json(tmp_path/'codex-preferences.json',{})=={'model':'gpt-6.1-sol','reasoning_effort':'max','approval_policy':'on-request'}
    with pytest.raises(ValueError):c.set_model('unavailable','max')
    with pytest.raises(ValueError):c.set_model('gpt-6.1-sol','ultra')

def test_model_and_effort_are_explicit_on_each_new_turn(monkeypatch,tmp_path):
    c=client(monkeypatch,tmp_path);c.set_model('gpt-6.1-sol','max');c.state.update(authenticated=True,connected=True)
    calls=[]
    async def request(method,params):
        calls.append((method,params));return {'thread':{'id':'test'}} if method=='thread/start' else {}
    c.request=request
    asyncio.run(c.chat('Review settings',{}))
    assert calls[0][1]['model']=='gpt-6.1-sol'
    assert calls[-1][1]['effort']=='max' and calls[-1][1]['model']=='gpt-6.1-sol'
    assert calls[0][1]['config']['model_reasoning_effort']=='max'
