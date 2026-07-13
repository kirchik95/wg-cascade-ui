#!/usr/bin/env python3
import pathlib
import shutil
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent

NODE_SETUP = r"""
const fs = require('fs');
const vm = require('vm');
const elements = new Map();
function element(id){
  if(!elements.has(id)){
    const classes = new Set();
    const attrs = {};
    elements.set(id, {
      id, textContent: '', innerHTML: '', className: '', dataset: {}, style: {},
      disabled: false, value: '', checked: false, offsetParent: {},
      classList: {
        add(...xs){ xs.forEach(x => classes.add(x)); },
        remove(...xs){ xs.forEach(x => classes.delete(x)); },
        contains(x){ return classes.has(x); },
        toggle(x,on){
          if(on === undefined) on = !classes.has(x);
          on ? classes.add(x) : classes.delete(x);
          return on;
        }
      },
      querySelectorAll(){ return []; },
      querySelector(){ return null; },
      setAttribute(k,v){ attrs[k] = String(v); },
      getAttribute(k){ return Object.prototype.hasOwnProperty.call(attrs,k) ? attrs[k] : null; },
      addEventListener(){},
      focus(){ this.focused = true; document.activeElement = this; },
      select(){}, closest(){ return this; }
    });
  }
  return elements.get(id);
}
const document = {
  body: {querySelectorAll(){ return []; }},
  activeElement: null,
  documentElement: {lang: 'en'},
  querySelector(selector){
    if(selector === 'meta[name=csrf]') return {content: 'csrf'};
    return null;
  },
  querySelectorAll(){ return []; },
  getElementById: element,
  createElement(){ return {click(){}, style: {}, dataset: {}}; },
  addEventListener(){},
  createTreeWalker(){ return {nextNode(){ return null; }}; }
};
const context = {
  console, require, document,
  NodeFilter: {SHOW_TEXT: 4},
  navigator: {},
  window: {matchMedia(){ return {matches: true}; }, addEventListener(){}},
  localStorage: {getItem(){ return 'en'; }, setItem(){}},
  requestAnimationFrame(){ return 0; },
  cancelAnimationFrame(){},
  clearTimeout(){},
  setInterval(){ return 0; },
  setTimeout(){ return 0; },
  fetch(){ return Promise.reject(new Error('network disabled in test')); },
  location: {href: '', reload(){}},
  performance: {now(){ return 0; }}
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync('app/app.js', 'utf8') +
  '\nglobalThis.__monthlyTest = {trafficTotals, peersByExit, clientExit, monthSummaryHTML, renderUsage};' +
  '\nglobalThis.__policyTest = {monthExitHTML, renderExitPolicy, exitPolicyRowHTML, exitSwitchConfirmHTML, policyRequestBody, bulkTargetBlock, saveExitPolicy, doExitAll, openModal, closeModal};',
  context,
  {filename: 'app/app.js'}
);
const monthly = context.__monthlyTest;
const policyHelpers = context.__policyTest;
"""


class TestFrontendMonthlyTraffic(unittest.TestCase):
    def run_node(self, body):
        script = textwrap.dedent(NODE_SETUP + "\n" + body)
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_header_has_accessible_exit_policy_controls(self):
        html = (ROOT / "app" / "index.html").read_text()
        self.assertIn('id="monthuse"', html)
        self.assertIn('button class="pill monthpill" id="monthuse-nl"', html)
        self.assertIn('button class="pill monthpill" id="monthuse-us"', html)
        self.assertIn('data-act="exit-policy"', html)
        self.assertIn('aria-label="NL exit routing settings"', html)
        self.assertIn('aria-label="US exit routing settings"', html)
        self.assertIn('id="policyalert"', html)
        self.assertIn('id="policyalert" style="display:none" role="alert"', html)

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_monthly_helpers_still_render_usage_history(self):
        self.run_node(
            r"""
            const totals = monthly.trafficTotals(
              [{mrx: 1024, mtx: 2048}, {mrx: 512, mtx: 0}, {mrx: null, mtx: 256}],
              'mrx', 'mtx'
            );
            if(totals.rx !== 1536 || totals.tx !== 2304){
              throw new Error('unexpected totals ' + JSON.stringify(totals));
            }
            const peers = [
              {exit: 'nl', mrx: 1024, mtx: 2048},
              {exit: 'us', mrx: 4096, mtx: 0},
              {exit: null, mrx: 512, mtx: 0},
            ];
            if(monthly.peersByExit(peers, 'nl').length !== 2 || monthly.peersByExit(peers, 'us').length !== 1){
              throw new Error('unexpected exit partition');
            }
            monthly.renderUsage({daily: [], clients: []});
            const modalHtml = element('ubody').innerHTML;
            if(!modalHtml.includes('Month') || !modalHtml.includes('0.0 B')){
              throw new Error('empty usage modal should include zero total: ' + modalHtml);
            }
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_server_policy_renders_quota_states_and_guarded_actions(self):
        self.run_node(
            r"""
            const policy = {
              auto_switch: true,
              exits: {
                nl: {used: 495 * 1024 ** 3, quota: 500 * 1024 ** 3, clients: 14, healthy: true, checked_age: 1, exhausted: false},
                us: {used: 0, quota: 750 * 1024 ** 3, clients: 0, healthy: false, checked_age: 1, exhausted: false}
              },
              blocked: {code: 'target_unhealthy', source: 'nl', target: 'us'},
              last_switch: null,
              warning: null
            };
            policyHelpers.renderExitPolicy(policy);
            if(!element('monthuse-nl').innerHTML.includes('495.0 GiB') || !element('monthuse-nl').classList.contains('warn')){
              throw new Error('NL warning missing');
            }
            if(element('monthuse-nl').classList.contains('critical')) throw new Error('warning cannot be critical');
            if(!element('policyalert').classList.contains('show') || element('policyalert').style.display !== 'flex'){
              throw new Error('blocked banner missing');
            }
            if(policyHelpers.bulkTargetBlock(policy, 'us') !== 'target_unhealthy'){
              throw new Error('unhealthy target must be blocked');
            }
            const body = policyHelpers.policyRequestBody(true, '500', '750');
            if(JSON.stringify(body) !== JSON.stringify({op:'setexitpolicy',auto_switch:true,quotas_gib:{nl:500,us:750}})){
              throw new Error('bad policy payload ' + JSON.stringify(body));
            }
            const row = policyHelpers.exitPolicyRowHTML('us', policy.exits.us);
            if(!row.includes('disabled') || !row.includes('target_unhealthy') || !row.includes('role="progressbar"')){
              throw new Error('blocked target row missing: ' + row);
            }
            const confirm = policyHelpers.exitSwitchConfirmHTML('us', 14);
            if(!confirm.includes('14') || !confirm.includes('including disabled') || !confirm.includes('briefly reconnect')){
              throw new Error('confirmation copy missing: ' + confirm);
            }
            policy.exits.nl.used = policy.exits.nl.quota;
            policyHelpers.renderExitPolicy(policy);
            if(!element('monthuse-nl').classList.contains('critical') || element('monthuse-nl').classList.contains('warn')){
              throw new Error('critical quota state missing');
            }
            const noChange = {
              auto_switch: false,
              exits: {
                nl: {used: 0, quota: 500 * 1024 ** 3, clients: 0, healthy: true, checked_age: 1, exhausted: false},
                us: {used: 0, quota: 750 * 1024 ** 3, clients: 14, healthy: true, checked_age: 1, exhausted: false}
              }, blocked: null, last_switch: null, warning: null
            };
            policyHelpers.renderExitPolicy(noChange);
            const noChangeRow = policyHelpers.exitPolicyRowHTML('us', noChange.exits.us);
            if(!noChangeRow.includes('disabled') || !noChangeRow.includes('no_clients_to_switch')){
              throw new Error('no-op target must be disabled: ' + noChangeRow);
            }
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_baseline_malformed_status_and_integer_validation_are_safe(self):
        self.run_node(
            r"""
            const base = {
              auto_switch: true,
              exits: {
                nl: {used: 1, quota: 100, clients: 1, healthy: true, checked_age: 1, exhausted: false},
                us: {used: 2, quota: 100, clients: 0, healthy: true, checked_age: 1, exhausted: false}
              }, blocked: null, warning: null,
              last_switch: {ts: 100, reason: 'quota', target: 'us'}
            };
            policyHelpers.renderExitPolicy(base);
            if(element('toast').textContent) throw new Error('initial last_switch must establish a silent baseline');
            policyHelpers.renderExitPolicy({...base, last_switch: {ts: 101, reason: 'quota', target: 'nl'}});
            if(!element('toast').textContent.includes('NL')) throw new Error('new quota switch should toast');

            policyHelpers.renderExitPolicy(undefined);
            policyHelpers.renderExitPolicy({});
            policyHelpers.renderExitPolicy({exits: {nl: null}});
            const malicious = {...base, blocked: {code: '<img src=x onerror=alert(1)>'}, last_switch: null};
            policyHelpers.renderExitPolicy(malicious);
            if(element('policyalert').innerHTML.includes('<img')) throw new Error('blocked policy content was not escaped');

            if(policyHelpers.policyRequestBody(true, '', '750') !== null) throw new Error('empty quota accepted');
            if(policyHelpers.policyRequestBody(true, '500.5', '750') !== null) throw new Error('fractional quota accepted');
            if(policyHelpers.policyRequestBody(true, '1000001', '750') !== null) throw new Error('oversized quota accepted');
            if(policyHelpers.policyRequestBody(true, '500', '750').quotas_gib.nl !== 500) throw new Error('integer quota rejected');
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_mutations_prevent_duplicates_and_restore_loading_controls(self):
        self.run_node(
            r"""
            (async () => {
              const active = {
                auto_switch: true,
                exits: {
                  nl: {used: 1, quota: 500 * 1024 ** 3, clients: 14, healthy: true, checked_age: 1, exhausted: false},
                  us: {used: 2, quota: 750 * 1024 ** 3, clients: 0, healthy: true, checked_age: 1, exhausted: false}
                }, blocked: null, last_switch: null, warning: null
              };
              policyHelpers.renderExitPolicy(active);
              element('xpq-nl').value = '500';
              element('xpq-us').value = '750';
              element('xpauto').checked = true;
              element('xpsave').innerHTML = 'Save';
              let resolveSave;
              const calls = [];
              context.fetch = (url, options) => {
                calls.push(JSON.parse(options.body));
                return new Promise(resolve => { resolveSave = resolve; });
              };
              const firstSave = policyHelpers.saveExitPolicy();
              const duplicateSave = policyHelpers.saveExitPolicy();
              if(calls.length !== 1 || !element('xpsave').disabled || !element('xpsave').textContent.includes('Saving')){
                throw new Error('save duplicate/loading guard missing');
              }
              resolveSave({status: 400, json: async () => ({ok:false,error:'recoverable'})});
              await Promise.all([firstSave, duplicateSave]);
              if(element('xpsave').disabled || !element('xperr').textContent.includes('recoverable')){
                throw new Error('save control did not recover');
              }

              let resolveBulk;
              context.fetch = (url, options) => {
                calls.push(JSON.parse(options.body));
                return new Promise(resolve => { resolveBulk = resolve; });
              };
              element('xpswitch').innerHTML = 'Switch all';
              const firstBulk = policyHelpers.doExitAll('us');
              const duplicateBulk = policyHelpers.doExitAll('us');
              if(calls.length !== 2 || !element('xpswitch').disabled || !element('xpswitch').textContent.includes('Switching')){
                throw new Error('bulk duplicate/loading guard missing');
              }
              const bulkBody = calls[1];
              if(JSON.stringify(bulkBody) !== JSON.stringify({op:'setexitall',exit:'us'}) || 'force' in bulkBody){
                throw new Error('bad bulk payload ' + JSON.stringify(bulkBody));
              }
              resolveBulk({status: 400, json: async () => ({ok:false,code:'target_stale'})});
              await Promise.all([firstBulk, duplicateBulk]);
              if(element('xpswitch').disabled || !element('xperr').textContent.includes('target_stale')){
                throw new Error('bulk control did not recover');
              }
            })().catch(error => { console.error(error); process.exitCode = 1; });
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_replacing_policy_modal_preserves_original_focus_target(self):
        self.run_node(
            r"""
            const trigger = element('monthuse-nl');
            const nestedControl = element('nested-control');
            document.activeElement = trigger;
            policyHelpers.openModal('<div class="mtitle">Exit routing</div>');
            document.activeElement = nestedControl;
            policyHelpers.openModal('<div class="mtitle">Confirm</div>');
            policyHelpers.closeModal();
            if(!trigger.focused || nestedControl.focused){
              throw new Error('modal replacement lost the original focus return target');
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
