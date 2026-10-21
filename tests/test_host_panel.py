"""Host-owned task runners reuse the panel without ACP or a second server."""
from pathlib import Path
import pytest
from aiify.panel import static_asset
from aiify.web import panel_tag


def test_public_host_assets_and_tag():
    assert static_asset('panel.js').is_file()
    assert 'data-transport="host"' in panel_tag(transport='host')
    with pytest.raises(ValueError):static_asset('../agent.py')
    with pytest.raises(ValueError):panel_tag(transport='invalid')


@pytest.fixture(scope='module')
def browser():
    runtime=pytest.importorskip('playwright.sync_api')
    with runtime.sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        yield browser
        browser.close()


def test_host_panel_transport_isolation_and_errors(browser):
    page=browser.new_page()
    requests=[];errors=[]
    page.on('request',lambda r:requests.append(r.url))
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('http://host.test/**',lambda route:route.fulfill(
        content_type='text/javascript' if route.request.url.endswith('.js') else 'text/css',
        body=static_asset(route.request.url.rsplit('/',1)[-1]).read_text(encoding='utf-8')))
    page.set_content('<div id="chat" style="height:600px"></div>')
    page.evaluate('''()=>{const s=document.createElement('script');s.src='http://host.test/panel.js';
      Object.assign(s.dataset,{transport:'host',layout:'inline',target:'#chat',launcher:'none'});document.head.append(s);}''')
    page.wait_for_function('typeof window.aiify?.bindHost==="function"')
    page.evaluate('''()=>{
      window.posts=[];window.drafts=[];
      window.first=aiify.bindHost({id:'one',operations:['send','queue'],info:{ready:true,title:'Task agent',features:{queue:true}},
        request:async(op,body)=>{posts.push({op,body});return {ok:false,error:'Try again'};},onDraft:text=>drafts.push(text),
        history:[{kind:'user',text:'Question'},{kind:'text',text:'**Saved reply**'}]});
    }''')
    root=page.locator('#aiify-root')
    root.get_by_text('Saved reply',exact=True).wait_for()
    assert root.locator('.cfg').is_hidden()
    assert root.get_by_role('button',name='New chat',exact=True).is_hidden()
    editor=root.locator('textarea');editor.fill('Keep after failure');editor.press('Enter')
    root.get_by_text('Try again',exact=True).wait_for()
    assert editor.input_value()=='Keep after failure'
    page.evaluate('''()=>{window.second=aiify.bindHost({id:'two',operations:['send'],info:{ready:true},draft:'Other draft',request:async()=>({ok:true})});
      first.receive({kind:'text',text:'Wrong conversation'});}''')
    assert root.get_by_text('Wrong conversation',exact=True).count()==0
    assert editor.input_value()=='Other draft'
    editor.press('Enter');page.wait_for_function('aiify.element.shadowRoot.querySelector("textarea").value===""')
    assert page.evaluate('posts')==[{'op':'send','body':{'text':'Keep after failure'}}]
    assert not any('/ws' in url or '/api/' in url or 'bridge.js' in url for url in requests)
    assert not errors
    page.close()


def test_a_streamed_reply_draws_the_same_as_the_whole_text(browser):
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('http://host.test/**',lambda route:route.fulfill(
        content_type='text/javascript' if route.request.url.endswith('.js') else 'text/css',
        body=static_asset(route.request.url.rsplit('/',1)[-1]).read_text(encoding='utf-8')))
    page.set_content('<div id="chat" style="height:600px"></div>')
    page.evaluate('''()=>{const s=document.createElement('script');s.src='http://host.test/panel.js';
      Object.assign(s.dataset,{transport:'host',layout:'inline',target:'#chat',launcher:'none'});document.head.append(s);}''')
    page.wait_for_function('typeof window.aiify?.bindHost==="function"')
    text=('Intro with **bold** and `code`.\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n'
          '```py\nx = 1\n\nprint(x)\n```\n\n## Done\nlast *line*')
    pieces=[text[i:i+3] for i in range(0,len(text),3)]
    html=page.evaluate('''async([text,pieces])=>{
      const reply=()=>aiify.element.shadowRoot.querySelector('.msg.reply').innerHTML;
      const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const whole=aiify.bindHost({id:'w',operations:['send'],request:async()=>({ok:true}),history:[{kind:'text',text}]});
      await frame();const a=reply();whole.dispose();
      const live=aiify.bindHost({id:'s',operations:['send'],request:async()=>({ok:true})});
      for(const p of pieces)live.receive({kind:'text',text:p});
      await frame();const b=reply();live.dispose();
      const ended=aiify.bindHost({id:'e',operations:['send'],request:async()=>({ok:true})});
      for(const p of pieces)ended.receive({kind:'text',text:p});
      ended.receive({kind:'tool',id:'t',title:'run'});        // drawn before the tool card, without a frame
      return [a,b,reply()];}''',[text,pieces])
    assert html[0]==html[1]==html[2]
    for tag in ('<ul>','<table>','<pre><code>x = 1\n\nprint(x)\n</code></pre>','<h2>Done</h2>'):
        assert tag in html[1]
    assert not errors
    page.close()


def test_a_file_over_the_limit_is_refused_before_it_is_read(browser):
    page=browser.new_page()
    page.route('http://host.test/**',lambda route:route.fulfill(
        content_type='text/javascript' if route.request.url.endswith('.js') else 'text/css',
        body=static_asset(route.request.url.rsplit('/',1)[-1]).read_text(encoding='utf-8')))
    page.set_content('<div id="chat" style="height:600px"></div>')
    page.evaluate('''()=>{const s=document.createElement('script');s.src='http://host.test/panel.js';
      Object.assign(s.dataset,{transport:'host',layout:'inline',target:'#chat',launcher:'none'});document.head.append(s);}''')
    page.wait_for_function('typeof window.aiify?.bindHost==="function"')
    got=page.evaluate('''async()=>{window.sent=[];
      aiify.bindHost({id:'a',operations:['send','attach'],info:{features:{attach:true},attach_limit:2048},
        request:async(op,body)=>{sent.push(op);return {ok:true};}});
      const big=await aiify.attach(new File(['x'.repeat(4096)],'big.txt'));
      const small=await aiify.attach(new File(['x'.repeat(100)],'small.txt'));
      return {big,small,sent};}''')
    assert got['big']=={'ok':False,'code':'failed','error':'big.txt is 4 KB; the limit is 0 MB'}
    assert got['small']['ok'] and got['sent']==['attach']
    page.close()


def test_a_tool_output_box_keeps_the_latest_output(browser):
    page=browser.new_page()
    page.route('http://host.test/**',lambda route:route.fulfill(
        content_type='text/javascript' if route.request.url.endswith('.js') else 'text/css',
        body=static_asset(route.request.url.rsplit('/',1)[-1]).read_text(encoding='utf-8')))
    page.set_content('<div id="chat" style="height:600px"></div>')
    page.evaluate('''()=>{const s=document.createElement('script');s.src='http://host.test/panel.js';
      Object.assign(s.dataset,{transport:'host',layout:'inline',target:'#chat',launcher:'none'});document.head.append(s);}''')
    page.wait_for_function('typeof window.aiify?.bindHost==="function"')
    text=page.evaluate('''()=>{const h=aiify.bindHost({id:'t',operations:['send'],request:async()=>({ok:true})});
      h.receive({kind:'tool',id:'x',title:'run',detail:''});
      for(let i=0;i<60;i++)h.receive({kind:'tool_update',id:'x',detail:'line '+i+' '+'y'.repeat(500)});
      return aiify.element.shadowRoot.querySelector('details.tool pre').textContent;}''')
    assert len(text)==20001 and text.startswith('…') and text.endswith('line 59 '+'y'*500)
    page.close()
