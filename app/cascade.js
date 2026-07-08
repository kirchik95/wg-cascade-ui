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
function exitPill(label,e,tip){
 const cls=exitCls(e);
 const ip=e.exit_seen||e.exit_ip||'—';
 const age=fmtAge(e.wg_age);
 return '<span class="exitpill '+cls+'" data-tip="'+esc(tip+' · '+ip)+'">'
  +'<b>'+label+'</b><span class="ep-dot"></span><span class="mono">'+esc(ip)+'</span>'
  +'<span class="ep-age">'+age+'</span></span>';
}
function cascGlyph(n,cx,cy,s){
 const sc=(s||18)/24;
 return '<g class="casc-glyph" transform="translate('+(cx-12*sc).toFixed(1)+','+(cy-12*sc).toFixed(1)+') scale('+sc.toFixed(3)+')">'
  +IP[n]+'</g>';
}
function cascNode(x,y,cls,icon,name,sub,tip){
 const r=22;
 const subTxt=sub&&String(sub).length>15?String(sub).slice(0,13)+'…':sub;
 return '<g class="casc-node '+cls+'">'
  +(tip?'<title>'+esc(tip)+'</title>':'')
  +'<rect class="casc-box" x="'+(x-r)+'" y="'+(y-r)+'" width="'+(r*2)+'" height="'+(r*2)+'" rx="11"/>'
  +cascGlyph(icon,x,y,20)
  +'<text class="casc-name" x="'+x+'" y="'+(y+r+16)+'">'+esc(name)+'</text>'
  +(subTxt?'<text class="casc-sub" x="'+x+'" y="'+(y+r+30)+'">'+esc(subTxt)+'</text>':'')
  +'</g>';
}
function cascLink(d,cls){
 return '<path class="casc-link base" d="'+d+'"/><path class="casc-link pulse '+cls+'" d="'+d+'"/>';
}
function renderCascade(t,rud){
 const nl=exitOf(t,'nl'),us=exitOf(t,'us');
 const cls={up:'ok',degraded:'warn',down:'bad'}[t.state];
 const nlCls=exitCls(nl),usCls=exitCls(us);
 const nlFlow=nl.ok?'flow ok':nlCls, usFlow=us.ok?'flow ok':usCls;
 const nlIP=nl.exit_seen||nl.exit_ip||'—';
 const usIP=us.exit_seen||us.exit_ip||'—';
 const entryTip=t.entry_ip?('Entry node · Russia · '+t.entry_ip):'Entry node · Russia · 203.0.113.10';
 const key=[t.state,nlCls,usCls,nlIP,usIP,rud?1:0,entryTip,LANG].join('|');
 if(key!==_cascKey){
  _cascKey=key;
  const youTip=tr('Your devices connect to the entry node');
  const nlTip=tr('Exit node · Amsterdam, NL')+' · '+nlIP;
  const usTip=tr('Exit node · United States')+' · '+usIP;
  const entryTipTr=tr(entryTip);
  /* viewBox: You ──▶ VDSina ──┬──▶ NL / └──▶ US */
  const y0=78,xYou=52,xEnt=198,xFork=278,xEx=448,yNl=36,yUs=120;
  const dTrunk='M '+(xYou+24)+' '+y0+' H '+(xEnt-24);
  const dStem='M '+(xEnt+24)+' '+y0+' H '+xFork;
  const dNl='M '+xFork+' '+y0+' V '+yNl+' H '+(xEx-24);
  const dUs='M '+xFork+' '+y0+' V '+yUs+' H '+(xEx-24);
  document.getElementById('cascade').innerHTML=
   '<svg class="casc-svg" viewBox="0 0 520 178" role="img" aria-label="'+esc(tr('Cascade topology'))+'">'
  +'<g class="casc-wires" fill="none" stroke-linecap="round" stroke-linejoin="round">'
  +cascLink(dTrunk,'flow ok')
  +cascLink(dStem,'flow ok')
  +cascLink(dNl,nlFlow)
  +cascLink(dUs,usFlow)
  +'</g>'
  +cascNode(xYou,y0,'live','d',tr('You'),tr('devices'),youTip)
  +cascNode(xEnt,y0,'ok','srv','VDSina',tr('entry · RU'),entryTipTr)
  +cascNode(xEx,yNl,nlCls,'net','NL',nlIP,nlTip)
  +cascNode(xEx,yUs,usCls,'net','US',usIP,usTip)
  +'</svg>';
 }
 let lbl='tunnel down';
 if(t.state==='up')lbl=(nl.ok&&us.ok)?'both exits up':(nl.ok?'NL up · US down':'US up · NL down');
 else if(t.state==='degraded')lbl='tunnel up · no exit';
 document.getElementById('tline').innerHTML='<span class="st '+cls+'">● '+tr(lbl)+'</span>'
  +(rud?'<span class="rud" data-tip="RU traffic bypasses the cascade and exits directly via VDSina (RU IP)">'+ic('branch')+tr('RU → direct')+'</span>':'')
  +exitPill('NL',nl,'Exit node · Amsterdam, NL')
  +exitPill('US',us,'Exit node · United States');
}
