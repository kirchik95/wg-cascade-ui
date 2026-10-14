#!/usr/bin/env python3
"""Frontend resilience: GET deadlines, polling backoff, admin timeouts, card reorder cost."""
import os
import shutil
import subprocess
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_frontend_monthly import NODE_SETUP, ROOT


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestFrontendPolling(unittest.TestCase):
    def run_node(self, body):
        script = textwrap.dedent(NODE_SETUP + "\n" + body)
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_hung_status_fetch_times_out_and_next_tick_requests_again(self):
        self.run_node(r"""
        process.exitCode=1;(async()=>{
          await new Promise(r=>setImmediate(r));          // let the load-time tick settle
          timers.clear();
          let calls=0;
          context.fetch=()=>{calls++;return new Promise(()=>{});};
          const first=context.tick();
          context.tick();                                   // busy: must not start a second request
          if(calls!==1)throw new Error('expected 1 request while busy, got '+calls);
          const deadline=[...timers.values()].filter(t=>t.delay===12000);
          if(deadline.length!==1)throw new Error('status request has no 12 s deadline');
          runTimers(12000);
          await first;
          if(!element('offline').innerHTML.includes('not responding'))throw new Error('stale banner missing: '+element('offline').innerHTML);
          context.tick();
          if(calls!==2)throw new Error('next tick did not issue a new request after the deadline: '+calls);
          process.exitCode=0;
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_backoff_grows_with_failures_and_resets_on_kick(self):
        self.run_node(r"""
        process.exitCode=1;(async()=>{
          await new Promise(r=>setImmediate(r));
          timers.clear();
          context.fetch=()=>Promise.reject(new Error('offline'));
          for(let i=0;i<3;i++)await context.tick();       // load tick + 3 → 4 failures
          const d=context.nextTickDelay();
          if(d<32000||d>48000)throw new Error('expected ~40 s backoff after 4 failures, got '+d);
          for(let i=0;i<6;i++)await context.tick();
          if(context.nextTickDelay()>60000*1.2)throw new Error('backoff not capped');
          context.kickTick();
          if(context.nextTickDelay()!==5000)throw new Error('kick did not reset backoff');
          if(![...timers.values()].some(t=>t.delay===0))throw new Error('kick did not schedule an immediate tick');
          process.exitCode=0;
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_hidden_tab_skips_fetch_and_rendering(self):
        self.run_node(r"""
        process.exitCode=1;(async()=>{
          await new Promise(r=>setImmediate(r));
          let calls=0;context.fetch=()=>{calls++;return Promise.reject(new Error('offline'));};
          document.hidden=true;
          await context.tick();
          if(calls!==0)throw new Error('hidden tab fetched status');
          if(context.nextTickDelay()!==15000)throw new Error('hidden interval not used');
          document.hidden=false;
          process.exitCode=0;
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_admin_timeout_follows_operation_table(self):
        self.run_node(r"""
        process.exitCode=1;(async()=>{
          await new Promise(r=>setImmediate(r));
          timers.clear();
          context.fetch=(url)=>new Promise(()=>{});
          const pending=context.admin({op:'rename',pubkey:'x',name:'y'});
          const delays=[...timers.values()].map(t=>t.delay);
          if(!delays.includes(160000))throw new Error('rename should wait 160 s, timers: '+delays);
          runTimers(160000);
          const r=await pending;
          if(r.ok||!/no response/.test(r.error))throw new Error('timeout not reported: '+JSON.stringify(r));
          timers.clear();
          context.admin({op:'add',name:'n'});context.admin({op:'getconf',pubkey:'x'});context.admin({op:'splitsave',entries:[]});
          const d2=[...timers.values()].map(t=>t.delay).sort((a,b)=>a-b).join(',');
          if(d2!=='60000,195000,210000')throw new Error('unexpected admin deadlines '+d2);
          process.exitCode=0;
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_config_shows_before_history_and_close_cancels_helpers(self):
        self.run_node(r"""
        process.exitCode=1;(async()=>{
          await new Promise(r=>setImmediate(r));
          const pending=[];
          context.fetch=(url)=>{
            if(url==='/api/admin')return Promise.resolve(response({ok:true,name:'phone',ip:'10.10.0.2',conf:'[Interface]\nPrivateKey = k'}));
            return new Promise((resolve,reject)=>pending.push({url,resolve}));
          };
          await context.showCfg('PUB');
          if(!element('modal').innerHTML.includes('PrivateKey'))throw new Error('config not shown while history pending');
          if(pending.length!==2)throw new Error('expected connections+history requests, got '+pending.length);
          context.closeModal();
          pending.forEach(p=>p.resolve(response({connections:[{ts:1,endpoint:'192.0.2.1:1'}],daily:[]})));
          await new Promise(r=>setImmediate(r));
          if(element('cfgextra')&&element('cfgextra').innerHTML.includes('192.0.2.1'))throw new Error('closed modal was updated');
          process.exitCode=0;
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_reorder_of_250_cards_uses_constant_root_queries(self):
        self.run_node(r"""
        const peers=[];
        for(let i=2;i<252;i++)peers.push({name:'c'+i,ip:'10.10.0.'+i,pubkey:'pk'+i,enabled:true,online:true,
          age:5,rx:i,tx:i,mrx:0,mtx:0,spark:[],endpoint:''});
        const root=element('cards');
        context.renderClients(peers.filter(p=>p.ip!=='10.10.0.100'));
        let qsa=0,qs=0;
        const origAll=root.querySelectorAll.bind(root),orig=root.querySelector.bind(root);
        root.querySelectorAll=sel=>{qsa++;return origAll(sel);};
        root.querySelector=sel=>{qs++;return orig(sel);};
        context.renderClients(peers);                     // pk100 is new and must land at index 98
        if(qsa+qs>4)throw new Error('root queried '+(qsa+qs)+' times for 250 cards');
        const order=root.children.map(c=>c.dataset.pk);
        if(order.length!==250||order[98]!=='pk100'||order[0]!=='pk2'||order[249]!=='pk251')
          throw new Error('wrong card order: '+order.slice(95,102));
        """)


if __name__ == "__main__":
    unittest.main()
