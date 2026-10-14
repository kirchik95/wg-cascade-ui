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
 const affected=+t.affected_clients||0;
 const key=t.state+'|'+!!nl.ok+'|'+!!us.ok+'|'+affected+'|'+LANG;
 if(el.__k===key)return;
 el.__k=key;
 const bad=t.state==='down';
 el.className='alert '+(bad?'bad':'warn');
 const failing=['nl','us'].filter(k=>(+exitOf(t,k).affected_clients||0)>0).map(k=>k.toUpperCase()).join(', ');
 const detail=affected
  ?'<b>'+affected+'</b> '+tr('clients on a failing exit')+(failing?' ('+esc(failing)+')':'')+'.'
  :bad
  ?tr('No fresh handshake on either exit link — client traffic fails closed.')
  :tr('One exit is down or unverified — clients on that path may fail.');
 el.innerHTML=ic('warn',17)+'<div><b>'+tr(bad?'Cascade is down':'Cascade degraded')+'</b> <span>'+detail+'</span></div>';
 applyI18n(el);
}
let _cascKey="";
function exitQuota(key){
 /* Exit usage/quota come from the server-owned policy snapshot (exit peer counters),
    not from summing clients by their current exit — moving clients must not move usage. */
 const e=typeof _exitPolicy!=='undefined'&&_exitPolicy&&_exitPolicy.exits&&_exitPolicy.exits[key];
 if(!e)return{used:'—',quota:''};
 return{used:fmtB(+e.used||0),quota:fmtB(+e.quota||0)};
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
function entryHandshake(t,nl,us){
 const ages=[nl,us].map(e=>e&&e.wg_age>=0?e.wg_age:-1).filter(a=>a>=0);
 if(!ages.length)return tr('no handshake');
 const age=Math.min.apply(null,ages);
 return fmtAge(age).replace(/\s*(ago|назад)$/,'')+' '+tr('handshake');
}
function cascNodeIc(kind,filled){
 const cls=filled?'casc-ic filled':'casc-ic';
 return '<span class="'+cls+'" aria-hidden="true">'+ic(kind,14)+'</span>';
}
function exitCard(label,key,e){
 const cls=exitCls(e);
 const ip=e.exit_seen||e.exit_ip||'—';
 const age=e.ok||e.wg_up?(e.wg_age>=0?fmtAge(e.wg_age):'—'):tr('down');
 const q=exitQuota(key);
 const tip=tr(key==='nl'?'Exit node · Amsterdam, NL':'Exit node · United States')+' · '+ip;
 return '<div class="casc-exit '+cls+'" data-tip="'+esc(tip)+'">'
  +'<div class="casc-exit-l">'
  +cascNodeIc('net',false)
  +'<div class="casc-exit-meta">'
  +'<div class="casc-exit-name"><b>'+tr(label+' exit')+'</b><span class="ep-dot"></span></div>'
  +'<div class="casc-exit-ip mono">'+esc(ip)+'</div>'
  +'</div></div>'
  +'<div class="casc-exit-r">'
  +'<div class="casc-exit-q">'+esc(q.used)+(q.quota?' <span class="mq">/ '+esc(q.quota)+'</span>':'')+'</div>'
  +'<div class="casc-exit-age">'+age+'</div>'
  +'</div></div>';
}
function renderCascade(t,rud){
 const nl=exitOf(t,'nl'),us=exitOf(t,'us');
 const nlCls=exitCls(nl),usCls=exitCls(us);
 const entCls=entryCls(t);
 const nlIP=nl.exit_seen||nl.exit_ip||'—';
 const usIP=us.exit_seen||us.exit_ip||'—';
 const health=cascHealth(t,nl,us);
 const hs=entryHandshake(t,nl,us);
 const nlQ=JSON.stringify(exitQuota('nl')),usQ=JSON.stringify(exitQuota('us'));
 const entryTip=tr('Entry node · Russia · VDSina');
 const key=[t.state,nlCls,usCls,entCls,nlIP,usIP,hs,nlQ,usQ,rud?1:0,health.label,LANG].join('|');
 if(key===_cascKey)return;
 _cascKey=key;
 const rudBadge=rud?'<span class="casc-rud" data-tip="'+esc(tr('RU traffic bypasses the cascade and exits directly via VDSina (RU IP)'))+'">'+tr('RU → direct')+'</span>':'';
 const head='<div class="casc-head">'
  +'<div class="casc-title">'+tr('Cascade topology')+'</div>'
  +'<div class="casc-badges">'+rudBadge
  +'<span class="casc-health '+health.cls+'"><span class="ep-dot"></span>'+tr(health.label)+'</span>'
  +'</div></div>';
 const you='<div class="casc-node live" data-tip="'+esc(tr('Your devices connect to the entry node'))+'">'
  +'<div class="casc-node-h">'+cascNodeIc('phone',false)+'<b>'+tr('You')+'</b></div>'
  +'<div class="casc-node-sub mono">'+tr('device')+'</div>'
  +'<div class="casc-node-sub">'+tr('wg-cl tunnel')+'</div>'
  +'</div>';
 const entry='<div class="casc-node '+entCls+'" data-tip="'+esc(entryTip)+'">'
  +'<div class="casc-node-h">'
  +'<div class="casc-node-h-l">'+cascNodeIc('srv',true)+'<b>VDSina</b></div>'
  +'<span class="ep-dot"></span>'
  +'</div>'
  +'<div class="casc-node-sub">'+tr('RU · entry node')+'</div>'
  +'<div class="casc-node-sub mono">'+esc(hs)+'</div>'
  +'</div>';
 const el=document.getElementById('cascade');
 el.innerHTML=head
  +'<div class="casc-topo" role="img" aria-label="'+esc(tr('Cascade topology'))+'">'
  +you
  +'<div class="casc-conn" aria-hidden="true"><i></i></div>'
  +entry
  +'<div class="casc-conn" aria-hidden="true"><i></i></div>'
  +'<div class="casc-exits">'
  +exitCard('NL','nl',nl)
  +exitCard('US','us',us)
  +'</div></div>';
 applyI18n(el);
}
