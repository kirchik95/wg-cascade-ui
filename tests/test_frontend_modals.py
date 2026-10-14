#!/usr/bin/env python3
"""Front-end windows (app/modals.js, stage 2B): name rules and transliteration, access
terms, the split list parser, exit settings (quotas, switches, bulk move — the old exit-policy
window tests on the new code), revert of a switched group, delete / turn off with undo, the
backup, offline guard, and texts. Runs icons.js + core.js + dashboard.js + modals.js in the
fake DOM of test_frontend_monthly."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_frontend_monthly import NODE_SETUP

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"
FILES = "['app/icons.js','app/core.js','app/dashboard.js']"
assert FILES in NODE_SETUP, "the fake DOM no longer loads the stage 1 files this way"
SETUP = NODE_SETUP.replace(FILES, "['app/icons.js','app/core.js','app/dashboard.js','app/modals.js']") + r"""
const K=WG.modalKit;
const eq=(a,b,m)=>{if(JSON.stringify(a)!==JSON.stringify(b))throw new Error(m+': '+JSON.stringify(a)+' !== '+JSON.stringify(b));};
const dlg=()=>{const c=WG.modal.current();if(!c)throw new Error('no window open');return c.el;};
const q=(sel)=>dlg().querySelector(sel);
const type=(el,v)=>{el.value=v;el.dispatchEvent(makeEvent('input',el));};
/* text of the live fake tree (textContent set later does not show in a parent's innerHTML) */
const text=(el)=>el?((el._textContent||'')+' '+el.children.map(text).join(' ')).replace(/\s+/g,' ').trim():'';
function admin(handler){
  const calls=[];
  context.fetch=(url,o)=>{
    if(url==='/api/admin'){const b=JSON.parse(o.body);calls.push(b);return Promise.resolve(handler(b,calls));}
    if(typeof handler.get==='function')return Promise.resolve(handler.get(url));
    return new Promise(()=>{});
  };
  return calls;
}
"""


def run(test, body, lang="en", timeout=20):
    script = textwrap.dedent(SETUP + "\nprocess.exitCode=1;(async()=>{\n" + body + "\nprocess.exitCode=0;console.log('__OK__');\n})().catch(e=>{console.error(e);process.exitCode=1;});")
    env = dict(os.environ, WGUI_TEST_LANG=lang)
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    test.assertEqual(result.returncode, 0, result.stderr + result.stdout)
    test.assertIn("__OK__", result.stdout, "the test body did not run to the end:\n" + result.stderr)


class TestModalsStatic(unittest.TestCase):
    def test_client_rules_match_the_helper(self):
        js = (APP / "modals.js").read_text()
        helper = (APP / "wg-admin.py").read_text()
        for name in ("NAME_RE", "ENTRY_RE"):
            py = re.search(name + r"\s*=\s*re\.compile\(r'([^']+)'\)", helper).group(1)
            jsre = re.search(r"const " + name + r"=/(.+?)/;", js).group(1).replace("\\/", "/")
            self.assertEqual(jsre, py, name + " drifted from wg-admin.py")

    def test_no_inline_handlers_and_accessible_windows(self):
        for name in ("modals.js", "login.html", "login.js"):
            src = (APP / name).read_text()
            self.assertNotRegex(src, r"""\son[a-z]+\s*=\s*["']""", name + " has an inline handler (CSP)")
        css = (APP / "modals.css").read_text()
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        self.assertIn("@media (max-width:600px)", css)
        self.assertRegex(css, r"\.mseg-b\{[^}]*min-height:44px")
        js = (APP / "modals.js").read_text()
        self.assertIn('role="switch"', js)
        self.assertIn('role="radiogroup"', js)

    def test_login_page_is_e1(self):
        html = (APP / "login.html").read_text()
        for needle in ('class="lg-form" method="post" action="/login"', 'autocomplete="username"',
                       'autocomplete="current-password"', 'aria-describedby="err"', 'id="pwtoggle"',
                       'data-act="lang" data-l="ru"', 'data-act="lang" data-l="en"'):
            self.assertIn(needle, html)
        self.assertRegex(html, r'<script src="/login\.js(?:\?v=[^"\s]+)?"></script>')
        self.assertNotIn("theme.js", html)
        js = (APP / "login.js").read_text()
        self.assertIn("aria-invalid", js)
        self.assertIn("после 5 неудачных попыток вход временно блокируется", js)


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestModalKit(unittest.TestCase):
    def test_names_and_transliteration(self):
        run(self, r"""
        const peers=[{pubkey:'a',name:'kirill-iphone'},{pubkey:'b',name:'anya-telefon'}];
        eq(K.nameProblem('',peers),'empty','empty');
        eq(K.nameProblem('Аня телефон',peers),'chars','cyrillic');
        eq(K.nameProblem('-phone',peers),'first','first char');
        eq(K.nameProblem('a'.repeat(33),peers),'long','33 chars');
        eq(K.nameProblem('a'.repeat(32),peers),'','32 chars fit');
        eq(K.nameProblem('Kirill-iPhone',peers),'taken','taken ignores case like the helper');
        eq(K.nameProblem('kirill-iphone',peers,'a'),'','a client keeps its own name');
        eq(K.nameProblem('  ok_name-1 ',peers),'','trimmed');
        eq(K.translit('Аня телефон'),'anya-telefon','translit');
        eq(K.translit('Щука / Ёж!!'),'shchuka-ezh','symbols collapse to one dash');
        eq(K.translit('я'.repeat(40)).length,32,'at most 32');
        eq(K.suggestName('Аня телефон',peers),'anya-telefon-2','a taken suggestion gets a suffix');
        eq(K.suggestName('ok-name',peers),'','nothing to suggest for a valid name');
        eq(K.suggestName('!!!',peers),'','nothing to suggest from symbols');
        """)

    def test_access_terms_count_from_the_running_term(self):
        run(self, r"""
        const now=1790000000,D=86400;
        eq(K.termAfter('keep',now+3*D,now),now+3*D,'keep');
        eq(K.termAfter('never',now+3*D,now),0,'no expiry');
        eq(K.termAfter('+30',now+3*D,now),now+33*D,'+30 from the running term');
        eq(K.termAfter('+7',now-D,now),now+7*D,'+7 from now when expired');
        eq(K.termAfter('+7',0,now),now+7*D,'+7 from now without a term');
        eq([K.addTerm(0,now),K.addTerm(7,now)],[0,now+7*D],'new client terms');
        """)

    def test_split_list_is_checked_line_by_line(self):
        run(self, r"""
        const p=K.parseSplit('gosuslugi.ru\n# note\n\nsberbank.ru\n203.0.113.0/24\nmybank..ru\nGOSUSLUGI.RU\n300.1.1.1\n10.0.0.0/33\n2001:db8::/32\nlocalhost\nexample.com/24\nbad_host.ru');
        eq(p.entries,['gosuslugi.ru','sberbank.ru','203.0.113.0/24'],'valid lines, comments dropped, duplicates once');
        eq(p.errors.map(e=>e.line+':'+e.code),['6:dots','8:octet','9:mask','10:ipv6','11:domain','12:mask_on_domain','13:chars'],'errors with line numbers');
        const t=K.splitErrorText(p.errors);
        if(!t.includes('line 6')||!t.includes('mybank..ru')||!t.includes('two dots in a row')||!t.includes('and 6 more'))throw new Error('error text: '+t);
        eq(K.parseSplit(Array.from({length:501},(_,i)=>'h'+i+'.example.com').join('\n')).tooMany,true,'500 lines max');
        """)

    def test_exit_policy_payload_guard_and_counts(self):
        run(self, r"""
        eq(K.policyBody(true,false,'500','750'),{op:'setexitpolicy',auto_switch:true,health_failover:false,quotas_gib:{nl:500,us:750}},'payload');
        for(const bad of ['','500.5','0','1000001','-1','5e2',' '])if(K.policyBody(true,true,bad,'750')!==null)throw new Error('bad quota accepted: '+JSON.stringify(bad));
        const pol={exits:{nl:{used:10,quota:100,checked_age:20,healthy:true},us:{used:100,quota:100,checked_age:20,healthy:true}}};
        eq(K.bulkBlock(pol,'us'),'target_exhausted','exhausted');
        pol.exits.us.used=1;pol.exits.us.checked_age=61;eq(K.bulkBlock(pol,'us'),'target_stale','stale after 60 s');
        pol.exits.us.checked_age=-1;eq(K.bulkBlock(pol,'us'),'target_stale','never checked');
        pol.exits.us.checked_age=5;pol.exits.us.healthy=false;eq(K.bulkBlock(pol,'us'),'target_unhealthy','down');
        pol.exits.us.healthy=true;eq(K.bulkBlock(pol,'us'),'','healthy');eq(K.bulkBlock(pol,'de'),'invalid_target','unknown exit');
        eq(K.moving([{exit:'nl',enabled:true},{exit:'us',enabled:true},{enabled:false}],'us'),{n:2,off:1,total:3},'disabled clients move too');
        const f=K.forecast([{mrx:10*GiB,mtx:0},{mrx:4*GiB,mtx:0}],{exits:{us:{used:50*GiB,quota:100*GiB}}},'us',new Date(2026,9,15,0,0).getTime()/1000);
        if(Math.abs(f.perDay-GiB)>1||Math.abs(f.days-50)>0.01)throw new Error('forecast: '+JSON.stringify(f));
        """)

    def test_health_history_is_grey_without_data(self):
        run(self, r"""
        const t0=1790000000-1790000000%3600;
        const hours=Array.from({length:24},(_,i)=>({ts:t0+i*3600,ok:i<2?0:120,fail:0}));
        let b=K.healthBuckets(hours);
        eq(b.slice(0,3).map(x=>x.st),['none','none','ok'],'no data is grey, not green');
        eq(K.healthSummary(b),'22 h without failures · 2 h no data','summary');
        hours[20]={ts:t0+20*3600,ok:117,fail:3};hours[21]={ts:t0+21*3600,ok:10,fail:110};
        b=K.healthBuckets(hours);
        eq([b[20].st,b[21].st],['warn','bad'],'some failures vs mostly failures');
        eq(K.healthSummary(b),'failure '+WG.fmtTime(t0+20*3600)+'–'+WG.fmtTime(t0+22*3600),'failure range');
        eq(K.healthSummary([]),'no check history yet','empty');
        """)

    def test_revert_plan_and_honest_outcomes(self):
        run(self, r"""
        const ev={id:42,ts:1,data:{source:'us',target:'nl',reason:'health',members:[{pubkey:'pk-a',name:'kirill-iphone'},{pubkey:'gone',name:'old'},{pubkey:'pk-c',name:'guest-1'}]}};
        const plan=K.revertPlan(ev,[{pubkey:'pk-a',name:'kirill-iphone',exit:'nl'},{pubkey:'pk-c',name:'guest-1',exit:'us'}]);
        eq([plan.from,plan.to,plan.count],['nl','us',1],'plan');
        eq(plan.rows.map(r=>r.state),['move','deleted','already'],'rows');
        let o=K.revertOutcome({kind:'partial',data:{ok:true,changed:[{pubkey:'pk-a',name:'kirill-iphone'}],skipped:[{pubkey:'gone',name:'old',reason:'deleted'},{pubkey:'pk-c',name:'guest-1',reason:'already_on_target'}]},message:'',steps:[]},plan);
        eq(o.kind,'ok','skips shown before confirming keep «ok»');
        o=K.revertOutcome({kind:'partial',data:{ok:true,changed:[{pubkey:'pk-a',name:'kirill-iphone'}],skipped:[{pubkey:'gone',name:'old',reason:'deleted'}],cleanup_warning:'cleanup failed'},message:'',steps:[]},plan);
        eq(o.kind,'warn','an expected skip must preserve the cleanup warning');
        eq(o.data.cleanup_warning,'cleanup failed','warning data is retained');
        o=K.revertOutcome({kind:'partial',data:{ok:true,changed:[{name:'kirill-iphone'}],skipped:[{name:'x',reason:'helper_failed'}]},message:''},plan);
        eq([o.kind,o.steps.map(s=>s.state)],['partial',['ok','failed']],'other skips are partial');
        if(o.steps[1].text.includes('helper_failed'))throw new Error('raw code shown');
        o=K.revertOutcome({kind:'partial',data:{ok:true,noop:true,changed:[],skipped:[{name:'old',reason:'deleted'}]},message:''},plan);
        eq(o.kind,'failed','nothing moved is not «applied»');
        o=K.revertOutcome({kind:'unknown',data:null,message:'No answer'},plan);
        eq(o.kind,'unknown','unknown stays unknown');
        """)

    def test_revert_keeps_newly_skipped_planned_client_partial(self):
        run(self, r"""
        const plan={to:'us',count:2,rows:[{pubkey:'a',state:'move'},{pubkey:'b',state:'move'},{pubkey:'old',state:'deleted'}]};
        const data={ok:true,committed:true,changed:[{pubkey:'a',name:'first'}],skipped:[{pubkey:'b',name:'second',reason:'deleted'},{pubkey:'old',name:'old',reason:'deleted'}],cleanup_warning:'cleanup failed'};
        const out=K.revertOutcome({kind:'partial',data,steps:[]},plan);
        eq(out.kind,'partial','a newly skipped planned move remains partial');
        eq(out.data.cleanup_warning,'cleanup failed','partial result keeps cleanup warning data');
        if(!out.steps.some(s=>s.text.includes('second')&&s.text.includes('deleted')))throw new Error('the new skip must be visible');
        """)

    def test_steps_stop_at_the_first_failure_and_say_what_applied(self):
        run(self, r"""
        await feed(snapshot());
        const ok=d=>()=>Promise.resolve({kind:'ok',data:d||{},message:''});
        const bad=code=>()=>Promise.resolve({kind:'failed',data:{ok:false,code},message:'x'});
        let r=await K.runSteps([{text:'a',call:bad('target_exhausted')},{text:'b',call:ok()}]);
        eq(r.kind,'failed','the first failure is its own outcome');
        let applied=[];
        r=await K.runSteps([{text:'name: a → b',call:ok(),apply:()=>applied.push('name')},{text:'exit: NL → US',call:bad('target_unhealthy')},{text:'term',call:ok()}]);
        eq([r.kind,r.steps.map(s=>s.state),applied],['partial',['ok','failed','skipped'],['name']],'partial');
        if(!r.steps[1].text.includes('down')||r.steps[1].text.includes('target_unhealthy'))throw new Error('step reason: '+r.steps[1].text);
        r=await K.runSteps([{text:'a',call:ok()},{text:'b',call:()=>Promise.resolve({kind:'unknown',data:null,message:'No answer.'})}]);
        if(r.kind!=='unknown'||!r.message.includes('Applied: a'))throw new Error('unknown after a step: '+JSON.stringify(r));
        r=await K.runSteps([{text:'a',call:()=>Promise.resolve({kind:'warn',data:{},message:'careful'})},{text:'b',call:ok({x:1})}]);
        eq([r.kind,r.message,r.data],['warn','careful',{x:1}],'warn');
        r=await K.runSteps([{text:'a',call:()=>Promise.resolve({kind:'busy',data:{busy:true},message:'busy'})}]);
        eq(r.kind,'busy','busy before anything applied');
        """)

    def test_steps_recheck_fresh_status_before_each_call(self):
        run(self, r"""
        for(const untrusted of [{loaded:false},{stale:true},{offline:true}]){
          await feed(snapshot());
          const calls=[];
          const out=await K.runSteps([
            {text:'first',call:()=>{calls.push('first');WG.state=Object.assign({},WG.state,untrusted);return Promise.resolve({kind:'ok',data:{committed:true}});}},
            {text:'second',call:()=>{calls.push('second');return Promise.resolve({kind:'ok',data:{committed:true}});}}
          ]);
          eq(calls,['first'],'untrusted status stops a later call');
          eq(out.kind,'partial','the already committed first step is reported');
        }
        """)

    def test_every_literal_text_has_a_russian_translation(self):
        js = (APP / "modals.js").read_text()
        keys = set(re.findall(r"\btr\('((?:[^'\\]|\\.)*)'", js))
        for block in ("ENTRY_TEXT", "SKIP_TEXT"):
            body = re.search(r"const " + block + r"=\{(.*?)\};", js, re.S).group(1)
            keys |= set(re.findall(r":'((?:[^'\\]|\\.)*)'", body))
        keys = sorted(k for k in keys if re.search(r"[A-Za-z]", k) and k not in ("{name} → {exit}",))
        self.assertGreater(len(keys), 100)
        run(self, "const keys=%s;const miss=keys.filter(k=>WG.tr(k)===k);if(miss.length)throw new Error('no Russian text for: '+miss.join(' | '));" % json.dumps(keys), lang="ru")


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestModalWindows(unittest.TestCase):
    def test_mutation_controls_require_loaded_fresh_status(self):
        run(self, r"""
        for(const untrusted of [{loaded:false},{stale:true},{offline:true}]){
          await feed(snapshot());
          WG.state=Object.assign({},WG.state,untrusted);
          const info={ok:true,extra:[],server:{state:'off',ipset:0},meta:{}};
          const event={id:42,ts:1790000000,kind:'exit_switch',data:{source:'us',target:'nl',reason:'health',members:[{pubkey:'pk-a',name:'kirill-iphone'}]}};
          const handler=b=>response(b.op==='splitinfo'?info:{ok:true,committed:true});
          handler.get=()=>response({event,events:[]});
          const calls=admin(handler);
          const disabled=sel=>{const b=q(sel);if(!b||!b.disabled)throw new Error(JSON.stringify(untrusted)+' allows '+sel);};
          WG.actions.addClient();type(q('.m-name'),'fresh');disabled('[data-m="create"]');
          WG.actions.editClient('pk-a');type(q('.m-name'),'renamed');disabled('[data-m="save"]');
          WG.actions.deleteClient('pk-a');type(q('.m-del-in'),'kirill-iphone');disabled('[data-m="del"]');disabled('[data-m="off"]');
          WG.actions.switchExit('pk-a','us');disabled('[data-m="go"]');
          WG.actions.exitsSettings();type(q('[data-x="us"]').querySelector('.m-q'),'700');
          disabled('[data-m="save"]');disabled('[data-m="bulk"][data-k="us"]');
          WG.actions.revertSwitch(42);await flush(40);disabled('[data-m="go"]');
          WG.actions.splitSettings();await flush(40);q('[data-m="on"]').click();
          disabled('[data-m="apply"]');disabled('[data-m="refresh"]');
          WG.actions.backup();type(q('.m-pw'),'password');disabled('[data-m="make"]');
          const out=await WG.actions.toggleEnabled('pk-a');
          eq(out.kind,'failed','direct toggle is blocked');
          eq(calls.map(b=>b.op),['splitinfo'],'only the read operation may be sent');
          WG.modal.close();
        }
        """)

    def test_multistep_mutations_stop_when_status_becomes_untrusted(self):
        run(self, r"""
        let serverNow=1790000000;
        for(const action of ['edit','split'])for(const untrusted of [{loaded:false},{stale:true},{offline:true}]){
          await feed(snapshot({now:serverNow+=10}));
          let resolve;
          const info={ok:true,extra:[],server:{state:'off',ipset:0},meta:{}};
          const calls=admin(b=>b.op==='splitinfo'?response(info):new Promise(r=>{resolve=r;}));
          if(action==='edit'){
            WG.actions.editClient('pk-a');type(q('.m-name'),'renamed');q('[data-m="exit"][data-k="us"]').click();
            q('[data-m="save"]').click();
          }else{
            WG.actions.splitSettings();await flush(40);q('[data-m="on"]').click();type(q('.m-sx'),'example.com');
            q('[data-m="apply"]').click();
          }
          WG.state=Object.assign({},WG.state,untrusted);WG.emit('status',WG.state);
          resolve(response({ok:true,committed:true}));await flush(60);
          eq(calls.map(b=>b.op),action==='edit'?['rename']:['splitinfo','splitserver'],action+' does not send the next step');
          const out=text(q('.m-out-box'));
          if(!out.includes('Partially'))throw new Error(action+' lost the first committed step: '+out);
          WG.modal.close();
        }
        """)

    def test_reopened_edit_waits_for_running_operation_before_saving_its_draft(self):
        run(self, r"""
        const initial=snapshot();await feed(initial);
        let resolve;
        const calls=admin(b=>b.op==='rename'?new Promise(r=>{resolve=r;}):response({ok:true,committed:true}));
        const request=context.fetch;
        WG.actions.editClient('pk-a');type(q('.m-name'),'renamed');q('[data-m="save"]').click();
        WG.modal.close();
        WG.actions.editClient('pk-a');q('[data-m="exit"][data-k="us"]').click();
        if(!q('[data-m="save"]').disabled)throw new Error('reopened edit allows saving during the earlier operation');
        q('.m-name').dispatchEvent(makeEvent('keydown',q('.m-name'),{key:'Enter'}));
        resolve(response({ok:true,committed:true}));await flush(60);
        if(!WG.modal.current())throw new Error('the earlier result closed the new draft');
        if(!q('[data-m="save"]').disabled)throw new Error('saving unlocked before a new status snapshot');
        const fresh=JSON.parse(JSON.stringify(initial));fresh.now+=5;fresh.peers[0].name='renamed';
        await feed(fresh);context.fetch=request;
        eq(q('.m-name').value,'renamed','untouched name follows the new server snapshot');
        if(q('[data-m="save"]').disabled)throw new Error('fresh status did not unlock saving');
        eq(calls.map(b=>b.op),['rename'],'the blocked draft did not send');
        q('[data-m="save"]').click();await flush(60);
        eq(calls[1],{op:'setexit',pubkey:'pk-a',exit:'us'},'the new draft is applied after its own save');
        """)

    def test_reopened_edit_waits_for_new_snapshot_and_extends_from_updated_expiry(self):
        run(self, r"""
        const start=Math.round(Date.now()/1000),s=snapshot();s.now=start;s.peers[0].expires=start+3*86400;
        await feed(s);
        let resolve;
        let calls=admin(()=>new Promise(r=>{resolve=r;}));
        WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();q('[data-m="save"]').click();
        eq(calls[0].expires,start+10*86400,'first extension');
        WG.modal.close();WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();
        resolve(response({ok:true,committed:true,expires:start+10*86400}));await flush(60);
        if(!q('[data-m="save"]').disabled)throw new Error('operation completion alone unlocks the old expiry');
        await feed(s);
        if(!q('[data-m="save"]').disabled)throw new Error('a repeated cached snapshot unlocks the old expiry');
        const fresh=JSON.parse(JSON.stringify(s));fresh.now=start+5;fresh.peers[0].expires=start+10*86400;
        await feed(fresh);
        if(q('[data-m="save"]').disabled)throw new Error('a new server snapshot did not unlock the draft');
        calls=admin(()=>response({ok:true,committed:true}));
        q('[data-m="save"]').click();await flush(60);
        eq(calls,[{op:'setexpiry',pubkey:'pk-a',expires:start+17*86400}],'second extension starts at the updated expiry');
        """)

    def test_reopened_edit_rebases_server_fields_and_preserves_dirty_choices(self):
        run(self, r"""
        const start=Math.round(Date.now()/1000),s=snapshot();s.now=start;s.peers[0].expires=start+3*86400;
        await feed(s);
        let resolve;admin(()=>new Promise(r=>{resolve=r;}));
        WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();q('[data-m="save"]').click();
        WG.modal.close();WG.actions.editClient('pk-a');
        type(q('.m-name'),'my-draft');q('[data-m="term"][data-k="+30"]').click();q('[data-m="exit"][data-k="us"]').click();
        resolve(response({ok:true,committed:true}));await flush(60);
        const fresh=JSON.parse(JSON.stringify(s));fresh.now=start+5;
        Object.assign(fresh.peers[0],{name:'server-name',expires:start+10*86400,exit:'us'});
        await feed(fresh);
        eq(q('.m-name').value,'my-draft','dirty name preserved');
        eq(q('[data-m="term"][data-k="+30"]').getAttribute('aria-checked'),'true','term choice preserved');
        eq(q('[data-m="exit"][data-k="us"]').getAttribute('aria-checked'),'true','exit choice preserved');
        const calls=admin(()=>response({ok:true,committed:true}));
        q('[data-m="save"]').click();await flush(60);
        eq(calls,[{op:'rename',pubkey:'pk-a',name:'my-draft'},{op:'setexpiry',pubkey:'pk-a',expires:start+40*86400}],'draft is compared with the new server baseline');
        """)

    def test_edit_opened_after_completion_waits_for_the_new_snapshot(self):
        run(self, r"""
        const start=Math.round(Date.now()/1000),s=snapshot();s.now=start;s.peers[0].expires=start+3*86400;
        await feed(s);
        let resolve;admin(()=>new Promise(r=>{resolve=r;}));
        WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();q('[data-m="save"]').click();
        WG.modal.close();resolve(response({ok:true,committed:true}));await flush(60);
        WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();
        if(!q('[data-m="save"]').disabled)throw new Error('a form opened after completion still uses the old expiry');
        const fresh=JSON.parse(JSON.stringify(s));fresh.now=start+5;fresh.peers[0].expires=start+10*86400;
        await feed(fresh);
        const calls=admin(()=>response({ok:true,committed:true}));q('[data-m="save"]').click();await flush(60);
        eq(calls,[{op:'setexpiry',pubkey:'pk-a',expires:start+17*86400}],'completed edits also establish the refresh barrier');
        """)

    def test_own_unknown_expiry_requires_new_choice_after_status_refresh(self):
        run(self, r"""
        let start=Math.round(Date.now()/1000);
        for(const applied of [true,false]){
          start+=10;
          const s=snapshot();s.now=start;s.peers[0].expires=start+3*86400;await feed(s);
          const calls=admin(()=>response({ok:false,committed:'unknown',error:'timeout'},400));
          const request=context.fetch;
          WG.actions.editClient('pk-a');q('[data-m="term"][data-k="+7"]').click();q('[data-m="save"]').click();await flush(60);
          eq(calls[0].expires,start+10*86400,'original absolute expiry');
          const fresh=JSON.parse(JSON.stringify(s));fresh.now=start+5;
          fresh.peers[0].expires=applied?start+10*86400:start+3*86400;
          await feed(fresh);context.fetch=request;
          if(!q('[data-m="save"]').disabled)throw new Error('own unknown relative term became an implicit new extension');
          eq(q('[data-m="term"][data-k="keep"]').getAttribute('aria-checked'),'true','own unknown resets the relative choice');
          if(!text(q('.m-term-h')).includes('Choose a term again'))throw new Error('the reset needs an explanation');
          q('.m-name').dispatchEvent(makeEvent('keydown',q('.m-name'),{key:'Enter'}));await flush(20);
          eq(calls.length,1,'Enter must not repeat an unknown relative extension');
          q('[data-m="term"][data-k="+7"]').click();q('[data-m="save"]').click();await flush(60);
          eq(calls[1].expires,start+(applied?17:10)*86400,'a new explicit choice extends the refreshed term');
          WG.modal.close();
        }
        """)

    def test_delete_turn_off_does_not_toggle_an_already_disabled_client_on(self):
        run(self, r"""
        await feed(snapshot());WG.actions.deleteClient('pk-a');
        const s=snapshot();s.peers.find(p=>p.pubkey==='pk-a').enabled=false;await feed(s);
        const calls=admin(()=>response({ok:true,committed:true}));
        q('[data-m="off"]').click();await flush(40);
        eq(calls,[{op:'enabled',pubkey:'pk-a',enabled:false}],'turn off remains an explicit disable after a status update');
        if(element('ops').querySelector('[data-act="op-undo"]'))throw new Error('an already disabled client must not offer an undo that enables it');
        """)

    def test_exit_settings_save_guards_and_outcomes(self):
        run(self, r"""
        await feed(snapshot());
        WG.actions.exitsSettings();
        const save=()=>q('[data-m="save"]');
        if(!save().disabled||!text(save()).includes('No changes'))throw new Error('a disabled save says why: '+text(save()));
        if(q('[data-m="auto"]').getAttribute('aria-checked')!=='true'||q('[data-m="auto"]').getAttribute('role')!=='switch')throw new Error('switch state');
        const usq=q('[data-x="us"]').querySelector('.m-q');
        if(usq.value!=='500')throw new Error('quota prefilled in GiB: '+usq.value);
        type(usq,'350');
        if(!text(q('.wband-box')).includes('becomes used up: 371 GiB used with the new quota of 350 GiB'))throw new Error('quota warning: '+text(q('.wband-box')));
        type(usq,'35.5');
        if(!save().disabled||!text(save()).includes('Fix the quota'))throw new Error('fractional quota accepted');
        type(usq,'750');
        if(text(q('.wband-box')))throw new Error('warning must clear');
        q('[data-m="fail"]').click();
        let resolve;const calls=[];
        context.fetch=(url,o)=>{if(url==='/api/admin'){calls.push(JSON.parse(o.body));return new Promise(r=>{resolve=r;});}return new Promise(()=>{});};
        save().click();
        if(save())throw new Error('the busy footer replaces the save button');
        WG.actions.exitsSettings&&WG.ops.run({key:'exit-policy',label:'again',call:()=>{calls.push('dup');return Promise.resolve({kind:'ok'});}});
        eq(calls,[{op:'setexitpolicy',auto_switch:true,health_failover:false,quotas_gib:{nl:1000,us:750}}],'one request, exact payload');
        const busy=text(q('.dlg-f'));
        if(!q('.mf-busy')||/%/.test(busy)||!busy.includes('result stays'))throw new Error('busy footer: '+busy);
        resolve(response({ok:false,error:'invalid exit policy'},400));
        await flush(40);
        if(!text(q('.m-out-box')).includes('Not applied'))throw new Error('failure stays in the window');
        if(save().disabled||usq.disabled)throw new Error('controls come back after a failure');
        if(!element('ops').querySelector('.op-failed'))throw new Error('failure in the strip too');
        context.fetch=(url,o)=>url==='/api/admin'?Promise.resolve(response({ok:true})):new Promise(()=>{});
        save().click();await flush(40);
        if(WG.modal.current())throw new Error('success closes the window');
        if(!element('ops').querySelector('.op-ok'))throw new Error('success in the strip');
        """)

    def test_exit_settings_closed_or_replaced_window_keeps_the_outcome_in_the_strip(self):
        run(self, r"""
        await feed(snapshot());
        for(const outcome of ['failure','success'])for(const transition of ['close','replace']){
          WG.actions.exitsSettings();
          const usq=q('[data-x="us"]').querySelector('.m-q');type(usq,'640');
          let resolve;context.fetch=(url)=>url==='/api/admin'?new Promise(r=>{resolve=r;}):new Promise(()=>{});
          q('[data-m="save"]').click();
          let newer=null;
          if(transition==='close')WG.modal.close();else newer=WG.modal.open({title:'Newer',body:'<p id="keep">keep</p>'});
          resolve(outcome==='success'?response({ok:true}):response({ok:false,code:'target_stale'},400));
          await flush(40);
          if(transition==='close'&&WG.modal.current())throw new Error(outcome+': a closed window came back');
          if(transition==='replace'&&(WG.modal.current()!==newer||!newer.alive()||!newer.body.querySelector('#keep')&&!newer.body.innerHTML.includes('keep')))throw new Error(outcome+': the newer window was touched');
          const sel=outcome==='success'?'.op-ok':'.op-failed';
          if(!element('ops').querySelector(sel))throw new Error(outcome+'/'+transition+': outcome lost');
          WG.modal.close();
          element('ops').querySelectorAll('[data-act="op-dismiss"]').forEach(b=>b.click());
        }
        """)

    def test_bulk_move_confirms_counts_and_sends_no_force(self):
        run(self, r"""
        await feed(snapshot());
        WG.actions.exitsSettings();
        type(q('[data-x="nl"]').querySelector('.m-q'),'900');
        const toNl=q('[data-m="bulk"][data-k="nl"]'),toUs=q('[data-m="bulk"][data-k="us"]');
        if(toNl.disabled||!text(toNl).includes('All 1 to NL'))throw new Error('to NL: '+text(toNl));
        if(toUs.disabled||!text(toUs).includes('All 2 to US'))throw new Error('to US: '+text(toUs));
        toUs.click();
        if(!text(q('.dlg-title')).includes('All 2 to US?'))throw new Error('confirm title');
        const rows=text(q('.m-rows'));
        if(!rows.includes('2 clients')||!rows.includes('371 of 500 GiB · 129 left')||!rows.includes('working'))throw new Error('rows: '+rows);
        q('[data-m="back"]').click();
        if(q('[data-x="nl"]').querySelector('.m-q').value!=='900')throw new Error('«Cancel» returns to the settings with the draft');
        q('[data-m="bulk"][data-k="us"]').click();
        let resolve;const calls=admin(()=>new Promise(r=>{resolve=r;}));
        q('[data-m="go"]').click();
        if(WG.modal.current())throw new Error('confirm closes; the strip shows the run');
        WG.actions.exitsSettings();q('[data-m="bulk"][data-k="us"]').click();q('[data-m="go"]').click();
        eq(calls,[{op:'setexitall',exit:'us'}],'one bulk request without force');
        resolve(response({ok:true,exit:'us',changed:2}));await flush(40);
        if(!text(element('ops')).includes('2 clients moved to US'))throw new Error('strip: '+text(element('ops')));
        const s=snapshot();s.exit_policy.exits.us.exhausted=true;await feed(s);
        WG.actions.exitsSettings();
        const b=q('[data-m="bulk"][data-k="us"]');
        if(!b.disabled||!text(b).includes('US quota is used up'))throw new Error('a used-up target is off with a reason: '+text(b));
        """)

    def test_bulk_move_reports_the_server_count_and_zero_as_no_change(self):
        run(self, r"""
        for(const changed of [1,0,undefined]){
          await feed(snapshot());
          WG.actions.exitsSettings();q('[data-m="bulk"][data-k="us"]').click();
          admin(()=>response({ok:true,committed:changed>0,exit:'us',changed}));
          q('[data-m="go"]').click();await flush(40);
          const out=text(element('ops'));
          if(out.includes('2 clients moved'))throw new Error('the preview count leaked into the result: '+out);
          if(changed===1&&!out.includes('1 client moved to US'))throw new Error('actual count missing: '+out);
          if(changed===0&&!out.includes('Nothing changed'))throw new Error('zero changes were not stated: '+out);
          if(changed===undefined&&(!out.includes('Switch to US completed')||out.includes('Nothing changed')))throw new Error('missing count must not be presented as zero: '+out);
        }
        """)

    def test_revert_result_counts_changed_clients_instead_of_the_preview(self):
        run(self, r"""
        await feed(snapshot());
        const event={id:42,ts:1790000000,kind:'exit_switch',data:{source:'us',target:'nl',reason:'health',members:[{pubkey:'pk-a',name:'first'},{pubkey:'pk-b',name:'second'}]}};
        const handler=()=>response({ok:true,committed:true,changed:[{pubkey:'pk-a',name:'first'}],skipped:[]});
        handler.get=()=>response({event});admin(handler);
        WG.actions.revertSwitch(42);await flush(40);q('[data-m="go"]').click();await flush(40);
        const out=text(element('ops'));
        if(!out.includes('1 client back on US')||out.includes('2 clients back on US'))throw new Error('server changed count missing: '+out);
        """)

    def test_delete_needs_the_name_and_turning_off_has_undo(self):
        run(self, r"""
        await feed(snapshot());
        let calls=admin(()=>response({ok:true}));
        WG.actions.deleteClient('pk-b');
        if(!q('.eyebrow').classList.contains('is-danger'))throw new Error('irreversible eyebrow');
        const del=()=>q('[data-m="del"]'),inp=q('.m-del-in');
        if(!del().disabled||!del().classList.contains('btn-danger'))throw new Error('delete starts disabled');
        type(inp,'ipa');if(!del().disabled)throw new Error('a partial name must not enable');
        type(inp,'ipad');if(del().disabled)throw new Error('the exact name enables');
        del().click();await flush(40);
        eq(calls,[{op:'delete',pubkey:'pk-b'}],'delete payload');
        if(WG.modal.current())throw new Error('window closes');
        calls=admin(()=>response({ok:true}));
        WG.actions.deleteClient('pk-a');q('[data-m="off"]').click();await flush(40);
        eq(calls,[{op:'enabled',pubkey:'pk-a',enabled:false}],'«Turn off instead»');
        const undo=element('ops').querySelector('[data-act="op-undo"]');
        if(!undo)throw new Error('turning off offers undo');
        undo.click();await flush(40);
        eq(calls[1],{op:'enabled',pubkey:'pk-a',enabled:true},'undo turns it back on');
        WG.actions.deleteClient('pk-c');
        if(q('[data-m="off"]'))throw new Error('a disabled client has no «Turn off instead»');
        """)

    def test_new_client_name_hint_payload_and_qr_step(self):
        run(self, r"""
        await feed(snapshot());
        WG.actions.addClient();
        const create=()=>q('[data-m="create"]'),inp=q('.m-name');
        if(!create().disabled||!text(create()).includes('Enter a name'))throw new Error('empty name: '+text(create()));
        type(inp,'Аня телефон');
        if(!create().disabled||!text(create()).includes('Fix the name'))throw new Error('cyrillic name');
        if(inp.getAttribute('aria-invalid')!=='true'||!text(q('.m-name-h')).includes('only Latin letters'))throw new Error('field error');
        q('[data-m="suggest"]').click();
        eq(inp.value,'anya-telefon','the hint fills the transliteration');
        if(create().disabled)throw new Error('a valid name enables create');
        type(inp,'Kirill-iPhone');
        if(!text(q('.m-name-h')).includes('already taken'))throw new Error('taken name');
        type(inp,'anya-telefon');
        q('[data-m="term"][data-k="7"]').click();
        q('[data-m="exit"][data-k="us"]').click();
        if(q('[data-m="exit"][data-k="us"]').getAttribute('aria-checked')!=='true')throw new Error('exit card selected');
        const conf='[Interface]\nAddress = 10.10.0.19/32\nDNS = 1.1.1.1\n\n[Peer]\nAllowedIPs = 0.0.0.0/0, ::/0\n';
        const calls=admin(b=>response({ok:true,name:b.name,ip:'10.10.0.19',pubkey:'pk-new',conf,qr:'iVBORw0KGgo=',exit:b.exit}));
        const t0=Math.round(Date.now()/1000);
        create().click();await flush(40);
        eq([calls[0].op,calls[0].name,calls[0].exit],['add','anya-telefon','us'],'add payload');
        if(Math.abs(calls[0].expires-(t0+7*86400))>5)throw new Error('7 days from now: '+calls[0].expires);
        if(text(q('.dlg-title'))!=='anya-telefon'||!q('.eyebrow').classList.contains('is-ok'))throw new Error('step 2 title');
        const img=q('img');if(!img||img.getAttribute('src')!=='data:image/png;base64,iVBORw0KGgo=')throw new Error('qr image');
        const meta=text(q('.cq-meta'));
        if(!meta.includes('exit US')||!meta.includes('10.10.0.19')||!meta.includes('IPv4 and IPv6')||!meta.includes('DNS 1.1.1.1'))throw new Error('meta: '+meta);
        if(!q('[data-m="dl"]')||!q('[data-m="copy"]')||q('[data-m="share"]'))throw new Error('.conf and copy; share only where the device can share files');
        admin(()=>response({ok:true,name:'kirill-iphone',ip:'10.10.0.2',conf,qr:'"><img src=x onerror=alert(1)>'}));
        WG.actions.showConfig('pk-a');await flush(40);
        if(q('.m-pane').innerHTML.includes('onerror')||q('img')||!text(q('.cq-qr')).includes('too big for a QR'))throw new Error('qr must be base64 only');
        const s=snapshot();s.exit_policy.exits.us.exhausted=true;await feed(s);
        WG.actions.addClient();
        const us=q('[data-m="exit"][data-k="us"]');
        if(us.getAttribute('aria-disabled')!=='true')throw new Error('a used-up exit cannot be picked');
        us.click();
        if(q('[data-m="exit"][data-k="nl"]').getAttribute('aria-checked')!=='true')throw new Error('the click on a blocked card is ignored');
        """)

    def test_edit_extends_from_the_current_term_and_reports_partial_changes(self):
        run(self, r"""
        const now=Math.round(Date.now()/1000),s=snapshot();s.peers[1].expires=now+3*86400;await feed(s);
        let calls=admin(()=>response({ok:true}));
        WG.actions.editClient('pk-b');
        const save=()=>q('[data-m="save"]');
        if(!save().disabled||!text(save()).includes('No changes'))throw new Error('nothing changed yet');
        if(!text(q('.m-now')).includes('3 days')||!q('.m-now').classList.contains('is-warn'))throw new Error('current term: '+text(q('.m-now')));
        q('[data-m="term"][data-k="+30"]').click();
        if(!text(q('.m-term-h')).includes('will be: until'))throw new Error('preview');
        save().click();await flush(40);
        eq(calls,[{op:'setexpiry',pubkey:'pk-b',expires:now+33*86400}],'+30 days from the current term');
        if(WG.modal.current())throw new Error('success closes');
        s.now+=5;s.peers[1].expires=now+33*86400;await feed(s);
        calls=admin(b=>b.op==='setexit'?response({ok:false,code:'target_exhausted'},409):response({ok:true}));
        WG.actions.editClient('pk-b');
        type(q('.m-name'),'ipad-2');
        q('[data-m="exit"][data-k="us"]').click();
        save().click();await flush(60);
        eq(calls.map(c=>c.op),['rename','setexit'],'steps in order');
        const out=text(q('.m-out-box'));
        if(!out.includes('Partially')||!out.includes('name: ipad → ipad-2')||!out.includes('quota is exhausted'))throw new Error('partial outcome: '+out);
        if(text(q('.dlg-title'))!=='ipad-2')throw new Error('the applied rename shows in the title');
        if(!element('ops').querySelector('.op-partial'))throw new Error('partial in the strip');
        """)

    def test_offline_sends_nothing(self):
        run(self, r"""
        await feed(snapshot());
        WG.state=Object.assign({},WG.state,{offline:true});
        let n=0;context.fetch=()=>{n++;return new Promise(()=>{});};
        const out=await WG.actions.toggleEnabled('pk-a');
        if(out.kind!=='failed'||!out.message.includes('No connection')||n!==0)throw new Error('offline: '+JSON.stringify(out)+' fetches='+n);
        WG.actions.addClient();type(q('.m-name'),'fresh');
        if(!q('[data-m="create"]').disabled||!text(q('[data-m="create"]')).includes('No connection'))throw new Error('create is off offline');
        """)

    def test_revert_lists_the_group_and_sends_the_event(self):
        run(self, r"""
        await feed(snapshot());
        const ev={id:42,ts:1790000000-600,kind:'exit_switch',data:{source:'us',target:'nl',reason:'health',
          members:[{pubkey:'pk-a',name:'kirill-iphone'},{pubkey:'pk-b',name:'ipad'},{pubkey:'zz',name:'gone'}]}};
        const handler=()=>new Promise(()=>{});
        handler.get=url=>url==='/api/events?id=42'?response({event:ev}):response({},404);
        const calls=admin(handler);
        WG.actions.revertSwitch(42);await flush(40);
        if(text(q('.dlg-title'))!=='Move clients back to US?')throw new Error('title: '+text(q('.dlg-title')));
        const rows=text(q('.ml'));
        if(!rows.includes('kirill-iphone NL → US')||!rows.includes('gone skipped · client deleted'))throw new Error('rows: '+rows);
        const go=q('[data-m="go"]');
        if(go.disabled||!text(go).includes('Move 2 back to US'))throw new Error('go: '+text(go));
        go.click();
        eq(calls,[{op:'revertswitch',event_id:42}],'revert payload');
        """)

    def test_split_draft_line_check_and_two_steps(self):
        run(self, r"""
        await feed(snapshot());
        const info=(on,extra)=>response({ok:true,meta:{ru_count:11873,direct_count:11876,built_at:'2026-10-12 03:00'},extra,server:{state:on?'on':'off',ipset:on?11876:0}});
        const calls=admin(b=>b.op==='splitinfo'?info(false,['gosuslugi.ru']):b.op==='splitserver'?info(true,['gosuslugi.ru']):info(true,b.entries));
        WG.actions.splitSettings();await flush(40);
        if(!text(q('.m-meta')).includes('11,873 RU subnets')||!text(q('.m-meta')).includes('03:00'))throw new Error('meta: '+text(q('.m-meta')));
        const apply=()=>q('[data-m="apply"]'),ta=q('.m-sx');
        eq(ta.value,'gosuslugi.ru','saved list');
        if(!apply().disabled||!text(apply()).includes('No changes'))throw new Error('no changes');
        type(ta,'gosuslugi.ru\nmybank..ru');
        if(!apply().disabled||!text(apply()).includes('Fix line 2')||!text(q('.m-sx-h')).includes('two dots'))throw new Error('line check');
        type(ta,'gosuslugi.ru\nexample.com');
        q('[data-m="on"]').click();
        if(q('[data-m="on"]').getAttribute('aria-checked')!=='true')throw new Error('switch is a draft until apply');
        eq(calls.length,1,'the switch alone sends nothing');
        apply().click();await flush(60);
        eq(calls.slice(1),[{op:'splitserver',split:true},{op:'splitsave',refresh:false,entries:['gosuslugi.ru','example.com']}],'two steps in order');
        if(WG.modal.current())throw new Error('applied: window closes');
        """)

    def test_backup_checks_the_password_and_hands_the_file(self):
        run(self, r"""
        await feed(snapshot());
        context.atob=atob;context.Blob=Blob;let made=0;context.URL={createObjectURL(){made++;return'blob:x';},revokeObjectURL(){}};
        const handler=b=>b.password==='right'?response({ok:true,archive:Buffer.from('abc').toString('base64'),missing:['extra/history.db']})
          :response({ok:false,error:'wrong password'},403);
        handler.get=url=>response({events:[{id:1,ts:Math.round(Date.now()/1000)-3*86400,kind:'admin',subject:'export',data:{op:'export',ok:true}}]});
        const calls=admin(handler);
        WG.actions.backup();await flush(20);
        if(!text(q('.m-last')).includes('last backup'))throw new Error('last backup: '+text(q('.m-last')));
        const make=()=>q('[data-m="make"]'),pw=q('.m-pw');
        if(!make().disabled)throw new Error('needs the password');
        type(pw,'nope');make().click();await flush(40);
        if(!text(q('.m-out-box')).includes('Wrong password')||pw.value!=='')throw new Error('wrong password: '+text(q('.m-out-box')));
        type(pw,'right');make().click();await flush(40);
        eq(calls.map(c=>c.op),['export','export'],'export twice');
        const file=text(q('.bk-file'));
        if(!/wg-cascade-\d{4}-\d{2}-\d{2}\.tar\.gz/.test(file)||!file.includes('not in the archive: extra/history.db'))throw new Error('file: '+file);
        if(made!==1)throw new Error('without share the archive downloads at once');
        """)


if __name__ == "__main__":
    unittest.main()
