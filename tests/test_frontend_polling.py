#!/usr/bin/env python3
"""Front-end core (app/core.js): GET deadlines, polling backoff, admin outcomes and
timeouts, the operations strip, dialogs, menus and row patching cost."""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_frontend_monthly import run_node


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestFrontendPolling(unittest.TestCase):
    def test_r01_mutations_require_a_fresh_loaded_snapshot(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await flush();
          if(!element('addbtn').disabled)throw new Error('initial add button permits a mutation without data');
          const states=[{loaded:false,offline:false,stale:false},{loaded:true,offline:false,stale:true},{loaded:true,offline:true,stale:false}];
          for(const state of states){
            Object.assign(WG.state,state);
            let posts=0;
            context.fetch=()=>{posts++;return Promise.resolve(response({ok:true,committed:true}));};
            const out=await WG.admin({op:'enabled',pubkey:'pk-a',enabled:false});
            if(posts!==0||out.kind!=='failed')throw new Error('unsafe mutation sent: '+JSON.stringify(state));
          }
          await feed(snapshot({stale:true,snapshot_age:120}));
          if(!element('addbtn').disabled)throw new Error('stale add button must be disabled');
          await feed(snapshot());
          if(element('addbtn').disabled)throw new Error('fresh data must unlock add');
          let posts=0;
          context.fetch=()=>{posts++;return Promise.resolve(response({ok:true,committed:true}));};
          const out=await WG.admin({op:'enabled',pubkey:'pk-a',enabled:false});
          if(posts!==1||out.kind!=='ok')throw new Error('fresh mutation refused');
          process.exitCode=0;console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_ops_notifications_track_running_keys_for_open_forms(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          let finish;const states=[];
          WG.on('ops',()=>states.push(WG.ops.running('edit:pk-a')));
          const p=WG.ops.run({key:'edit:pk-a',label:'save',call:()=>new Promise(r=>{finish=r;})});
          if(states.join(',')!=='true')throw new Error('open forms were not told the key became busy');
          finish({kind:'busy',data:null,message:'busy'});await p;
          if(states.join(',')!=='true,false')throw new Error('open forms were not unlocked on completion');
          process.exitCode=0;console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_stale_banner_keeps_navigation_enabled_but_blocks_mutations(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot({stale:true,snapshot_age:120}));
          WG.banner.set('custom',{level:'info',text:'inspect',actions:[
            {label:'Navigate',primary:true,act:()=>{}},{label:'Mutate',live:true,act:()=>{}}
          ]});
          element('banner').querySelector('[data-act="banner-more"]').click();
          const actions=element('banner').querySelectorAll('[data-b="custom"][data-act="banner-act"]');
          if(actions.length!==2||actions[0].disabled||!actions[1].disabled)
            throw new Error('stale data must block writes, not navigation');
          process.exitCode=0;console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_r11_unknown_outcome_waits_for_a_successful_fresh_check(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot());
          await WG.ops.run({key:'change',label:'change',call:()=>Promise.resolve({kind:'unknown',message:'No answer'})});
          let respond;
          context.fetch=()=>new Promise(r=>{respond=r;});
          element('ops').querySelector('[data-act="op-check"]').click();
          runTimers(0);await flush();
          let line=element('ops').querySelector('.op-unknown');
          if(line.innerHTML.includes('State refreshed'))throw new Error('refresh was claimed before any response');
          if(!line.querySelector('[data-act="op-check"]').disabled)throw new Error('duplicate check is still enabled');
          respond(response(snapshot({stale:true,snapshot_age:120})));await flush(30);
          line=element('ops').querySelector('.op-unknown');
          if(line.innerHTML.includes('State refreshed'))throw new Error('stale response was called fresh');
          context.fetch=()=>Promise.reject(new Error('offline'));
          line.querySelector('[data-act="op-check"]').click();runTimers(0);await flush(30);
          line=element('ops').querySelector('.op-unknown');
          if(!WG.state.offline||line.innerHTML.includes('State refreshed'))throw new Error('failed refresh was called successful');
          if(!line.innerHTML.includes('Could not refresh'))throw new Error('failed check needs an honest explanation');
          context.fetch=()=>Promise.resolve(response(snapshot()));
          line.querySelector('[data-act="op-check"]').click();runTimers(0);await flush(30);
          line=element('ops').querySelector('.op-unknown');
          if(!line||!line.innerHTML.includes('State refreshed'))throw new Error('fresh check must be acknowledged while outcome stays unknown');
          process.exitCode=0;console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_ops_done_label_uses_the_actual_outcome(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await WG.ops.run({key:'moved',label:'Moving 4',done:o=>'Moved '+o.data.changed,
            call:()=>Promise.resolve({kind:'ok',data:{changed:1}})});
          const text=visibleText(element('ops').querySelector('.op-ok').innerHTML);
          if(!text.includes('Moved 1')||text.includes('o.data'))throw new Error('result label did not use server count: '+text);
          process.exitCode=0;console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_hung_status_fetch_times_out_and_next_tick_requests_again(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot());
          timers.clear();
          let calls=0;
          context.fetch=()=>{calls++;return new Promise(()=>{});};
          const first=WG._poll.tick();
          WG._poll.tick();                                  // busy: must not start a second request
          if(calls!==1)throw new Error('expected 1 request while busy, got '+calls);
          const deadline=[...timers.values()].filter(t=>t.delay===12000);
          if(deadline.length!==1)throw new Error('status request has no 12 s deadline');
          runTimers(12000);
          await first;await flush();
          if(!WG.state.offline||!WG.state.timedOut)throw new Error('timeout must mark the data as offline');
          if(!bannerText().includes('did not answer in 12 s'))throw new Error('offline plaque missing: '+bannerText());
          WG._poll.tick();
          if(calls!==2)throw new Error('next tick did not issue a new request after the deadline: '+calls);
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_backoff_grows_with_failures_and_resets_on_kick(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          timers.clear();
          context.fetch=()=>Promise.reject(new Error('offline'));
          for(let i=0;i<4;i++)await WG._poll.tick();       // 4 failures
          const d=WG._poll.nextTickDelay();
          if(d<32000||d>48000)throw new Error('expected ~40 s backoff after 4 failures, got '+d);
          if(!(WG.state.retryAt>Date.now()))throw new Error('the offline plaque needs the retry time');
          const cd=element('banner').querySelector('[data-countdown]');
          if(!cd||+cd.getAttribute('data-countdown')!==WG.state.retryAt)throw new Error('countdown must follow the latest retry');
          for(let i=0;i<6;i++)await WG._poll.tick();
          if(WG._poll.nextTickDelay()>60000*1.2)throw new Error('backoff not capped');
          WG.refresh();
          if(WG._poll.nextTickDelay()!==5000)throw new Error('kick did not reset backoff');
          if(![...timers.values()].some(t=>t.delay===0))throw new Error('kick did not schedule an immediate tick');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_hidden_tab_skips_fetch_and_rendering(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          let calls=0;context.fetch=()=>{calls++;return Promise.reject(new Error('offline'));};
          document.hidden=true;
          await WG._poll.tick();
          if(calls!==0)throw new Error('hidden tab fetched status');
          if(WG._poll.nextTickDelay()!==15000)throw new Error('hidden interval not used');
          document.hidden=false;
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_admin_timeout_follows_operation_table_and_is_unknown_not_failed(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot());
          timers.clear();
          let sent=null;
          context.fetch=(url,opts)=>{sent=opts;return new Promise(()=>{});};
          const pending=WG.admin({op:'rename',pubkey:'x',name:'y'});
          if(sent.headers['X-CSRF']!=='csrf'||sent.method!=='POST')throw new Error('admin must POST with the CSRF header');
          const delays=[...timers.values()].map(t=>t.delay);
          if(!delays.includes(160000))throw new Error('rename should wait 160 s, timers: '+delays);
          runTimers(160000);
          const r=await pending;
          if(r.kind!=='unknown'||!/may have applied/.test(r.message)||!r.message.includes('2:40'))throw new Error('timeout not reported as unknown: '+JSON.stringify(r));
          timers.clear();
          WG.admin({op:'add',name:'n'});WG.admin({op:'getconf',pubkey:'x'});WG.admin({op:'splitsave',entries:[]});
          const d2=[...timers.values()].map(t=>t.delay).sort((a,b)=>a-b).join(',');
          if(d2!=='60000,195000,210000')throw new Error('unexpected admin deadlines '+d2);
          if(WG._poll.adminTimeout('revertswitch')!==100000)throw new Error('revertswitch waits 100 s');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_admin_answers_fold_into_six_outcomes(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot());
          const cases=[
            [response({ok:true,name:'a'}),'ok'],
            [response({ok:true,warning:'target_stale'}),'warn'],
            [response({ok:false,code:'target_exhausted',target:'us'},409),'failed'],
            [response({ok:false,error:'timeout',committed:'unknown'},400),'unknown'],
            [response({ok:false,error:'busy',busy:true},400),'busy'],
            [response({ok:true,committed:true,changed:['pk1'],skipped:[{pubkey:'pk2',name:'ipad',reason:'target_unhealthy'}]}),'partial'],
            [response({ok:true,cleanup_warning:'x'}),'warn']
          ];
          for(const [resp,kind] of cases){
            context.fetch=()=>Promise.resolve(resp);
            const r=await WG.admin({op:'setexit',pubkey:'p',exit:'us'});
            if(r.kind!==kind)throw new Error('expected '+kind+', got '+JSON.stringify(r));
            if(/target_|_unhealthy|busy|timeout/.test(r.message))throw new Error('raw server code in message: '+r.message);
            if(kind==='partial'&&(r.steps.length!==2||r.steps[1].state!=='failed'))throw new Error('partial steps: '+JSON.stringify(r.steps));
            if(kind==='failed'&&!/quota/.test(r.message))throw new Error('failed needs the reason: '+r.message);
          }
          context.fetch=()=>Promise.resolve(response({error:'auth'},401));
          const r=await WG.admin({op:'rename'});
          if(r.kind!=='failed'||context.location.href!=='/login')throw new Error('401 must send to /login');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_ops_strip_blocks_repeats_shows_elapsed_and_keeps_results(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          let resolve,calls=0;
          const call=()=>{calls++;return new Promise(r=>{resolve=r;});};
          const a=WG.ops.run({key:'k1',label:'mama-pixel: extend',call}),b=WG.ops.run({key:'k1',label:'again',call});
          if(a!==b||calls!==1||!WG.ops.running('k1'))throw new Error('a running key must not start twice');
          const ops=element('ops');
          const run=ops.querySelector('.op-run');
          if(!run||!visibleText(run.innerHTML).includes('Running · 1')||!/0:0\d/.test(run.innerHTML)||/%/.test(run.innerHTML))
            throw new Error('running line must show elapsed time only: '+visibleText(run&&run.innerHTML));
          if(run.getAttribute('aria-live')!=='off')throw new Error('the ticking line must not spam screen readers');
          resolve({kind:'unknown',data:null,message:'No answer from the server.'});
          const out=await a;await flush();
          if(out.kind!=='unknown'||WG.ops.running('k1'))throw new Error('outcome not returned');
          const line=ops.querySelector('.op-unknown');
          if(!line||!line.innerHTML.includes('data-act="op-check"')||line.innerHTML.includes('op-retry'))throw new Error('unknown offers a check, never a blind retry');
          if(line.getAttribute('role')!=='alert')throw new Error('unknown outcome must be announced');
          runTimers(1000);runTimers(1000);runTimers(1000);runTimers(1000);runTimers(1000);runTimers(1000);
          if(!ops.querySelector('.op-unknown'))throw new Error('unknown must stay until «Got it»');
          line.querySelector('[data-act="op-dismiss"]').click();
          if(ops.querySelector('.op-unknown'))throw new Error('«Got it» must remove the line');
          await WG.ops.run({key:'k2',label:'x',done:'mama-pixel: extended',call:()=>Promise.resolve({kind:'ok',data:{},message:''})});
          if(!visibleText(ops.querySelector('.op-ok').innerHTML).includes('mama-pixel: extended'))throw new Error('ok text');
          const clock=vm.runInContext('Date',context),realNow=clock.now;
          clock.now=()=>realNow()+5100;                    // the fade follows wall time, not timer counts
          runTimers(1000);
          clock.now=realNow;
          if(ops.querySelector('.op-ok'))throw new Error('ok must fade after 5 s');
          let tries=0;
          await WG.ops.run({key:'k3',label:'rename',call:()=>{tries++;return Promise.resolve({kind:'busy',data:null,message:'busy'});}});
          ops.querySelector('.op-busy').querySelector('[data-act="op-retry"]').click();await flush();
          if(tries!==2)throw new Error('busy offers «Retry»');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_ops_result_survives_closed_window_and_success_unlocks_before_refresh(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          await feed(snapshot());
          const h=WG.modal.open({title:'Edit',body:'<button id="b1">x</button>'});
          let resolveAdmin,statusCalls=0;
          context.fetch=(url)=>{
            if(url==='/api/admin')return new Promise(r=>{resolveAdmin=r;});
            statusCalls++;return new Promise(()=>{});
          };
          let settled=false;
          const p=WG.ops.run({key:'e',label:'mama-pixel',call:()=>WG.admin({op:'setexpiry',pubkey:'p',expires:1})}).then(()=>{settled=true;});
          h.close();
          if(h.alive())throw new Error('closed handle must not be alive');
          resolveAdmin(response({ok:false,code:'target_exhausted'},409));
          for(let i=0;i<12;i++)await Promise.resolve();
          runTimers(0);await flush();
          if(!settled)throw new Error('the op stayed busy behind a hanging status refresh');
          if(statusCalls!==1)throw new Error('a finished op must refresh status once, got '+statusCalls);
          if(!element('ops').querySelector('.op-failed'))throw new Error('outcome lost when the window closed');
          await p;
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_modal_traps_focus_closes_on_escape_and_returns_focus(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          const trigger=element('addbtn');trigger.disabled=false;trigger.focus();
          let closed='';
          const h=WG.modal.open({title:'T',eyebrow:'E',body:'<input id="f1" autofocus><button id="f2">a</button>',
            footer:'<button id="f3">b</button>',size:'sm',onClose:r=>{closed=r;}});
          if(!h.el.getAttribute('aria-modal')||h.el.getAttribute('role')!=='dialog'||!h.el.classList.contains('dlg-sm'))throw new Error('dialog semantics');
          runTimers(0);
          if(document.activeElement.id!=='f1')throw new Error('autofocus not honoured: '+(document.activeElement&&document.activeElement.id));
          const f=WG._poll.focusables(h.el),first=f[0],last=f[f.length-1];
          last.focus();const tab=makeEvent('keydown',last,{key:'Tab',shiftKey:false});document.dispatchEvent(tab);
          if(!tab.defaultPrevented||document.activeElement!==first)throw new Error('forward Tab trap failed');
          first.focus();const back=makeEvent('keydown',first,{key:'Tab',shiftKey:true});document.dispatchEvent(back);
          if(!back.defaultPrevented||document.activeElement!==last)throw new Error('reverse Tab trap failed');
          let aborted=false;
          context.fetch=(url,opts)=>new Promise(()=>{});
          const req=h.api('/api/connections?pub=x');req.catch(e=>{aborted=e.name==='AbortError';});
          document.dispatchEvent(makeEvent('keydown',last,{key:'Escape'}));
          await flush();
          if(h.alive()||closed!=='esc'||document.activeElement!==trigger)throw new Error('Escape close/focus return failed');
          if(!aborted)throw new Error('requests of a closed window must be aborted');
          const h2=WG.modal.open({title:'Two',body:'x'});
          const x=h2.el.querySelector('[data-act="modal-close"]'),child=new FakeElement('span');x.appendChild(child);
          child.dispatchEvent(makeEvent('click',child));
          if(h2.alive())throw new Error('nested close delegation failed');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_confirm_with_type_to_confirm(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          const p=WG.confirm({title:'Delete guest-2?',body:'gone',confirmLabel:'Delete',danger:true,typeToConfirm:'guest-2'});
          const dlg=WG.modal.current().el,ok=dlg.querySelector('[data-confirm-ok]'),input=dlg.querySelector('[data-confirm-input]');
          if(!ok.disabled||!ok.classList.contains('btn-danger'))throw new Error('danger confirm must start disabled');
          input.value='guest';input.dispatchEvent(makeEvent('input',input));
          if(!ok.disabled)throw new Error('partial name must not enable');
          input.value='guest-2';input.dispatchEvent(makeEvent('input',input));
          if(ok.disabled)throw new Error('exact name enables');
          ok.click();
          if(await p!==true)throw new Error('confirm resolves true');
          const q=WG.confirm({title:'Sure?'});WG.modal.close();
          if(await q!==false)throw new Error('closing resolves false');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_menu_keyboard_and_shortcuts(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          const anchor=element('acct');anchor.focus();
          const hits=[];
          WG.menu.open(anchor,[{icon:'qr',label:'Config',key:'q',act:()=>hits.push('q')},{type:'sep'},
            {icon:'edit',label:'Edit',key:'e',act:()=>hits.push('e')},{icon:'delete',label:'Off',disabled:true,act:()=>hits.push('x')}],{title:'kirill'});
          runTimers(0);
          const menu=element('layer').querySelector('.menu');
          if(menu.getAttribute('role')!=='menu'||anchor.getAttribute('aria-expanded')!=='true')throw new Error('menu semantics');
          const items=menu.querySelectorAll('[data-mi]');
          if(document.activeElement!==items[0])throw new Error('first item focused');
          document.dispatchEvent(makeEvent('keydown',items[0],{key:'ArrowDown'}));
          if(document.activeElement!==items[1])throw new Error('ArrowDown skips separators');
          document.dispatchEvent(makeEvent('keydown',items[1],{key:'ArrowDown'}));
          if(document.activeElement!==items[0])throw new Error('disabled items are skipped and focus wraps');
          document.dispatchEvent(makeEvent('keydown',items[0],{key:'e'}));
          if(hits.join()!=='e'||element('layer').querySelector('.menu'))throw new Error('shortcut must run and close');
          if(document.activeElement!==anchor)throw new Error('focus returns to the anchor');
          WG.menu.open(anchor,[{icon:'qr',label:'Config',act:()=>hits.push('q')}]);
          document.dispatchEvent(makeEvent('keydown',anchor,{key:'Escape'}));
          if(element('layer').querySelector('.menu')||anchor.getAttribute('aria-expanded')!=='false')throw new Error('Escape closes');
          WG.menu.open(anchor,[{icon:'qr',label:'Config',act:()=>hits.push('q')}]);runTimers(0);
          document.dispatchEvent(makeEvent('keydown',document.activeElement,{key:'Tab'}));
          if(element('layer').querySelector('.menu')||document.activeElement!==anchor)throw new Error('Tab leaves the menu from its anchor');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_router_renders_registered_sections_and_replaces_placeholders(self):
        run_node(self, r"""
        process.exitCode=1;(async()=>{
          const nav=element('nav').innerHTML;
          for(const r of ['#/clients','#/exits','#/split','#/usage','#/journal'])if(!nav.includes('href="'+r+'"'))throw new Error('nav misses '+r);
          if(!nav.includes('aria-current="page"'))throw new Error('current section not marked');
          const tabs=visibleText(element('tabbar').innerHTML);
          if(tabs!=='Clients Exits Usage More')throw new Error('phone tab bar: '+tabs);
          let left=0;
          WG.router.register('usage',{title:'Usage',icon:'usage',mobileTab:true,render(el,ctx){el.innerHTML='<p class="real">real</p>';ctx.on('status',()=>{});},leave(){left++;}});
          context.location.hash='#/usage';WG.router.go('usage');
          if(!element('view').querySelector('.real'))throw new Error('stage 2 page did not replace the placeholder');
          WG.router.go('clients');
          if(left!==1||WG.router.current()!=='clients')throw new Error('leave hook not called');
          process.exitCode=0;
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_reorder_of_250_rows_uses_constant_root_queries(self):
        run_node(self, r"""
        const peers=[];
        for(let i=2;i<252;i++)peers.push({name:'c'+i,ip:'10.10.0.'+i,pubkey:'pk'+i,enabled:true,online:true,
          age:5,rx:i,tx:i,mrx:0,mtx:0,spark:[],endpoint:'',exit:'nl',expires:0});
        const root=element('rows-under-test'),s=snapshot({peers});
        WG.dashboard.renderRows(root,s,'live',peers.filter(p=>p.ip!=='10.10.0.100'));
        let qsa=0,qs=0,writes=0;
        const origAll=root.querySelectorAll.bind(root),orig=root.querySelector.bind(root);
        root.querySelectorAll=sel=>{qsa++;return origAll(sel);};
        root.querySelector=sel=>{qs++;return orig(sel);};
        const cellWrites=()=>root.children.map(r=>r.children.reduce((n,c)=>n+c.innerHTMLWrites,r.innerHTMLWrites));
        const before=cellWrites();
        WG.dashboard.renderRows(root,s,'live',peers);           // pk100 is new and must land at index 98
        if(qsa+qs>4)throw new Error('root queried '+(qsa+qs)+' times for 250 rows');
        const after=cellWrites(),order0=root.children.map(c=>c.getAttribute('data-pk'));
        order0.forEach((pk,i)=>{if(pk!=='pk100'&&after[i]!==before[i-(i>98?1:0)])writes++;});
        if(writes)throw new Error(writes+' unchanged rows were rewritten');
        const order=root.children.map(c=>c.getAttribute('data-pk'));
        if(order.length!==250||order[98]!=='pk100'||order[0]!=='pk2'||order[249]!=='pk251')
          throw new Error('wrong row order: '+order.slice(95,102));
        console.log('__OK__');
        """)


if __name__ == "__main__":
    unittest.main()
