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
const documentListeners = new Map();
const windowListeners = new Map();
const timers = new Map();
let nextTimer = 1;

function attrDataKey(name){
  return name.slice(5).replace(/-([a-z])/g, (_,c) => c.toUpperCase());
}
function selectorMatch(el, raw){
  let selector = raw.trim();
  if(!selector) return false;
  const nots = [];
  selector = selector.replace(/:not\(([^)]+)\)/g, (_,part) => { nots.push(part); return ''; });
  if(nots.some(part => selectorMatch(el, part))) return false;
  const tag = selector.match(/^[a-z][a-z0-9-]*/i);
  if(tag && el.tagName !== tag[0].toUpperCase()) return false;
  for(const match of selector.matchAll(/\.([a-z0-9_-]+)/gi)){
    if(!el.classList.contains(match[1])) return false;
  }
  for(const match of selector.matchAll(/\[([a-z0-9_-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/gi)){
    const name = match[1], expected = match[2] ?? match[3] ?? (match[4] && match[4].trim());
    const actual = el.getAttribute(name);
    if(actual === null || (expected !== undefined && actual !== expected)) return false;
  }
  return true;
}
function matchesAny(el, selector){
  return selector.split(',').some(part => selectorMatch(el, part));
}

class FakeClassList {
  constructor(owner){ this.owner = owner; this.values = new Set(); }
  fromString(value){ this.values = new Set(String(value || '').split(/\s+/).filter(Boolean)); }
  sync(){ this.owner._className = [...this.values].join(' '); }
  add(...xs){ xs.forEach(x => this.values.add(x)); this.sync(); }
  remove(...xs){ xs.forEach(x => this.values.delete(x)); this.sync(); }
  contains(x){ return this.values.has(x); }
  toggle(x,on){
    if(on === undefined) on = !this.values.has(x);
    on ? this.values.add(x) : this.values.delete(x);
    this.sync();
    return on;
  }
}

function connectTree(node, connected){
  node.isConnected = connected;
  if(node.id){
    if(connected) elements.set(node.id, node);
    else if(elements.get(node.id) === node) elements.delete(node.id);
  }
  node.children.forEach(child => connectTree(child, connected));
}
function detachTree(node){ connectTree(node, false); }

class FakeElement {
  constructor(tag='div'){
    this.tagName = tag.toUpperCase();
    this.id = '';
    this.parentElement = null;
    this.children = [];
    this._attrs = {};
    this.dataset = {};
    this.style = {};
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.hidden = false;
    this.isConnected = false;
    this._className = '';
    this.classList = new FakeClassList(this);
    this._innerHTML = '';
    this._textContent = '';
    this.innerHTMLWrites = 0;
    this.listeners = new Map();
  }
  get className(){ return this._className; }
  set className(value){ this._className = String(value || ''); this.classList.fromString(value); }
  get offsetParent(){ return this.isConnected && !this.hidden && this.style.display !== 'none' ? {} : null; }
  get firstChild(){ return this.children[0] || null; }
  get innerHTML(){ return this._innerHTML; }
  set innerHTML(value){
    this.children.forEach(detachTree);
    this.children = [];
    this._innerHTML = String(value == null ? '' : value);
    this._textContent = '';
    this.innerHTMLWrites += 1;
    parseHTML(this._innerHTML, this);
  }
  get textContent(){ return this._textContent; }
  set textContent(value){
    this.children.forEach(detachTree);
    this.children = [];
    this._innerHTML = '';
    this._textContent = String(value == null ? '' : value);
  }
  setAttribute(name,value){
    const string = String(value);
    this._attrs[name] = string;
    if(name === 'id'){
      if(this.id && elements.get(this.id) === this) elements.delete(this.id);
      this.id = string;
      if(this.isConnected) elements.set(this.id, this);
    }else if(name === 'class'){
      this.className = string;
    }else if(name.startsWith('data-')){
      this.dataset[attrDataKey(name)] = string;
    }else if(name === 'disabled'){
      this.disabled = true;
    }else if(name === 'checked'){
      this.checked = true;
    }else if(name === 'value'){
      this.value = string;
    }else if(name === 'hidden'){
      this.hidden = true;
    }
  }
  getAttribute(name){
    if(name === 'id') return this.id || null;
    if(name === 'class') return this.className || null;
    if(name === 'disabled') return this.disabled ? '' : null;
    if(name === 'checked') return this.checked ? '' : null;
    if(name === 'value') return this.value;
    if(name === 'hidden') return this.hidden ? '' : null;
    if(name.startsWith('data-')){
      const value = this.dataset[attrDataKey(name)];
      return value === undefined ? null : String(value);
    }
    return Object.prototype.hasOwnProperty.call(this._attrs,name) ? this._attrs[name] : null;
  }
  removeAttribute(name){
    delete this._attrs[name];
    if(name === 'disabled') this.disabled = false;
    else if(name === 'checked') this.checked = false;
    else if(name === 'hidden') this.hidden = false;
    else if(name.startsWith('data-')) delete this.dataset[attrDataKey(name)];
  }
  appendChild(child){
    if(child.parentElement) child.parentElement.removeChild(child);
    this.children.push(child);
    child.parentElement = this;
    connectTree(child, this.isConnected);
    return child;
  }
  prepend(child){
    if(child.parentElement) child.parentElement.removeChild(child);
    this.children.unshift(child);
    child.parentElement = this;
    connectTree(child, this.isConnected);
    return child;
  }
  removeChild(child){
    const index = this.children.indexOf(child);
    if(index >= 0) this.children.splice(index,1);
    child.parentElement = null;
    detachTree(child);
    return child;
  }
  remove(){ if(this.parentElement) this.parentElement.removeChild(this); else detachTree(this); }
  replaceWith(replacement){
    if(!this.parentElement) return;
    const parent = this.parentElement, index = parent.children.indexOf(this);
    parent.removeChild(this);
    if(replacement.parentElement) replacement.parentElement.removeChild(replacement);
    parent.children.splice(index,0,replacement);
    replacement.parentElement = parent;
    connectTree(replacement,parent.isConnected);
  }
  contains(node){
    for(let cur=node;cur;cur=cur.parentElement) if(cur === this) return true;
    return false;
  }
  querySelectorAll(selector){
    const found = [];
    const walk = node => node.children.forEach(child => {
      if(matchesAny(child,selector)) found.push(child);
      walk(child);
    });
    walk(this);
    return found;
  }
  querySelector(selector){ return this.querySelectorAll(selector)[0] || null; }
  closest(selector){
    for(let cur=this;cur;cur=cur.parentElement) if(matchesAny(cur,selector)) return cur;
    return null;
  }
  addEventListener(type,listener){
    if(!this.listeners.has(type)) this.listeners.set(type,[]);
    this.listeners.get(type).push(listener);
  }
  dispatchEvent(event){
    if(!event.target) event.target = this;
    for(let cur=this;cur;cur=cur.parentElement){
      event.currentTarget = cur;
      for(const listener of cur.listeners.get(event.type) || []) listener(event);
      if(event.propagationStopped) return !event.defaultPrevented;
    }
    document.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  focus(){ if(this.isConnected){ this.focused = true; document.activeElement = this; } }
  select(){}
  click(){ return this.dispatchEvent(makeEvent('click',this)); }
  insertAdjacentHTML(position,html){
    if(position === 'afterbegin'){
      const holder = new FakeElement('div');holder.isConnected = this.isConnected;parseHTML(html,holder);
      holder.children.slice().reverse().forEach(child => this.prepend(child));
    }else parseHTML(html,this);
  }
  insertAdjacentElement(position,node){ return position === 'beforebegin' && this.parentElement ? this.parentElement.prepend(node) : this.appendChild(node); }
}

const VOID_TAGS = new Set(['INPUT','IMG','BR','HR','META','LINK']);
function parseHTML(html,parent){
  const stack = [parent];
  const tokens = String(html).match(/<\/?[a-z][^>]*>|[^<]+/gi) || [];
  for(const token of tokens){
    if(token.startsWith('</')){ if(stack.length > 1) stack.pop(); continue; }
    if(!token.startsWith('<')){ stack[stack.length-1]._textContent += token; continue; }
    const open = token.match(/^<([a-z0-9-]+)([^>]*)>/i);if(!open)continue;
    const node = new FakeElement(open[1]);
    const attrs = open[2] || '';
    for(const match of attrs.matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)){
      node.setAttribute(match[1],match[2] ?? match[3] ?? match[4] ?? '');
    }
    stack[stack.length-1].appendChild(node);
    if(!VOID_TAGS.has(node.tagName) && !token.endsWith('/>')) stack.push(node);
  }
}

let document = {};
const body = new FakeElement('body');
body.isConnected = true;
Object.assign(document,{
  body,
  activeElement: null,
  documentElement: {lang:'en'},
  createElement(tag){ return new FakeElement(tag); },
  getElementById(id){ const found=elements.get(id);return found&&found.isConnected?found:null; },
  querySelector(selector){
    if(selector === 'meta[name=csrf]') return {content:'csrf'};
    return body.querySelector(selector);
  },
  querySelectorAll(selector){ return body.querySelectorAll(selector); },
  addEventListener(type,listener){
    if(!documentListeners.has(type)) documentListeners.set(type,[]);
    documentListeners.get(type).push(listener);
  },
  dispatchEvent(event){
    if(!event.target) event.target = document;
    event.currentTarget = document;
    for(const listener of documentListeners.get(event.type) || []) listener(event);
    return !event.defaultPrevented;
  },
  createTreeWalker(){ return {nextNode(){ return null; }}; }
});

function mount(tag,id,parent=body){
  const node = new FakeElement(tag);node.setAttribute('id',id);parent.appendChild(node);return node;
}
function element(id){ return document.getElementById(id) || mount('div',id); }
function makeEvent(type,target,extra={}){
  return Object.assign({type,target,currentTarget:null,defaultPrevented:false,propagationStopped:false,
    preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.propagationStopped=true;}},extra);
}
function runTimers(maxDelay=Infinity){
  const due=[...timers.entries()].filter(([,timer])=>timer.delay<=maxDelay);
  due.forEach(([id,timer])=>{timers.delete(id);timer.fn();});
}
function visibleText(html){ return String(html).replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim(); }
function response(payload,status=200){ return {status,json:async()=>payload}; }

const mbgNode=mount('div','mbg');
const modalNode=mount('div','modal',mbgNode);modalNode.setAttribute('tabindex','-1');
[
 ['button','monthuse-nl'],['button','monthuse-us'],['div','policyalert'],['div','toast'],
 ['div','offline'],['div','upd'],['div','cards'],['div','hostbar'],['svg','spark'],
 ['div','sparkticks'],['div','sparkymax'],['div','viewfilt'],['div','exitfilt'],['div','csum'],
 ['button','lang'],['button','acctbtn'],['button','morebtn'],['input','csearch'],['div','tline'],
 ['div','alert'],['div','cascade'],['div','thr'],['div','chartnow'],['div','charttip']
].forEach(([tag,id])=>mount(tag,id));
element('monthuse-nl').setAttribute('data-act','exit-policy');
element('monthuse-us').setAttribute('data-act','exit-policy');

const fakeWindow={
  matchMedia(){return{matches:true};},
  addEventListener(type,listener){
    if(!windowListeners.has(type))windowListeners.set(type,[]);
    windowListeners.get(type).push(listener);
  }
};
const context={
  console,require,document,NodeFilter:{SHOW_TEXT:4},navigator:{},window:fakeWindow,
  localStorage:{getItem(){return'en';},setItem(){}},
  requestAnimationFrame(){return 0;},cancelAnimationFrame(){},
  setTimeout(fn,delay=0){const id=nextTimer++;timers.set(id,{fn,delay});return id;},
  clearTimeout(id){timers.delete(id);},setInterval(){return 0;},
  fetch(){return Promise.reject(new Error('network disabled in test'));},
  location:{href:'',reload(){}},performance:{now(){return 0;}},
  matchMedia:fakeWindow.matchMedia
};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(
  fs.readFileSync('app/app.js','utf8')+
  fs.readFileSync('app/clients.js','utf8')+
  '\nglobalThis.__monthlyTest={trafficTotals,peersByExit,clientExit,monthSummaryHTML,renderUsage};'+
  '\nglobalThis.__policyTest={monthExitHTML,renderExitPolicy,exitPolicyRowHTML,exitSwitchConfirmHTML,policyRequestBody,bulkTargetBlock,saveExitPolicy,doExitAll,openModal,closeModal,openExitRouting,confirmExitAll,policyReason,focusables};'+
  '\nglobalThis.__setLanguageForTest=function(value){LANG=value;};',
  context,{filename:'app/app.js'}
);
const monthly=context.__monthlyTest;
const policyHelpers=context.__policyTest;
function activePolicy(){
  return {auto_switch:true,exits:{
    nl:{used:1,quota:500*1024**3,clients:14,healthy:true,checked_age:1,exhausted:false},
    us:{used:2,quota:750*1024**3,clients:0,healthy:true,checked_age:1,exhausted:false}
  },blocked:null,last_switch:null,warning:null};
}
"""


class TestFrontendMonthlyTraffic(unittest.TestCase):
    def run_node(self, body):
        script = textwrap.dedent(NODE_SETUP + "\n" + body)
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_header_has_accessible_exit_policy_controls(self):
        html = (ROOT / "app" / "index.html").read_text()
        self.assertIn('<header class="topnav">', html)
        self.assertIn('<section class="status-strip">', html)
        self.assertIn('id="monthuse"', html)
        self.assertIn('button class="pill monthpill" id="monthuse-nl"', html)
        self.assertIn('button class="pill monthpill" id="monthuse-us"', html)
        self.assertIn('data-act="exit-policy"', html)
        self.assertIn('aria-label="NL exit routing settings"', html)
        self.assertIn('aria-label="US exit routing settings"', html)
        self.assertIn('id="policyalert" style="display:none" role="alert"', html)

    def test_policy_alert_css_uses_explicit_aa_text_without_nested_opacity(self):
        css = (ROOT / "app" / "app.css").read_text()
        self.assertRegex(css, r"\.policyalert\{[^}]*color:var\(--txt\)")
        self.assertRegex(css, r"\.policyalert span\{[^}]*opacity:1")
        self.assertNotRegex(css, r"\.policyalert(?:-detail|>span)[^{]*\{[^}]*opacity:\s*\.(?:[0-9]+)")
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        self.assertIn("@media(max-width:560px)", css)

    def test_service_worker_cache_is_bumped(self):
        self.assertIn("wgui-shell-v26", (ROOT / "app" / "sw.js").read_text())
        self.assertIn("cacheablePath", (ROOT / "app" / "sw.js").read_text())

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_monthly_helpers_still_render_usage_history(self):
        self.run_node(
            r"""
            const totals=monthly.trafficTotals([{mrx:1024,mtx:2048},{mrx:512,mtx:0},{mrx:null,mtx:256}],'mrx','mtx');
            if(totals.rx!==1536||totals.tx!==2304)throw new Error('unexpected totals '+JSON.stringify(totals));
            const peers=[{exit:'nl'},{exit:'us'},{exit:null}];
            if(monthly.peersByExit(peers,'nl').length!==2||monthly.peersByExit(peers,'us').length!==1)throw new Error('unexpected exit partition');
            element('ubody');monthly.renderUsage({daily:[],clients:[]});
            const html=element('ubody').innerHTML;
            if(!html.includes('Month')||!html.includes('0.0 B'))throw new Error('empty usage modal missing totals: '+html);
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_server_policy_renders_thresholds_progress_and_guarded_actions(self):
        self.run_node(
            r"""
            const policy=activePolicy();
            policy.exits.nl.used=495*1024**3;
            policy.exits.us.healthy=false;
            policy.blocked={code:'target_unhealthy',source:'nl',target:'us'};
            policyHelpers.renderExitPolicy(policy);
            if(!element('monthuse-nl').innerHTML.includes('495.0 GiB')||!element('monthuse-nl').classList.contains('warn'))throw new Error('NL warning missing');
            if(element('monthuse-nl').classList.contains('critical'))throw new Error('warning cannot be critical');
            if(!element('policyalert').classList.contains('show'))throw new Error('blocked banner missing');
            if(policyHelpers.bulkTargetBlock(policy,'us')!=='target_unhealthy')throw new Error('unhealthy target allowed');
            const requestBody=policyHelpers.policyRequestBody(true,'500','750');
            if(JSON.stringify(requestBody)!==JSON.stringify({op:'setexitpolicy',auto_switch:true,quotas_gib:{nl:500,us:750}}))throw new Error('bad payload');
            const failBody=policyHelpers.policyRequestBody(true,'500','750',false);
            if(failBody.health_failover!==false)throw new Error('failover flag not sent');
            for(const code of ['both_unhealthy','failover_cooldown']){
              if(/^[_a-z]+$/.test(policyHelpers.policyReason(code)))throw new Error('raw failover code: '+code);
            }
            const row=policyHelpers.exitPolicyRowHTML('us',policy.exits.us),rowText=visibleText(row);
            if(!row.includes('disabled')||!row.includes('role="progressbar"'))throw new Error('blocked target row missing');
            if(rowText.includes('target_unhealthy'))throw new Error('raw reason visible: '+rowText);
            const confirm=policyHelpers.exitSwitchConfirmHTML('us',14);
            if(!confirm.includes('14')||!confirm.includes('including disabled')||!confirm.includes('briefly reconnect'))throw new Error('confirmation copy missing');
            policy.exits.nl.used=policy.exits.nl.quota;
            policyHelpers.renderExitPolicy(policy);
            if(!element('monthuse-nl').classList.contains('critical')||element('monthuse-nl').classList.contains('warn'))throw new Error('critical state missing');
            const noChange=activePolicy();noChange.exits.nl.clients=0;noChange.exits.us.clients=14;
            policyHelpers.renderExitPolicy(noChange);
            const noChangeText=visibleText(policyHelpers.exitPolicyRowHTML('us',noChange.exits.us));
            if(noChangeText.includes('no_clients_to_switch')||!noChangeText.includes('already'))throw new Error('no-op copy invalid: '+noChangeText);
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_reason_copy_is_localized_and_never_exposes_server_codes(self):
        self.run_node(
            r"""
            const codes=['invalid_target','target_unhealthy','target_stale','target_exhausted','both_exhausted','counter_unavailable','helper_failed','missing_policy','invalid_policy','no_clients_to_switch'];
            for(const code of codes){
              const message=policyHelpers.policyReason(code);
              if(message.includes(code)||/^[_a-z]+$/.test(message))throw new Error('raw English policy code: '+code+' => '+message);
            }
            const counter=policyHelpers.policyReason('counter_unavailable');
            if(!/current.*target.*counter/i.test(counter))throw new Error('counter copy is not actionable: '+counter);
            const unknown=policyHelpers.policyReason('future_server_identifier');
            if(unknown.includes('future_server_identifier')||!unknown.includes('blocked'))throw new Error('unknown code fallback leaked: '+unknown);
            policyHelpers.renderExitPolicy({...activePolicy(),blocked:{code:'future_server_identifier'}});
            if(visibleText(element('policyalert').innerHTML).includes('future_server_identifier'))throw new Error('alert leaked unknown code');
            context.__setLanguageForTest('ru');
            for(const code of codes){
              const message=policyHelpers.policyReason(code);
              if(message.includes(code)||/^[_a-z]+$/.test(message))throw new Error('raw Russian policy code: '+code+' => '+message);
            }
            if(!/сч[её]тчик|данн/i.test(policyHelpers.policyReason('counter_unavailable')))throw new Error('Russian counter copy missing');
            if(policyHelpers.policyReason('future_server_identifier').includes('future_server_identifier'))throw new Error('Russian fallback leaked code');
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_alert_only_mutates_when_signature_changes_or_clears(self):
        self.run_node(
            r"""
            const alert=element('policyalert'),base=activePolicy();
            const blocked={...base,blocked:{code:'target_stale'}};
            const before=alert.innerHTMLWrites;
            policyHelpers.renderExitPolicy(blocked);
            const shown=alert.innerHTMLWrites;
            policyHelpers.renderExitPolicy(blocked);
            if(alert.innerHTMLWrites!==shown||shown!==before+1)throw new Error('unchanged alert retriggered');
            policyHelpers.renderExitPolicy({...base,blocked:{code:'counter_unavailable'}});
            if(alert.innerHTMLWrites!==shown+1)throw new Error('changed alert was not announced');
            const changed=alert.innerHTMLWrites;
            policyHelpers.renderExitPolicy(base);
            if(alert.innerHTMLWrites!==changed+1||alert.style.display!=='none')throw new Error('clear mutation missing');
            policyHelpers.renderExitPolicy(base);
            if(alert.innerHTMLWrites!==changed+1)throw new Error('unchanged clear retriggered');
            policyHelpers.renderExitPolicy(undefined);
            const unavailable=alert.innerHTMLWrites;
            policyHelpers.renderExitPolicy({});
            if(alert.innerHTMLWrites!==unavailable)throw new Error('unchanged unavailable alert retriggered');
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_baseline_malformed_status_and_integer_validation_are_safe(self):
        self.run_node(
            r"""
            const base=activePolicy();base.last_switch={ts:100,reason:'quota',target:'us'};
            policyHelpers.renderExitPolicy(base);
            if(element('toast').textContent||visibleText(element('toast').innerHTML))throw new Error('initial last_switch must be silent');
            policyHelpers.renderExitPolicy({...base,last_switch:{ts:101,reason:'quota',target:'nl'}});
            if(!(element('toast').textContent+visibleText(element('toast').innerHTML)).includes('NL'))throw new Error('new quota switch should toast');
            policyHelpers.renderExitPolicy(undefined);policyHelpers.renderExitPolicy({});policyHelpers.renderExitPolicy({exits:{nl:null}});
            const malicious={...base,blocked:{code:'<img src=x onerror=alert(1)>'},last_switch:null};
            policyHelpers.renderExitPolicy(malicious);
            if(element('policyalert').innerHTML.includes('<img')||visibleText(element('policyalert').innerHTML).includes('onerror'))throw new Error('blocked content was not sanitized');
            if(policyHelpers.policyRequestBody(true,'','750')!==null)throw new Error('empty quota accepted');
            if(policyHelpers.policyRequestBody(true,'500.5','750')!==null)throw new Error('fractional quota accepted');
            if(policyHelpers.policyRequestBody(true,'1000001','750')!==null)throw new Error('oversized quota accepted');
            if(policyHelpers.policyRequestBody(true,'500','750').quotas_gib.nl!==500)throw new Error('integer quota rejected');
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_real_delegation_keyboard_focus_trap_and_focus_return(self):
        self.run_node(
            r"""
            policyHelpers.renderExitPolicy(activePolicy());
            const trigger=element('monthuse-nl');trigger.focus();
            const nested=trigger.querySelector('.msum');
            if(!nested||nested.closest('[data-act]')!==trigger)throw new Error('realistic closest tree missing');
            nested.dispatchEvent(makeEvent('click',nested));
            if(!element('mbg').classList.contains('show')||!element('modal').innerHTML.includes('Exit routing'))throw new Error('nested delegated action did not open modal');
            runTimers(30);
            if(document.activeElement.id!=='xpq-nl')throw new Error('initial modal focus missing: '+(document.activeElement&&document.activeElement.id));
            const focusable=policyHelpers.focusables(element('modal'));
            const first=focusable[0],last=focusable[focusable.length-1];
            last.focus();const tab=makeEvent('keydown',last,{key:'Tab',shiftKey:false});document.dispatchEvent(tab);
            if(!tab.defaultPrevented||document.activeElement!==first)throw new Error('forward Tab trap failed');
            first.focus();const shiftTab=makeEvent('keydown',first,{key:'Tab',shiftKey:true});document.dispatchEvent(shiftTab);
            if(!shiftTab.defaultPrevented||document.activeElement!==last)throw new Error('reverse Tab trap failed');
            const escape=makeEvent('keydown',last,{key:'Escape'});document.dispatchEvent(escape);
            if(element('mbg').classList.contains('show')||document.activeElement!==trigger)throw new Error('Escape close/focus return failed');
            nested.dispatchEvent(makeEvent('click',nested));
            const close=element('modal').querySelector('[data-act="close"]'),closeChild=new FakeElement('span');close.appendChild(closeChild);
            closeChild.dispatchEvent(makeEvent('click',closeChild));
            if(element('mbg').classList.contains('show'))throw new Error('nested close action delegation failed');
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_policy_mutations_prevent_duplicates_and_restore_live_controls(self):
        self.run_node(
            r"""
            (async()=>{
              policyHelpers.renderExitPolicy(activePolicy());
              policyHelpers.openExitRouting();
              let resolveSave;const calls=[];
              context.fetch=(url,options)=>{calls.push(JSON.parse(options.body));return new Promise(resolve=>{resolveSave=resolve;});};
              const first=policyHelpers.saveExitPolicy(),duplicate=policyHelpers.saveExitPolicy();
              const saveButton=element('xpsave');
              if(calls.length!==1||!saveButton.disabled||!saveButton.textContent.includes('Saving'))throw new Error('save duplicate/loading guard missing');
              resolveSave(response({ok:false,error:'recoverable'},400));await Promise.all([first,duplicate]);
              if(saveButton.disabled||!element('xperr').textContent.includes('blocked'))throw new Error('save control did not recover safely');
              policyHelpers.confirmExitAll('us');
              let resolveBulk;
              context.fetch=(url,options)=>{calls.push(JSON.parse(options.body));return new Promise(resolve=>{resolveBulk=resolve;});};
              const bulk=policyHelpers.doExitAll('us'),bulkDuplicate=policyHelpers.doExitAll('us');
              const bulkButton=element('xpswitch');
              if(calls.length!==2||!bulkButton.disabled||!bulkButton.textContent.includes('Switching'))throw new Error('bulk duplicate/loading guard missing');
              if(JSON.stringify(calls[1])!==JSON.stringify({op:'setexitall',exit:'us'})||'force' in calls[1])throw new Error('bad bulk payload');
              resolveBulk(response({ok:false,code:'target_stale'},400));await Promise.all([bulk,bulkDuplicate]);
              if(bulkButton.disabled||!element('xperr').textContent.includes('stale')||element('xperr').textContent.includes('target_stale'))throw new Error('bulk control did not recover safely');
            })().catch(error=>{console.error(error);process.exitCode=1;});
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_save_and_bulk_ignore_closed_or_replaced_modal_on_success_and_failure(self):
        self.run_node(
            r"""
            (async()=>{
              policyHelpers.renderExitPolicy(activePolicy());
              for(const kind of ['save','bulk'])for(const outcome of ['failure','success'])for(const transition of ['close','replace']){
                policyHelpers.openExitRouting();
                if(kind==='bulk')policyHelpers.confirmExitAll('us');
                const button=element(kind==='save'?'xpsave':'xpswitch'),error=element('xperr');
                let resolveAdmin,adminCalls=0;
                context.fetch=(url,options)=>{
                  if(url==='/api/admin'){adminCalls++;return new Promise(resolve=>{resolveAdmin=resolve;});}
                  return Promise.reject(new Error('status offline'));
                };
                const pending=kind==='save'?policyHelpers.saveExitPolicy():policyHelpers.doExitAll('us');
                if(adminCalls!==1||!button.disabled)throw new Error(kind+' request did not start');
                let newer='';
                if(transition==='close')policyHelpers.closeModal();
                else{policyHelpers.openModal('<div class="mtitle">Newer modal</div><button id="newer">Keep open</button>');newer=element('modal').innerHTML;}
                resolveAdmin(response(outcome==='success'?{ok:true}:{ok:false,code:'target_stale'},outcome==='success'?200:400));
                await pending;
                if(error.textContent)throw new Error(kind+' '+outcome+' wrote stale error after '+transition+': '+error.textContent);
                if(!button.disabled)throw new Error(kind+' restored a non-live originating button');
                if(transition==='replace'&&(!element('mbg').classList.contains('show')||element('modal').innerHTML!==newer))throw new Error(kind+' '+outcome+' closed/replaced newer modal');
                if(transition==='close'&&element('mbg').classList.contains('show'))throw new Error(kind+' '+outcome+' reopened closed modal');
              }
            })().catch(error=>{console.error(error);process.exitCode=1;});
            """
        )

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_success_unlocks_before_hanging_background_refresh(self):
        self.run_node(
            r"""
            (async()=>{
              policyHelpers.renderExitPolicy(activePolicy());policyHelpers.openExitRouting();
              let resolveAdmin,statusCalls=0;
              context.fetch=(url,options)=>{
                if(url==='/api/admin')return new Promise(resolve=>{resolveAdmin=resolve;});
                statusCalls++;return new Promise(()=>{});
              };
              let settled=false;const first=policyHelpers.saveExitPolicy().then(()=>{settled=true;});
              resolveAdmin(response({ok:true}));
              for(let i=0;i<12;i++)await Promise.resolve();
              if(!settled||statusCalls!==1)throw new Error('successful save stayed busy on hanging tick: settled='+settled+', statusCalls='+statusCalls);
              policyHelpers.openExitRouting();let secondCalls=0;
              context.fetch=(url,options)=>{if(url==='/api/admin'){secondCalls++;return Promise.resolve(response({ok:false,error:'failed'},400));}return Promise.reject(new Error('offline'));};
              await policyHelpers.saveExitPolicy();
              if(secondCalls!==1)throw new Error('global save busy state was not reset before refresh');
              await first;
            })().catch(error=>{console.error(error);process.exitCode=1;});
            """
        )


if __name__ == "__main__":
    unittest.main()
