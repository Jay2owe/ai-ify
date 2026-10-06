import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest
from aiify import Agent, MessageHub
from aiify.protocol import AiifyError
from aiify.cli import build_request


def mailboxes(tmp_path):
    hub=MessageHub(tmp_path/'messages.sqlite3')
    a=hub.mailbox('analysis',label='Analysis assistant')
    b=hub.mailbox('writing',label='Writing assistant')
    a.activate();b.activate()
    return hub,a,b


def test_read_only_import_construction_and_missing_store(tmp_path):
    folder=tmp_path/'missing'
    m=MessageHub(folder/'messages.sqlite3').mailbox('test')
    assert m.peers()==[] and m.inbox()['items']==[] and m.history()['items']==[]
    assert not folder.exists()


def test_future_store_is_rejected_without_rewriting_and_context_is_frozen(tmp_path):
    import sqlite3
    hub = MessageHub(tmp_path / 'messages.sqlite3')
    a = hub.mailbox('a', metadata={'context_hash': 'original'})
    b = hub.mailbox('b')
    a.activate(); b.activate()
    sent = a.send('b', 'An attributed observation')
    hub.mailbox('a', metadata={'context_hash': 'later'}).activate()
    assert b.history()['items'][0]['sender_context'] == {'context_hash': 'original'}
    assert sent['sender_context'] == {'context_hash': 'original'}
    with sqlite3.connect(hub.path) as db:
        db.execute('PRAGMA user_version=99')
    before = hub.path.read_bytes()
    with pytest.raises(AiifyError, match='Unsupported message store version 99'):
        b.inbox()
    with pytest.raises(AiifyError, match='Unsupported message store version 99'):
        a.send('b', 'Refuse unknown storage')
    assert hub.path.read_bytes() == before


def test_mail_is_attributed_durable_threaded_and_audited(tmp_path):
    hub,a,b=mailboxes(tmp_path)
    events=[];b.activate(lambda **e:events.append(e))
    refs=[{'record_id':'synthetic-finding','revision':'exact-revision'}]
    first=a.send('writing','Use this recorded result.',references=refs,request_key='once')
    assert events[0]['message']['id']==first['id']
    assert first['sender']=='analysis' and first['sender_label']=='Analysis assistant'
    assert a.send('writing','Use this recorded result.',references=refs,request_key='once')==first
    assert len(events)==1
    with pytest.raises(AiifyError): a.send('writing','Different content',request_key='once')
    assert len(b.inbox()['items'])==1 and not b.inbox()['items'][0]['acknowledged']
    answer=b.reply(first['id'],'Recorded; I will cite the source.')
    assert answer['thread_id']==first['thread_id'] and answer['reply_to']==first['id']
    b.acknowledge([first['id']])
    assert b.inbox()['items']==[]
    b.deactivate()
    reloaded=MessageHub(hub.path).mailbox('writing')
    record=reloaded.history()['items'][0]
    assert record['text']==first['text'] and record['references']==refs
    assert record['events'][0]['actor']=='writing'
    assert reloaded.peers()[0]['connected'] is False
    json.dumps(reloaded.history(),allow_nan=False)


def test_scope_identity_validation_and_atomic_ack(tmp_path):
    hub,a,b=mailboxes(tmp_path)
    c=hub.mailbox('third');c.activate()
    message=a.send('writing','Original')
    with pytest.raises(AiifyError): c.reply(message['id'],'Spoofed reply')
    with pytest.raises(AiifyError): c.send('writing','Hijacked thread',reply_to=message['id'])
    with pytest.raises(AiifyError): a.acknowledge([message['id']])
    with pytest.raises(AiifyError): b.acknowledge([message['id'],'missing'])
    assert b.inbox()['items'][0]['events']==[]
    with pytest.raises(AiifyError): a.send('analysis','Self')
    with pytest.raises(AiifyError): a.send('missing','No recipient')
    with pytest.raises(AiifyError): a.send('writing','x'*16001)
    with pytest.raises(AiifyError): a.send('writing','Bad references',references=[float('nan')])
    with pytest.raises(AiifyError): b.inbox(limit=0)
    with pytest.raises(AiifyError): b.inbox(unread='false')
    assert MessageHub(tmp_path/'elsewhere.sqlite3').mailbox('writing').inbox()['items']==[]


def test_parallel_sends_retry_safety_pagination_and_bounded_context(tmp_path):
    hub,a,b=mailboxes(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        same=list(pool.map(lambda _:a.send('writing','One logical message',request_key='retry'),range(4)))
    assert len({x['id'] for x in same})==1
    for n in range(6):a.send('writing',str(n)+'x'*5000)
    first=b.inbox(limit=2);second=b.inbox(after=first['next_after'],limit=2)
    assert first['has_more'] and not {m['id'] for m in first['items']}&{m['id'] for m in second['items']}
    text,ids=b.context('aiify --app writer')
    assert len(ids)<7 and len(text)<20000 and 'More mail' in text


def test_bound_control_port_cannot_forge_sender(tmp_path):
    hub,a,b=mailboxes(tmp_path)
    agent=Agent('analysis-test',messaging=a,codex_accounts=None)
    async def run():
        req={**build_request(['messages','send','recipient=writing','text=Hello']), 'token':agent.port.token}
        reply=await agent.port.handle_request(req)
        assert reply['ok'] and reply['result']['sender']=='analysis'
        assert not (await agent.port.handle_request({**req,'sender':'third'}))['ok']
        desc=await agent.port.handle_request({'op':'describe','token':agent.port.token})
        assert desc['result']['levels']['messages']['automatic_replies'] is False
        assert 'messages.inbox' in desc['result']['ops']
    asyncio.run(run())


def test_messages_wait_for_next_turn_and_failed_turn_does_not_ack(tmp_path):
    hub,a,b=mailboxes(tmp_path)
    agent=Agent('writer-test',messaging=b,codex_accounts=None,limit_check_every=None,app_map=None)
    sent=[]
    class Session:
        session_id='synthetic-session'
        async def send(self,text):
            sent.append(text)
            return {'stop':'auth_required' if len(sent)==1 else 'end_turn'}
    async def ready():return Session()
    agent._ensure_session=ready
    async def run():
        await agent.start()
        try:
            message=a.send('writing','Preserve the original finding reference.')
            await asyncio.sleep(.01)
            assert not sent and not agent.busy
            await agent.send('Draft a paragraph')
            assert b.inbox()['items'][0]['id']==message['id']
            await agent.send('Retry the paragraph')
            assert all(message['text'] in s and message['id'] in s for s in sent)
            assert b.inbox()['items']==[]
            assert b.history()['items'][0]['events'][0]['kind']=='included_in_reply'
        finally:await agent.stop()
    asyncio.run(run())


def test_http_uses_bound_mailbox_and_requires_same_origin_header(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    hub,a,b=mailboxes(tmp_path)
    agent=Agent('http-test',messaging=a,codex_accounts=None)
    app=FastAPI();agent.mount(app)
    with TestClient(app) as client:
        data={'operation':'messages.send','params':{'recipient':'writing','text':'HTTP message'}}
        assert client.post('/aiify/api/messages',json=data).status_code==403
        result=client.post('/aiify/api/messages',json=data,headers={'X-Aiify':'1'}).json()
        assert result['ok'] and result['result']['sender']=='analysis'
        assert b.inbox()['items'][0]['text']=='HTTP message'
        assert not client.post('/aiify/api/messages',json={**data,'params':{**data['params'],'sender':'forged'}},headers={'X-Aiify':'1'}).json()['ok']
