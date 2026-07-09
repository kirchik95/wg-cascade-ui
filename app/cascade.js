function exitOf(t,key){
 if(t&&t.exits&&t.exits[key])return t.exits[key];
 return {ok:false,wg_up:false,wg_age:-1,exit_ip:null,exit_seen:null,checked_age:-1,
  iface:key==='nl'?'wg-do':'wg-us'};
}
function exitCls(e){return e&&e.ok?'ok':(e&&e.wg_up?'warn':'bad')}
function renderAlert(t){
 const el=document.getElementById('alert');
 if(!t||t.state==='up'){el.style.display='none';el.__k='';return}
 el.style.display='flex';
 const nl=exitOf(t,'nl'),us=exitOf(t,'us');
 const key=t.state+'|'+!!nl.ok+'|'+!!us.ok;
 if(el.__k===key)return;
 el.__k=key;
 const bad=t.state==='down';
 el.className='alert '+(bad?'bad':'warn');
 const detail=bad
  ?'No fresh handshake on either exit link — client traffic fails closed.'
  :'One exit is down or unverified — clients on that path may fail.';
 el.innerHTML=ic('warn',17)+'<div><b>'+(bad?'Cascade is down':'Cascade degraded')+'</b> <span>'+detail+'</span></div>';
 applyI18n(el);
}
let _cascKey="";
function exitQuota(key){
 if(typeof trafficTotals!=='function'||typeof peersByExit!=='function')return'';
 const t=trafficTotals(peersByExit(_peers||[],key),'mrx','mtx');
 return fmtB((t.rx||0)+(t.tx||0));
}
function exitRow(label,e,tip){
 const cls=exitCls(e);
 const ip=e.exit_seen||e.exit_ip||'—';
 const age=fmtAge(e.wg_age);
 const q=exitQuota(label.toLowerCase());
 const tipFull=tip+' · '+ip;
 return '<div class="casc-exit '+cls+'" data-tip="'+esc(tipFull)+'">'
  +'<div class="casc-exit-l">'
  +'<span class="casc-exit-ic">'+ic('net',14)+'</span>'
  +'<div class="casc-exit-meta">'
  +'<div class="casc-exit-name"><b>'+label+'</b><span class="ep-dot"></span><span class="casc-exit-lbl">'+tr('exit')+'</span></div>'
  +'<div class="casc-exit-ip mono">'+esc(ip)+'</div>'
  +'</div></div>'
  +'<div class="casc-exit-r">'
  +(q?'<div class="casc-exit-q mono">'+esc(q)+' <span class="mq">/ 500 GiB</span></div>':'')
  +'<div class="casc-exit-age">'+age+'</div>'
  +'</div></div>';
}
function tlineLabel(t,nl,us){
 if(t.state==='down')return'tunnel down';
 if(t.state==='degraded'){
  if(nl.ok&&!us.ok)return'NL up · US down';
  if(!nl.ok&&us.ok)return'US up · NL down';
  return'tunnel up · no exit';
 }
 if(nl.ok&&us.ok)return'both exits up';
 if(nl.ok&&!us.ok)return'NL up · US down';
 if(!nl.ok&&us.ok)return'US up · NL down';
 return'tunnel up · no exit';
}
function cascHealth(t,nl,us){
 if(t.state==='down')return{cls:'bad',label:'Down'};
 if(t.state==='up'&&nl.ok&&us.ok)return{cls:'ok',label:'Healthy'};
 return{cls:'warn',label:'Degraded'};
}
function entryCls(t){
 if(t.state==='down')return'bad';
 if(t.state==='degraded')return'warn';
 return'ok';
}
function trunkFlow(t){
 if(t.state==='down')return'bad';
 if(t.state==='degraded')return'warn';
 return'flow ok';
}
function cascGlyph(n,cx,cy,s){
 const sc=(s||18)/24;
 return '<g class="casc-glyph" transform="translate('+(cx-12*sc).toFixed(1)+','+(cy-12*sc).toFixed(1)+') scale('+sc.toFixed(3)+')">'
  +IP[n]+'</g>';
}
function cascNode(x,y,cls,icon,name,sub,tip){
 const r=20;
 const subTxt=sub&&String(sub).length>15?String(sub).slice(0,13)+'…':sub;
 return '<g class="casc-node '+cls+'">'
  +(tip?'<title>'+esc(tip)+'</title>':'')
  +'<rect class="casc-box" x="'+(x-r)+'" y="'+(y-r)+'" width="'+(r*2)+'" height="'+(r*2)+'" rx="10"/>'
  +cascGlyph(icon,x,y,18)
  +'<text class="casc-name" x="'+x+'" y="'+(y+r+14)+'">'+esc(name)+'</text>'
  +(subTxt?'<text class="casc-sub" x="'+x+'" y="'+(y+r+26)+'">'+esc(subTxt)+'</text>':'')
  +'</g>';
}
function cascLink(d,cls){
 return '<path class="casc-link base" d="'+d+'"/><path class="casc-link pulse '+cls+'" d="'+d+'"/>';
}
function renderCascade(t,rud){
 const nl=exitOf(t,'nl'),us=exitOf(t,'us');
 const cls={up:'ok',degraded:'warn',down:'bad'}[t.state];
 const nlCls=exitCls(nl),usCls=exitCls(us);
 const entCls=entryCls(t),trunk=trunkFlow(t);
 const nlFlow=nl.ok?'flow ok':nlCls, usFlow=us.ok?'flow ok':usCls;
 const nlIP=nl.exit_seen||nl.exit_ip||'—';
 const usIP=us.exit_seen||us.exit_ip||'—';
 const nlSub=nl.wg_age>=0?fmtAge(nl.wg_age):nlIP;
 const usSub=us.wg_age>=0?fmtAge(us.wg_age):usIP;
 const health=cascHealth(t,nl,us);
 const entryTip=t.entry_ip?('Entry node · Russia · '+t.entry_ip):'Entry node · Russia · 203.0.113.10';
 const nlQ=exitQuota('nl'),usQ=exitQuota('us');
 const key=[t.state,nlCls,usCls,entCls,trunk,nlIP,usIP,nlSub,usSub,nlQ,usQ,rud?1:0,health.label,entryTip,LANG].join('|');
 if(key!==_cascKey){
  _cascKey=key;
  const youTip=tr('Your devices connect to the entry node');
  const nlTip=tr('Exit node · Amsterdam, NL')+' · '+nlIP;
  const usTip=tr('Exit node · United States')+' · '+usIP;
  const entryTipTr=tr(entryTip);
  const rudBadge=rud?'<span class="casc-rud" data-tip="RU traffic bypasses the cascade and exits directly via VDSina (RU IP)">'+ic('branch')+tr('RU → direct')+'</span>':'';
  const head='<div class="casc-head">'
   +'<div class="casc-title">'+tr('Cascade topology')+'</div>'
   +'<div class="casc-badges">'+rudBadge
   +'<span class="casc-health '+health.cls+'"><span class="ep-dot"></span>'+tr(health.label)+'</span>'
   +'</div></div>';
  /* denser schematic: You ──▶ VDSina ──┬──▶ NL / └──▶ US */
  const y0=58,xYou=44,xEnt=168,xFork=236,xEx=380,yNl=28,yUs=88;
  const dTrunk='M '+(xYou+22)+' '+y0+' H '+(xEnt-22);
  const dStem='M '+(xEnt+22)+' '+y0+' H '+xFork;
  const dNl='M '+xFork+' '+y0+' V '+yNl+' H '+(xEx-22);
  const dUs='M '+xFork+' '+y0+' V '+yUs+' H '+(xEx-22);
  const el=document.getElementById('cascade');
  el.innerHTML=head
   +'<svg class="casc-svg" viewBox="0 0 440 130" role="img" aria-label="'+esc(tr('Cascade topology'))+'">'
  +'<g class="casc-wires" fill="none" stroke-linecap="round" stroke-linejoin="round">'
  +cascLink(dTrunk,trunk)
  +cascLink(dStem,trunk)
  +cascLink(dNl,nlFlow)
  +cascLink(dUs,usFlow)
  +'</g>'
  +cascNode(xYou,y0,'live','d',tr('You'),tr('devices'),youTip)
  +cascNode(xEnt,y0,entCls,'srv','VDSina',tr('entry · RU'),entryTipTr)
  +cascNode(xEx,yNl,nlCls,'net','NL',nlSub,nlTip)
  +cascNode(xEx,yUs,usCls,'net','US',usSub,usTip)
  +'</svg>'
  +'<div class="casc-exits">'
  +'<div class="casc-exits-st st '+cls+'">● '+tr(tlineLabel(t,nl,us))+'</div>'
  +exitRow('NL',nl,tr('Exit node · Amsterdam, NL'))
  +exitRow('US',us,tr('Exit node · United States'))
  +'</div>';
  applyI18n(el);
 }
}
