#!/usr/bin/env python3
"""Front-end sections of stage 2C (app/pages.js): the exits scheme and its honest states,
usage forecast / day series / CSV, journal texts for every event kind, login folding,
day grouping, filters, and the routes with their loading, empty and error states.
Runs app/icons.js, core.js, dashboard.js and pages.js in node on the fake DOM of
test_frontend_monthly."""
import os
import shutil
import subprocess
import textwrap
import unittest

from test_frontend_monthly import NODE_SETUP, ROOT

PAGES_SETUP = NODE_SETUP.replace("'app/dashboard.js']", "'app/dashboard.js','app/pages.js']")

HELPERS = r"""
const P=WG.pages;
const urls=[];
/* fetch by URL prefix; a function value builds the response from the URL */
function serve(map){
  context.fetch=(url)=>{
    urls.push(String(url));
    for(const k of Object.keys(map)) if(String(url).startsWith(k)){
      const v=map[k];
      return Promise.resolve(typeof v==='function'?v(String(url)):response(v));
    }
    return Promise.reject(new Error('unexpected '+url));
  };
}
function local(y,m,d,h=12,mi=0){return Math.round(new Date(y,m-1,d,h,mi).getTime()/1000);}
/* the fake DOM keeps text on each node: collect it through the tree (sub-elements are re-rendered on their own) */
function deepText(n){return (n._textContent||'')+' '+n.children.map(deepText).join(' ');}
function viewText(){return deepText(element('view')).replace(/\s+/g,' ').trim();}
function q(sel){return element('view').querySelector(sel);}
const acts=[];
Object.assign(WG.actions,{revertSwitch:id=>acts.push(['revert',id]),exitsSettings:()=>acts.push(['exits']),
  splitSettings:()=>acts.push(['split']),showConfig:(pk,o)=>acts.push(['conf',pk,o&&o.section])});
const settle=()=>flush(40);
"""


def run_pages(test, body, lang="en", timeout=30):
    test.assertNotEqual(PAGES_SETUP, NODE_SETUP, "the node setup no longer lists dashboard.js the expected way")
    script = textwrap.dedent(PAGES_SETUP + "\n" + HELPERS + "\n" + body)
    env = dict(os.environ, WGUI_TEST_LANG=lang)
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    test.assertEqual(result.returncode, 0, result.stderr + result.stdout)
    test.assertIn("__OK__", result.stdout, "the test body did not run to the end:\n" + result.stderr)


def wrap(js):
    return "(async()=>{\n" + js + "\nconsole.log('__OK__');\n})().catch(e=>{console.error(e);process.exitCode=1;});"


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestUsageHelpers(unittest.TestCase):
    def test_month_info_and_shift_roll_over_years_and_leap_days(self):
        run_pages(self, wrap(r"""
          if(P.shiftMonth('2026-12',1)!=='2027-01'||P.shiftMonth('2026-01',-1)!=='2025-12')throw new Error('month shift');
          if(P.monthInfo('2028-02',local(2028,2,10)).days!==29)throw new Error('leap February');
          const cur=P.monthInfo('2026-10',local(2026,10,14,12));
          if(!cur.current||cur.today!==14||cur.days!==31)throw new Error('current month: '+JSON.stringify(cur));
          if(Math.abs(cur.elapsed-13.5)>0.05)throw new Error('elapsed days must count the part of today: '+cur.elapsed);
          const past=P.monthInfo('2026-09',local(2026,10,14));
          if(!past.past||past.current||past.elapsed!==30)throw new Error('past month');
          if(!P.monthInfo('2026-11',local(2026,10,14)).future)throw new Error('future month');
        """))

    def test_day_series_sums_rx_tx_per_exit_and_ignores_other_months(self):
        run_pages(self, wrap(r"""
          const info=P.monthInfo('2026-10',local(2026,10,14));
          const s=P.daySeries({nl:[{day:'2026-10-01',rx:3*GiB,tx:GiB},{day:'2026-09-30',rx:9*GiB,tx:0}],
                               us:[{day:'2026-10-01',rx:GiB,tx:0},{day:'2026-10-03',rx:2*GiB,tx:GiB}]},info);
          if(s.length!==31)throw new Error('one row per day');
          if(s[0].nl!==4*GiB||s[0].us!==GiB||!s[0].has)throw new Error('day 1: '+JSON.stringify(s[0]));
          if(s[1].has||s[2].us!==3*GiB)throw new Error('days 2-3');
          if(P.niceMax(37*GiB)!==50||P.niceMax(0)!==1||P.niceMax(260*GiB)!==500)throw new Error('nice scale');
        """))

    def test_forecast_projection_runs_out_exhausted_and_final(self):
        run_pages(self, wrap(r"""
          const info=P.monthInfo('2026-10',local(2026,10,14,12));
          const proj=P.forecast({used:96*GiB,quota:1000*GiB,info,series:[]});
          if(proj.kind!=='projection')throw new Error('NL stays under quota: '+proj.kind);
          if(Math.abs(proj.projected/GiB-96/13.5*31)>1)throw new Error('projection = average so far × days: '+proj.projected/GiB);
          const txt=P.forecastText(proj,{key:'nl',used:96*GiB,clients:17,info});
          if(!txt.includes('average over 1–Oct 14')||!txt.includes('by Oct 31 ~220 GiB'))throw new Error('method must be named: '+txt);
          const us=P.forecast({used:371*GiB,quota:500*GiB,info,series:[]});
          if(us.kind!=='runs-out'||us.day!==19)throw new Error('US runs out on the 19th: '+JSON.stringify(us));
          const idle=P.forecastText(us,{key:'us',used:371*GiB,clients:0,info});
          if(!idle.includes('would run out ~Oct 19')||!idle.includes('now US has 0 clients'))throw new Error('idle exit text: '+idle);
          const busy=P.forecastText(us,{key:'us',used:371*GiB,clients:3,info});
          if(!busy.includes('runs out ~Oct 19')||busy.includes('would'))throw new Error('busy exit text: '+busy);
          const series=[200,200,150].map(g=>g*GiB);
          const ex=P.forecast({used:550*GiB,quota:500*GiB,info,series});
          if(ex.kind!=='exhausted'||ex.day!==3)throw new Error('exhausted on day 3: '+JSON.stringify(ex));
          if(P.forecastText(ex,{key:'us',info})!=='quota used up on Oct 3')throw new Error('exhausted text');
          const past=P.monthInfo('2026-09',local(2026,10,14));
          const fin=P.forecast({used:300*GiB,quota:1000*GiB,info:past,series:[]});
          if(fin.kind!=='final'||Math.round(fin.rate/GiB)!==10)throw new Error('past month is a total');
          if(!P.forecastText(fin,{key:'nl',info:past}).startsWith('month total · 10 GiB/day'))throw new Error('final text');
          if(P.forecast({used:0,quota:500*GiB,info:P.monthInfo('2026-11',local(2026,10,14)),series:[]}).kind!=='none')throw new Error('future');
        """))

    def test_client_rows_direction_names_and_csv_escaping(self):
        run_pages(self, wrap(r"""
          const rows=P.clientRows([{name:'ipad',rx:GiB,tx:10*GiB},{name:'gone',rx:0,tx:GiB},{name:'macbook',rx:2*GiB,tx:40*GiB}],
                                  [{name:'ipad',pubkey:'pk-i'},{name:'macbook',pubkey:'pk-m'}]);
          if(rows[0].name!=='macbook'||rows[2].name!=='gone')throw new Error('sorted by total');
          const ipad=rows[1];
          if(ipad.down!==10*GiB||ipad.up!==GiB||ipad.pubkey!=='pk-i')throw new Error('client tx is what the device received: '+JSON.stringify(ipad));
          if(rows[2].pubkey!=='')throw new Error('a deleted client has no link');
          const csv=P.toCSV([['client','total'],['a,b',1],['say "hi"',2],['=cmd()',3],['line\nbreak',4]]);
          const lines=csv.split('\r\n');
          const Q='"';
          if(lines[1]!==Q+'a,b'+Q+',1'||lines[2]!==Q+'say '+Q+Q+'hi'+Q+Q+Q+',2')throw new Error('quoting: '+csv);
          if(lines[3]!=="'=cmd(),3")throw new Error('formula guard: '+lines[3]);
          if(!csv.includes('"line\nbreak",4'))throw new Error('newline quoting');
          if(P.csvCell(-5)!=='-5')throw new Error('numbers are not guarded');
        """))


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestJournalHelpers(unittest.TestCase):
    def test_every_admin_op_reads_as_a_sentence(self):
        run_pages(self, wrap(r"""
          const names={'pk-a':'kirill-iphone','pk-g':'guest-1'};
          const ctx={now:local(2026,10,14,20),peerName:pk=>names[pk]||''};
          const v=(op,data,extra)=>P.eventView(Object.assign({id:1,ts:local(2026,10,14,10),kind:'admin',actor:'admin',ip:'198.51.100.7',subject:op,data:Object.assign({op},data)},extra||{}),ctx);
          const cases=[
            [v('add',{name:'anna-phone',exit:'nl',expires:0,ok:true}),'Client anna-phone created','exit NL · no expiry','ok'],
            [v('rename',{pubkey:'pk-a',name:'kirill-15',ok:true}),'Renamed to kirill-15','',''],
            [v('enabled',{pubkey:'pk-g',enabled:false,ok:true}),'guest-1 turned off','access paused, keys kept','u'],
            [v('enabled',{pubkey:'pk-g',enabled:true,ok:true}),'guest-1 turned on','access restored','ok'],
            [v('delete',{pubkey:'Zm9vYmFyYmF6',ok:true}),'Client key Zm9vYmFy… deleted','keys and config removed','bad'],
            [v('setexpiry',{pubkey:'pk-a',name:'kirill-iphone',expires:0,ok:true}),'kirill-iphone: no expiry now','',''],
            [v('setexit',{pubkey:'pk-a',name:'kirill-iphone',exit:'us',ok:true}),'kirill-iphone moved to US','',''],
            [v('setexitall',{exit:'nl',ok:true,changed:0}),'Everyone is already on NL','',''],
            [v('revertswitch',{ok:true,event_id:null,revert_of:5}),'Nobody left to move back','the clients were deleted or moved by hand',''],
            [v('setexitpolicy',{ok:true}),'Exit settings changed','quotas and automatic switching',''],
            [v('splitsave',{entries:14,refresh:true,ok:true}),'Split tunnel list saved','14 entries · RU subnets refreshed',''],
            [v('splitserver',{split:false,ok:true}),'Split tunnel turned off','all traffic goes through the exits',''],
            [v('export',{ok:true}),'Config backup downloaded','the archive holds every private key','warn'],
          ];
          for(const [view,title,detail,tone] of cases){
            if(view.title!==title)throw new Error('title: '+view.title+' ≠ '+title);
            if(detail&&view.detail!==detail)throw new Error('detail of «'+title+'»: '+view.detail);
            if(tone&&view.tone!==tone)throw new Error('tone of «'+title+'»: '+view.tone);
            if(view.who!=='admin · 198.51.100.7')throw new Error('who: '+view.who);
          }
          if(cases[0][0].tag!=='Client'||cases[9][0].tag!=='Settings'||cases[12][0].tag!=='Backup'||cases[7][0].tag!=='Switch')throw new Error('tags');
          if(!v('setexitall',{exit:'nl',ok:true,event_id:9,changed:5}).hide)throw new Error('a bulk switch with a journal row is told by that row');
          if(!v('revertswitch',{ok:true,event_id:12,revert_of:9}).hide)throw new Error('a revert with a journal row is told by that row');
        """))

    def test_failures_name_the_cause_without_raw_codes(self):
        run_pages(self, wrap(r"""
          const ctx={now:local(2026,10,14,20),peerName:()=>''};
          const v=(op,data)=>P.eventView({id:1,ts:local(2026,10,14,10),kind:'admin',actor:'admin',ip:'198.51.100.7',subject:op,data:Object.assign({op},data)},ctx);
          const ex=v('setexit',{pubkey:'pk-x',name:'ipad',exit:'us',ok:false,code:'target_exhausted'});
          if(ex.title!=='Not applied: moving ipad to US'||ex.tone!=='bad')throw new Error(ex.title);
          if(ex.detail!=='the target exit quota is exhausted')throw new Error('cause, lower-case, no dot: '+ex.detail);
          if(JSON.stringify(ex).includes('target_exhausted'))throw new Error('raw code leaked');
          const busy=v('add',{name:'guest-2',ok:false,error:'busy',busy:true});
          if(busy.title!=='Not started: creating guest-2'||busy.detail!=='another operation was running')throw new Error(busy.title+' / '+busy.detail);
          const unk=v('delete',{pubkey:'pk-x',ok:false,committed:'unknown',error:'timeout'});
          if(!unk.title.startsWith('Result unknown: deleting')||unk.tone!=='warn')throw new Error(unk.title);
          const pw=v('export',{ok:false,error:'wrong password'});
          if(pw.title!=='Not applied: config backup'||pw.detail!=='wrong password')throw new Error(pw.title+' / '+pw.detail);
          const other=v('rename',{pubkey:'pk-x',name:'x',ok:false,error:'name taken'});
          if(other.detail!=='the server refused the request')throw new Error('unknown errors get the generic cause: '+other.detail);
        """))

    def test_health_switch_login_and_logout_events(self):
        run_pages(self, wrap(r"""
          const now=local(2026,10,14,3,14);
          const ctx={now,revertedAt:()=>0,eventTs:()=>0};
          const down=P.eventView({id:2,ts:local(2026,10,14,3,2),kind:'health',actor:'system',subject:'us',data:{exit:'us',from:'up',to:'down',fails:3}},ctx);
          if(down.title!=='US stopped answering'||down.detail!=='3 checks in a row failed'||down.who!=='system'||down.tone!=='bad')throw new Error(JSON.stringify(down));
          const up=P.eventView({id:3,ts:now,kind:'health',actor:'system',subject:'us',data:{exit:'us',from:'down',to:'up',oks:2}},ctx);
          if(up.title!=='US passes its checks again'||!up.detail.includes('2 successful checks in a row')||up.tone!=='ok')throw new Error(JSON.stringify(up));
          const members=['kirill-iphone','macbook-pro','ipad','tv','router','watch','kindle'].map((n,i)=>({pubkey:'pk'+i,name:n,from:'us'}));
          const sw=P.eventView({id:4,ts:local(2026,10,14,3,12),kind:'exit_switch',actor:'system',subject:'us->nl',
            data:{source:'us',target:'nl',reason:'health',changed:7,members}},ctx);
          if(sw.title!=='7 clients moved US → NL')throw new Error(sw.title);
          if(!sw.detail.includes('kirill-iphone, macbook-pro')||!sw.detail.includes('and 1 more')||!sw.detail.includes('US failed its checks'))throw new Error(sw.detail);
          if(!sw.detail.includes('next automatic switch not before 03:17'))throw new Error('cooldown: '+sw.detail);
          if(!sw.revert||sw.revert.id!==4||sw.revert.n!==7||sw.tag!=='Switch'||!sw.hot)throw new Error('revert offered: '+JSON.stringify(sw.revert));
          const back=P.eventView({id:4,ts:local(2026,10,14,3,12),kind:'exit_switch',actor:'system',data:{source:'us',target:'nl',reason:'health',changed:7,members}},
            Object.assign({},ctx,{revertedAt:id=>id===4?local(2026,10,14,4,0):0}));
          if(back.revert||!back.detail.includes('moved back at 04:00'))throw new Error('a reverted switch is not offered again: '+back.detail);
          const rv=P.eventView({id:5,ts:now,kind:'exit_switch',actor:'admin',ip:'198.51.100.7',data:{source:'nl',target:'us',reason:'revert',changed:2,members:members.slice(0,2),revert_of:4}},
            Object.assign({},ctx,{eventTs:id=>id===4?local(2026,10,14,3,12):0}));
          if(rv.revert||!rv.detail.includes('back after the switch at 03:12'))throw new Error('a revert cannot be reverted from the journal: '+rv.detail);
          const one=P.eventView({id:6,ts:now,kind:'exit_switch',actor:'admin',data:{source:'nl',target:'us',reason:'manual',changed:1,members:members.slice(0,1)}},ctx);
          if(one.title!=='1 client moved NL → US'||!one.detail.includes('by hand'))throw new Error(one.title+' / '+one.detail);
          const ok=P.eventView({id:7,ts:now,kind:'login',actor:'admin',ip:'198.51.100.7',data:{ok:true}},ctx);
          if(ok.title!=='Signed in to the panel'||ok.tag!=='Sign-in'||ok.who!=='admin · 198.51.100.7')throw new Error(JSON.stringify(ok));
          const bad=P.eventView({id:8,ts:now,kind:'login',ip:'203.0.113.45',data:{ok:false,reason:'bad_creds'}},ctx);
          if(bad.title!=='Failed sign-in attempt'||bad.detail!=='from 203.0.113.45'||bad.who!=='protection')throw new Error(JSON.stringify(bad));
          const all=P.eventView({id:9,ts:now,kind:'logout_all',actor:'admin',ip:'198.51.100.7',data:{ok:true}},ctx);
          if(all.title!=='Signed out on all devices'||all.cat!=='access')throw new Error(JSON.stringify(all));
        """))

    def test_failed_sign_ins_fold_and_days_group(self):
        run_pages(self, wrap(r"""
          const now=local(2026,10,14,20);
          const ev=[];let id=100;
          ev.push({id:id--,ts:local(2026,10,14,9,32),kind:'login',ip:'203.0.113.45',data:{ok:false,reason:'throttled'}});
          for(let i=0;i<5;i++)ev.push({id:id--,ts:local(2026,10,14,9,31)-i*20,kind:'login',ip:'203.0.113.45',data:{ok:false,reason:'bad_creds'}});
          ev.push({id:id--,ts:local(2026,10,14,9,0),kind:'login',ip:'203.0.113.9',data:{ok:false,reason:'bad_creds'}});
          ev.push({id:id--,ts:local(2026,10,13,22,15),kind:'admin',actor:'admin',ip:'198.51.100.7',subject:'enabled',data:{op:'enabled',pubkey:'pk-g',enabled:false,ok:true}});
          ev.push({id:id--,ts:local(2026,10,10,8,0),kind:'login',actor:'admin',ip:'198.51.100.7',data:{ok:true}});
          const views=P.journalViews(ev,'all',{now});
          if(views.length!==4)throw new Error('six failures from one address fold into one row: '+views.map(v=>v.title).join(' | '));
          if(views[0].title!=='6 failed sign-in attempts'||!views[0].detail.includes('blocked for a while'))throw new Error(views[0].title+' / '+views[0].detail);
          if(views[1].title!=='Failed sign-in attempt')throw new Error('another address stays apart');
          const groups=P.groupByDay(views,now);
          if(groups.map(g=>g.label).join(' | ')!=='Today · October 14 | Yesterday · October 13 | October 10')throw new Error(groups.map(g=>g.label).join(' | '));
          if(groups[0].items.length!==2)throw new Error('two rows today');
        """))

    def test_filters_follow_the_meaning_not_only_the_kind(self):
        run_pages(self, wrap(r"""
          const now=local(2026,10,14,20);let id=50;
          const ev=['add','setexitpolicy','splitserver','export','setexit'].map(op=>({id:id--,ts:now-id*60,kind:'admin',actor:'admin',subject:op,data:{op,ok:true,name:'x',exit:'nl'}}))
            .concat([{id:id--,ts:now-9000,kind:'health',actor:'system',data:{exit:'nl',from:'up',to:'down',fails:3}},
                     {id:id--,ts:now-9100,kind:'login',actor:'admin',data:{ok:true}}]);
          const cats=f=>P.journalViews(ev,f,{now}).map(v=>v.title).join(' | ');
          if(cats('clients')!=='Client x created | x moved to NL')throw new Error('clients: '+cats('clients'));
          if(cats('exits')!=='Exit settings changed | Split tunnel turned off | NL stopped answering')throw new Error('exits: '+cats('exits'));
          if(cats('access')!=='Config backup downloaded | Signed in to the panel')throw new Error('access: '+cats('access'));
          if(P.journalViews(ev,'all',{now}).length!==ev.length)throw new Error('all shows everything');
        """))


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestExitsHelpers(unittest.TestCase):
    def test_situation_offers_revert_only_when_the_source_is_healthy(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          const s=JSON.parse(JSON.stringify(WG.state));
          s.exit_policy.exits.nl.clients=3;s.exit_policy.exits.us.clients=0;
          s.exit_policy.last_switch={ts:s.now-1800,source:'us',target:'nl',reason:'health',changed:5,event_id:42,members_count:5};
          s.tunnel.exits.us.health_since=s.now-600;
          let st=P.situation(s);
          if(st.tone!=='warn'||!st.revert||st.revert.id!==42||st.revert.n!==5||st.revert.exit!=='US')throw new Error(JSON.stringify(st));
          if(!st.text.startsWith('All 3 clients on NL: at ')||!st.text.includes('US healthy again since'))throw new Error(st.text);
          s.tunnel.exits.us=Object.assign({},s.tunnel.exits.us,{ok:false,health:'down',affected_clients:0});
          st=P.situation(s);
          if(st.revert)throw new Error('no way back onto a failing exit');
          s.tunnel.exits.us=Object.assign({},s.tunnel.exits.us,{ok:true,health:'up'});
          s.exit_policy.last_switch.revert_of=7;
          if(P.situation(s).revert)throw new Error('a revert is not a failover');
          const stale=Object.assign({},s,{stale:true});
          const su=P.situation(stale);
          if(su.tone!=='u'||su.revert||!su.text.startsWith('Data is stale'))throw new Error('stale: '+JSON.stringify(su));
          const off=Object.assign({},s,{offline:true});
          if(P.situation(off).tone!=='u'||!P.situation(off).text.includes('actions are off'))throw new Error('offline');
        """))

    def test_scheme_widths_and_grey_lines_when_unknown(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          let md=P.diagramModel(WG.state);
          const nl=md.exits.find(e=>e.key==='nl'),us=md.exits.find(e=>e.key==='us');
          if(!(nl.w>us.w)||!nl.main||us.main)throw new Error('the busier exit is the thick main line');
          if(nl.tone!=='ink'||P.wireWidth(0)!==2||P.wireWidth(1)!==10)throw new Error('widths');
          md=P.diagramModel(Object.assign({},WG.state,{stale:true}));
          if(!md.u||md.exits.some(e=>e.tone!=='u'||e.health!=='unknown'))throw new Error('stale lines are grey');
        """))

    def test_health_cells_never_paint_missing_hours_as_ok(self):
        run_pages(self, wrap(r"""
          const t=local(2026,10,14,0);
          const cells=P.healthCells([{ts:t,ok:0,fail:0},{ts:t+3600,ok:360,fail:0},{ts:t+7200,ok:340,fail:20},{ts:t+10800,ok:100,fail:260},{ts:t+14400,ok:360,fail:0}]);
          if(cells.map(c=>c.tone).join()!=='none,ok,warn,bad,ok')throw new Error(cells.map(c=>c.tone).join());
          const s=P.healthSummary(cells);
          if(s!=='failure 02:00–04:00 · 1 h no data')throw new Error(s);
          if(P.healthSummary(P.healthCells([{ts:t,ok:5,fail:0},{ts:t+3600,ok:5,fail:0}]))!=='2 h without failures')throw new Error('clean');
          const pol=P.protectionText(10,{auto_switch:true,health_failover:false});
          if(!pol.startsWith('Exits are checked every ~10 s.')||!pol.includes('on a failure they stay'))throw new Error(pol);
        """))


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestPagesRender(unittest.TestCase):
    def test_exits_page_scheme_history_and_actions(self):
        run_pages(self, wrap(r"""
          const snap=snapshot();
          snap.exit_policy.last_switch={ts:snap.now-1800,source:'us',target:'nl',reason:'health',changed:5,event_id:42,members_count:5};
          await feed(snap);
          const hours=Array.from({length:24},(_,i)=>({ts:snap.now-(23-i)*3600,ok:i<2?0:360,fail:i===20?30:0}));
          serve({'/api/health-history':()=>response({error:'history unavailable'},503),'/api/status':snap});
          WG.router.go('exits');await settle();
          if(!viewText().includes('Check history is unavailable.')||!q('[data-act="xs-hh-retry"]'))throw new Error('history error state: '+viewText());
          if(!viewText().includes('Amsterdam'))throw new Error('the scheme does not wait for the history');
          serve({'/api/health-history':{probe_s:10,exits:{nl:hours,us:hours}},'/api/status':snap});
          q('[data-act="xs-hh-retry"]').click();await settle();
          const text=viewText();
          for(const s of ['Cascade scheme','Amsterdam','New York','Internet','RU sites','Now','Health checks · 24 h','failure','How it works'])
            if(!text.includes(s))throw new Error('missing «'+s+'»: '+text.slice(0,400));
          if(!text.includes('Exits are checked every ~10 s.'))throw new Error('probe interval from the history');
          if(q('.xs-exit.is-main').getAttribute('data-exit')!=='nl')throw new Error('NL is the main exit');
          q('[data-act="xs-revert"]').click();
          q('[data-act="xs-settings"]').click();
          if(JSON.stringify(acts)!=='[["revert",42],["exits"]]')throw new Error('actions: '+JSON.stringify(acts));
          serve({'/api/health-history':()=>response({error:'history unavailable'},503),'/api/status':snap});
          WG.router.go('clients');WG.router.go('exits');await settle();
          if(!viewText().includes('failure')||!viewText().includes('could not refresh'))throw new Error('a failed refresh keeps the last history and says so: '+viewText().slice(-500));
        """))

    def test_usage_page_loads_months_and_shows_errors(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          const now=WG.state.now,d=new Date(now*1000),key=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');
          const prev=P.shiftMonth(key,-1);
          const day=key+'-01';
          serve({'/api/history':url=>url.includes(prev)?response({error:'x'},503):response({month:key,daily:[],
              clients:[{name:'kirill-iphone',rx:GiB,tx:30*GiB},{name:'gone-device',rx:0,tx:GiB}],
              exits_daily:{nl:[{day,rx:20*GiB,tx:GiB}],us:[{day,rx:5*GiB,tx:0}]},exits_month:{nl:{rx:20*GiB,tx:GiB},us:{rx:5*GiB,tx:0}}}),
            '/api/events':{events:[],next_before:null},'/api/status':WG.state});
          WG.router.go('usage');await settle();
          if(!urls.some(u=>u==='/api/history?month='+key))throw new Error('the month is asked explicitly: '+urls.join(' '));
          const text=viewText();
          for(const s of ['Traffic usage','By day','By client','kirill-iphone','gone-device','deleted','quota 1000 GiB','Through the exits this month'])
            if(!text.includes(s))throw new Error('missing «'+s+'»: '+text.slice(0,500));
          if(!element('view').querySelector('table.sr-only'))throw new Error('the chart has a table for screen readers');
          q('[data-act="us-client"]').click();
          if(JSON.stringify(acts)!=='[["conf","pk-a","history"]]')throw new Error('client opens its history: '+JSON.stringify(acts));
          q('[data-act="us-month"]').click();await settle();
          if(!urls.includes('/api/history?month='+prev))throw new Error('previous month requested');
          if(!viewText().includes('The usage database is unavailable.')||!q('[data-act="us-retry"]'))throw new Error('error state: '+viewText().slice(0,300));
          const next=element('view').querySelectorAll('[data-act="us-month"]').pop();
          next.click();await settle();
          if(!viewText().includes('kirill-iphone'))throw new Error('back to the current month from cache');
          const after=element('view').querySelectorAll('[data-act="us-month"]').pop();
          if(!after.disabled)throw new Error('no future months');
        """))

    def test_usage_empty_month_says_so(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          serve({'/api/history':{month:'x',daily:[],clients:[],exits_daily:{nl:[],us:[]},exits_month:{nl:{rx:0,tx:0},us:{rx:0,tx:0}}},
                 '/api/events':{events:[],next_before:null},'/api/status':WG.state});
          WG.router.go('usage');await settle();
          if(!/No traffic in \w+ \d{4}\./.test(viewText()))throw new Error('empty month: '+viewText().slice(0,300));
        """))

    def test_journal_page_rows_filters_paging_and_states(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          const now=WG.state.now;
          const page1=[{id:30,ts:now-60,kind:'exit_switch',actor:'system',subject:'us->nl',data:{source:'us',target:'nl',reason:'health',changed:2,
                          members:[{pubkey:'pk-a',name:'kirill-iphone'},{pubkey:'pk-b',name:'ipad'}]}}];
          for(let i=0;i<49;i++)page1.push({id:29-i,ts:now-120-i*60,kind:'login',actor:'admin',ip:'198.51.100.7',data:{ok:true}});
          const page2=[{id:-20,ts:now-4000,kind:'logout_all',actor:'admin',ip:'198.51.100.7',data:{ok:true}}];
          serve({'/api/events?limit=50&kind=health,exit_switch,admin':{events:[],next_before:null},
                 '/api/events?limit=50&before=':{events:page2,next_before:null},
                 '/api/events':{events:page1,next_before:-19},'/api/status':WG.state});
          WG.router.go('journal');await settle();
          let text=viewText();
          if(!text.includes('2 clients moved US → NL')||!text.includes('Signed in to the panel'))throw new Error(text.slice(0,300));
          const rv=q('[data-act="jr-revert"]');
          if(!rv||rv.getAttribute('data-id')!=='30')throw new Error('revert link');
          rv.click();
          if(JSON.stringify(acts)!=='[["revert",30]]')throw new Error(JSON.stringify(acts));
          q('[data-act="jr-more"]').click();await settle();
          if(!viewText().includes('Signed out on all devices')||!viewText().includes('That is the whole journal.'))throw new Error('second page: '+viewText().slice(-300));
          element('view').querySelectorAll('[data-act="jr-filter"]')[1].click();await settle();
          if(!urls.includes('/api/events?limit=50&kind=health,exit_switch,admin'))throw new Error('filter asks the server by kind: '+urls.join(' '));
          if(!viewText().includes('No events of this type.'))throw new Error('empty filter: '+viewText().slice(0,300));
          serve({'/api/events':()=>response({error:'events unavailable'},503),'/api/status':WG.state});
          element('view').querySelectorAll('[data-act="jr-filter"]')[0].click();await settle();
          if(!viewText().includes('The journal is unavailable.')||!q('[data-act="jr-retry"]'))throw new Error('error: '+viewText().slice(0,300));
        """))

    def test_split_route_opens_the_settings_only_from_navigation(self):
        run_pages(self, wrap(r"""
          await feed(snapshot());
          serve({'/api/status':WG.state,'/api/health-history':{probe_s:10,exits:{}}});
          WG.router.go('split');runTimers(0);await settle();
          if(!viewText().includes('RU sites directly')||!viewText().includes('On: RU subnets'))throw new Error(viewText());
          if(JSON.stringify(acts)!=='[["split"]]')throw new Error('opened from the nav: '+JSON.stringify(acts));
          q('[data-act="sp-open"]').click();
          if(acts.length!==2)throw new Error('button opens the settings');
        """))

    def test_russian_texts_and_plurals(self):
        run_pages(self, wrap(r"""
          const ctx={now:local(2026,10,14,20)};
          const sw=n=>P.eventView({id:1,ts:local(2026,10,14,10),kind:'exit_switch',actor:'system',data:{source:'us',target:'nl',reason:'quota',changed:n,members:[]}},ctx).title;
          if(sw(1)!=='1 клиент переведён US → NL'||sw(3)!=='3 клиента переведены US → NL'||sw(5)!=='5 клиентов переведены US → NL')throw new Error([sw(1),sw(3),sw(5)].join(' | '));
          const ev=[];for(let i=0;i<5;i++)ev.push({id:10-i,ts:local(2026,10,14,9,31)-i*20,kind:'login',ip:'203.0.113.45',data:{ok:false,reason:'bad_creds'}});
          if(P.journalViews(ev,'all',ctx).length!==1||P.journalViews(ev,'all',ctx)[0].title!=='5 неудачных попыток входа в панель')throw new Error('login plural');
          const g=P.groupByDay([{ts:local(2026,10,14,10)},{ts:local(2026,10,13,10)}],local(2026,10,14,20));
          if(g[0].label!=='Сегодня · 14 октября'||g[1].label!=='Вчера · 13 октября')throw new Error(g.map(x=>x.label).join(' | '));
          const info=P.monthInfo('2026-10',local(2026,10,14,12));
          const t=P.forecastText(P.forecast({used:371*GiB,quota:500*GiB,info,series:[]}),{key:'us',used:371*GiB,clients:0,info});
          if(t!=='при темпе 1–14 окт (27 ГиБ/день) кончилась бы ~19 окт · сейчас на US 0 клиентов')throw new Error(t);
        """), lang="ru")


if __name__ == "__main__":
    unittest.main()
