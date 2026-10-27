"""Typed, one-request replies to Codex. No automatic grants or policy amendments."""
DECISIONS={'item/commandExecution/requestApproval','item/fileChange/requestApproval'}
QUESTIONS={'item/tool/requestUserInput','tool/requestUserInput'}
MCP_ELICITATION='mcpServer/elicitation/request'


def is_mcp_confirmation(message):
    params=message.get('params',{});schema=params.get('requestedSchema')
    # Codex MCP tool approvals use a zero-field form. Never pretend a filled
    # form, URL authentication or device verification is a simple confirmation.
    return (message.get('method')==MCP_ELICITATION and params.get('mode')=='form'
            and isinstance(schema,dict) and schema.get('type')=='object'
            and schema.get('properties')=={} and not schema.get('required'))


def request_view(message):
    method=message.get('method');params=message.get('params',{})
    if is_mcp_confirmation(message):
        meta=params.get('_meta') or {}
        return {'id':message['id'],'method':method,'kind':'mcp_confirmation',
                'reason':params.get('message'),'server':params.get('serverName'),
                'tool_description':meta.get('tool_description'),
                'tool_params':meta.get('tool_params'),
                'decisions':['accept','decline','cancel']}
    if method not in DECISIONS|QUESTIONS:return None
    value={'id':message['id'],'method':method,'kind':'questions' if method in QUESTIONS else 'decision'}
    if method in QUESTIONS:value['questions']=params.get('questions',[])
    else:
        value.update(reason=params.get('reason') or 'Review this action before allowing it once.',
                     command=params.get('command'),cwd=params.get('cwd'),grant_root=params.get('grantRoot'),
                     decisions=[d for d in params.get('availableDecisions') or ['accept','decline'] if d in ('accept','decline','cancel')])
    return value


def response_for(message,decision=None,answers=None):
    method=message.get('method');params=message.get('params',{})
    if is_mcp_confirmation(message):
        if decision not in ('accept','decline','cancel'):
            raise ValueError('Choose Allow once, Decline or Cancel for this tool request.')
        # No persistence metadata: this reply authorizes this request only.
        return {'action':decision,'content':{} if decision=='accept' else None}
    if method in DECISIONS:
        allowed=(request_view(message) or {}).get('decisions',[])
        if decision not in allowed:raise ValueError('Choose an available one-time decision.')
        return {'decision':decision}
    if method in QUESTIONS:
        questions=params.get('questions',[])
        if decision=='decline':return {'answers':{q['id']:{'answers':[]} for q in questions}}
        if not isinstance(answers,dict) or set(answers)!={q['id'] for q in questions}:
            raise ValueError('Answer each question before continuing.')
        result={}
        for q in questions:
            answer=answers[q['id']]
            if not isinstance(answer,str) or not answer.strip() or len(answer)>4000:
                raise ValueError('Enter a response for each question (up to 4,000 characters).')
            if q.get('options') and not q.get('isOther') and answer not in {o['label'] for o in q['options']}:
                raise ValueError('Choose one of the offered answers.')
            result[q['id']]={'answers':[answer]}
        return {'answers':result}
    raise ValueError('This request type is not supported. No approval was sent.')
