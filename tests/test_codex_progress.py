import asyncio
import json
from types import SimpleNamespace

import pytest

from printflow.common import Events
from printflow.codex import CodexClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr('printflow.codex.DATA', tmp_path)
    return CodexClient(Events())


def test_completed_tool_returns_to_thinking_not_a_frozen_completed_label(client):
    client.begin_turn('turn-1')
    client.item_activity({'id': 'a', 'type': 'mcpToolCall', 'tool': 'design_history'})
    assert client.state['progress']['label'] == 'Reviewing saved designs'
    client.item_activity({'id': 'a', 'type': 'mcpToolCall', 'tool': 'design_history', 'status': 'completed'}, True)
    assert client.state['busy']
    assert client.state['progress']['phase'] == 'thinking'
    assert client.state['progress']['steps'][0]['status'] == 'completed'
    assert client.state['progress']['started_at']


def test_dynamic_tools_and_parallel_operations_are_visible_without_arguments(client):
    client.begin_turn('turn-1')
    client.item_activity({'id': 'a', 'type': 'dynamicToolCall', 'tool': 'exec', 'arguments': 'PRIVATE'})
    client.item_activity({'id': 'b', 'type': 'commandExecution', 'command': 'SECRET COMMAND'})
    client.item_activity({'id': 'a', 'type': 'dynamicToolCall', 'status': 'completed'}, True)
    assert client.state['progress']['phase'] == 'tool'
    assert client.state['progress']['label'] == 'Running a local command'
    history = json.dumps(client.events.history)
    assert 'PRIVATE' not in history and 'SECRET COMMAND' not in history
    # Already-published steps must not mutate when the running step completes.
    assert client.events.history[1]['data']['progress']['steps'][0]['status'] == 'running'


def test_failed_tool_is_not_misreported_as_success(client):
    client.begin_turn()
    client.item_activity({'id': 'a', 'type': 'commandExecution', 'exitCode': 1, 'status': 'completed'}, True)
    assert client.state['progress']['steps'][0]['status'] == 'failed'
    client.finish_turn('interrupted')
    assert not client.state['busy']
    assert client.state['progress']['phase'] == 'stopped'


def test_tool_rejection_keeps_finished_response_from_claiming_success(client):
    client.begin_turn()
    rejected={'id':'blocked','type':'mcpToolCall','tool':'prepare_calibration_test','status':'failed','error':{'message':'PRIVATE'}}
    client.item_activity(rejected,True);client.item_activity(rejected,True)
    # Failures must survive the twelve-entry activity display limit.
    for i in range(15):client.item_activity({'id':str(i),'type':'mcpToolCall','tool':'library_list','status':'completed'},True)
    client.finish_turn()
    assert client.state['progress']['phase']=='partial'
    assert client.state['progress']['failed_actions']==1 and not client.state['busy']
    assert 'PRIVATE' not in json.dumps(client.events.history)
    client.begin_turn();client.finish_turn()
    assert client.state['progress']['phase']=='completed'


def test_mcp_error_result_is_not_a_completed_action(client):
    client.begin_turn()
    client.item_activity({'id':'failed','type':'mcpToolCall','status':'completed','result':{'isError':True}},True)
    client.finish_turn()
    assert client.state['progress']['phase']=='partial'


def test_restart_preserves_tool_failures_without_retry(client):
    async def scenario():
        client.saved_thread='saved'
        async def request(method,params):
            assert method=='thread/turns/list'
            return {'data':[{'status':'completed','items':[{'id':'f','type':'mcpToolCall','tool':'show_model','status':'failed'}]}]}
        client.request=request
        await client.restore_last_turn();await client.restore_last_turn()
        assert client.state['progress']['phase']=='partial'
        assert client.state['progress']['failed_actions']==1
    asyncio.run(scenario())


def test_large_tool_output_does_not_swallow_completion(client):
    async def run():
        reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
        client.proc = SimpleNamespace(stdout=reader)
        records = [
            {'method': 'turn/started', 'params': {'turn': {'id': 't'}}},
            {'method': 'item/started', 'params': {'item': {'id': 'x', 'type': 'dynamicToolCall', 'tool': 'exec'}}},
            {'method': 'item/completed', 'params': {'item': {'id': 'x', 'type': 'dynamicToolCall', 'status': 'completed', 'contentItems': [{'text': 'x' * 220000}]}}},
            {'method': 'item/reasoning/textDelta', 'params': {'delta': 'PRIVATE REASONING'}},
            {'method': 'item/completed', 'params': {'item': {'id': 'm', 'type': 'agentMessage', 'text': 'Model saved.'}}},
            {'method': 'turn/completed', 'params': {'turn': {'id': 't', 'status': 'completed'}}},
        ]
        reader.feed_data(('\n'.join(json.dumps(r) for r in records) + '\n').encode())
        reader.feed_eof()
        await client.read_messages()
        assert client.messages[-1]['text'] == 'Model saved.'
        assert not client.state['busy']
        assert client.state['progress']['phase'] == 'completed'
        assert 'PRIVATE REASONING' not in json.dumps(client.events.history)
    asyncio.run(run())


def test_reader_failure_clears_busy_instead_of_hanging_forever(client):
    async def run():
        class BrokenReader:
            async def readline(self): raise ValueError('line too large')
        client.begin_turn()
        client.proc = SimpleNamespace(stdout=BrokenReader())
        await client.read_loop()
        assert not client.state['busy'] and not client.state['connected']
        assert client.state['progress']['phase'] == 'disconnected'
        assert client.state['error']
    asyncio.run(run())


def test_restart_recovers_final_message_without_sending_or_resuming(client):
    async def run():
        client.saved_thread = 'saved'
        client.messages = [{'role': 'assistant', 'text': 'Starting.'}]
        calls = []
        async def request(method, params):
            calls.append(method)
            return {'data': [{'id': 't', 'status': 'completed', 'startedAt': 1000, 'completedAt': 1060,
                             'items': [{'type': 'agentMessage', 'text': 'Starting.'},
                                       {'type': 'agentMessage', 'text': 'Model saved.'}]}]}
        client.request = request
        await client.restore_last_turn()
        await client.restore_last_turn()
        assert calls == ['thread/turns/list', 'thread/turns/list']
        assert len(client.messages) == 2
        assert client.state['progress']['phase'] == 'completed'
        assert client.state['progress']['started_at'].startswith('1970-01-01')
        assert client.state['thread_id'] is None
    asyncio.run(run())
