/* Shared native-runner pickers. No model calls, sockets, provider switching or globals. */
export function launchControls(host,{values={},options={},save,onError=()=>{},label='Agent',count=true,account=true}={}){
  let current={...values},pending=Promise.resolve(),disposed=false,lastError=null;
  const controls={};host.replaceChildren();host.style.display='flex';host.style.flexWrap='wrap';host.style.gap='6px';host.style.alignItems='center';
  function picker(key,title,choices,defaultLabel){
    const wrap=document.createElement('label'),select=document.createElement('select');
    wrap.append(title+' ',select);select.setAttribute('aria-label',label+': '+title);select.title=label+': '+title;
    const rows=new Map([...(options.provider==='claude'&&key!=='account'?[]:[['',defaultLabel]]),...choices.map(c=>typeof c==='string'?[c,c]:[c.id,c.name])]);
    if(current[key]&&!rows.has(current[key]))rows.set(current[key],current[key]);
    for(const [value,text] of rows)select.add(new Option(text,value));select.value=current[key]||'';
    select.onchange=()=>{
      const value=select.value;select.disabled=true;
      pending=pending.then(async()=>{if(disposed)return;try{
        const accepted=await save({[key]:value});if(disposed)return;
        current={...current,...(accepted||{[key]:value})};lastError=null;
      }catch(error){lastError=error;if(!disposed){select.value=current[key]||'';onError(error);}}
      finally{if(!disposed)select.disabled=false;}});
    };controls[key]=select;host.append(wrap);return select;
  }
  picker('model','Model',options.models||[],'Provider default');
  picker('effort','Effort',options.efforts||[],'Default effort');
  if(account){const control=picker('account','Account',options.accounts?.choices||[],options.accounts?.label||'Current login');
    if(options.accounts?.label&&!options.accounts.choices?.length)control.disabled=true;}
  if(count){const wrap=document.createElement('label'),input=document.createElement('input');input.type='number';input.min='1';input.max='20';input.value=current.agents||1;input.style.width='4em';input.setAttribute('aria-label',label+': Agents');wrap.append('Agents ',input);host.append(wrap);controls.agents=input;
    input.onchange=()=>{const value=Number(input.value);input.disabled=true;pending=pending.then(async()=>{if(disposed)return;try{
      if(!Number.isInteger(value)||value<1||value>20)throw Error('Choose 1–20 agents.');
      current={...current,...(await save({agents:value})||{agents:value})};lastError=null;
    }catch(error){lastError=error;if(!disposed){input.value=current.agents||1;onError(error);}}finally{if(!disposed)input.disabled=false;}});};
  }
  return {controls,flush:async()=>{let captured;do{captured=pending;await captured;}while(captured!==pending);if(lastError)throw lastError;},values:()=>({...current}),dispose:()=>{disposed=true;}};
}
