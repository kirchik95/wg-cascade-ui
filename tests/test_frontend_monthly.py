#!/usr/bin/env python3
"""Front-end dashboard and shell: quota gauges, honest stale/outage/offline states,
plaque priority, texts for server codes, the client menu and action hooks.
NODE_SETUP is a small fake DOM that runs app/icons.js, core.js and dashboard.js in node."""
import os
import pathlib
import re
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
  insertBefore(child,ref){
    if(child.parentElement) child.parentElement.removeChild(child);
    const index = ref ? this.children.indexOf(ref) : -1;
    if(index >= 0) this.children.splice(index,0,child); else this.children.push(child);
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

let narrow=false;
const store=new Map([['wgui-lang',process.env.WGUI_TEST_LANG||'en']]);
['top','nav','age','ops','banner','view','tabbar','layer'].forEach(id=>mount('div',id));
mount('main','main');
const acct=mount('button','acct');acct.setAttribute('data-act','account');
const addbtn=mount('button','addbtn');addbtn.setAttribute('data-act','add-client');addbtn.setAttribute('data-live','');
const fakeWindow={
  matchMedia(q){return{matches:/max-width/.test(q)?narrow:false};},
  addEventListener(type,listener){
    if(!windowListeners.has(type))windowListeners.set(type,[]);
    windowListeners.get(type).push(listener);
  }
};
const context={
  console,require,document,NodeFilter:{SHOW_TEXT:4},navigator:{},window:fakeWindow,
  localStorage:{getItem(k){return store.has(k)?store.get(k):null;},setItem(k,v){store.set(k,String(v));}},
  requestAnimationFrame(){return 0;},cancelAnimationFrame(){},
  setTimeout(fn,delay=0){const id=nextTimer++;timers.set(id,{fn,delay});return id;},
  clearTimeout(id){timers.delete(id);},setInterval(){return 0;},
  fetch(){return Promise.reject(new Error('network disabled in test'));},
  location:{href:'',hash:'',reload(){}},performance:{now(){return 0;}},
  matchMedia:fakeWindow.matchMedia
};
context.globalThis=context;
vm.createContext(context);
for(const file of ['app/icons.js','app/core.js','app/dashboard.js'])
  vm.runInContext(fs.readFileSync(file,'utf8'),context,{filename:file});
const WG=context.WG;
runTimers(0);                                   // DOMContentLoaded equivalent: start() + first poll
const flush=async(n=8)=>{for(let i=0;i<n;i++)await Promise.resolve();};
const GiB=1024**3;
function exits(over){
  const base={nl:{ok:true,health:'up',health_since:1,checked_age:20,fails:0,affected_clients:0},
              us:{ok:true,health:'up',health_since:1,checked_age:18,fails:0,affected_clients:0}};
  return Object.assign(base,over||{});
}
function snapshot(over){
  const now=1790000000;
  const peers=[
    {name:'kirill-iphone',ip:'10.10.0.2',pubkey:'pk-a',enabled:true,online:true,age:12,endpoint:'198.51.100.10:51820',rx:1,tx:1,mrx:33*GiB,mtx:0,expires:0,exit:'nl',spark:[1,2,525000]},
    {name:'ipad',ip:'10.10.0.5',pubkey:'pk-b',enabled:true,online:false,age:3*86400,endpoint:'',rx:0,tx:0,mrx:11*GiB,mtx:0,expires:0,exit:'nl',spark:[]},
    {name:'guest-1',ip:'10.10.0.14',pubkey:'pk-c',enabled:false,online:false,age:-1,endpoint:'',rx:0,tx:0,mrx:0,mtx:0,expires:0,exit:'us',spark:[]}
  ];
  return Object.assign({now,snapshot_age:0,stale:false,rud:true,peers,
    host:{cpu:8,mem_used:0.6*GiB,mem_total:1.9*GiB,uptime:5*3600},
    thr:{series:[{t:now-5,down:100,up:10},{t:now,down:4500000,up:200000}],cur:{down:4500000,up:200000}},
    tunnel:{state:'up',affected_clients:0,exits:exits()},
    exit_policy:{auto_switch:true,health_failover:true,blocked:null,health_blocked:null,warning:null,last_switch:null,
      exits:{nl:{used:96*GiB,quota:1000*GiB,clients:2,healthy:true,checked_age:20,exhausted:false},
             us:{used:371*GiB,quota:500*GiB,clients:1,healthy:true,checked_age:18,exhausted:false}}}},over||{});
}
async function feed(snap){
  timers.clear();
  context.fetch=()=>Promise.resolve(response(snap));
  await WG._poll.tick();
  await flush();
}
function bannerText(){return visibleText(element('banner').innerHTML);}
function rowsHTML(body){return body.children.map(r=>r.children.map(c=>c.innerHTML).join('')).join('');}
"""


def run_node(test, body, lang="en", timeout=20):
    script = textwrap.dedent(NODE_SETUP + "\n" + body)
    env = dict(os.environ, WGUI_TEST_LANG=lang)
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    test.assertEqual(result.returncode, 0, result.stderr + result.stdout)
    test.assertIn("__OK__", result.stdout, "the test body did not run to the end:\n" + result.stderr)


class TestFrontendShell(unittest.TestCase):
    def test_shell_has_accessible_navigation_and_live_regions(self):
        html = (ROOT / "app" / "index.html").read_text()
        self.assertIn('<header class="top" id="top">', html)
        self.assertIn('<nav class="nav" id="nav" aria-label="Sections">', html)
        self.assertIn('<nav class="tabbar" id="tabbar" aria-label="Sections">', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('id="ops" role="status" aria-live="polite"', html)
        self.assertIn('class="banners" id="banner"', html)
        self.assertIn('<main class="main" id="main" tabindex="-1">', html)
        self.assertIn('class="skip" href="#main"', html)
        self.assertNotRegex(html, r"\son[a-z]+=")           # CSP: no inline handlers
        self.assertNotIn("<script>", html)                 # CSP: no inline scripts
        scripts = [u.replace("?v=__V__", "") for u in re.findall(r'<script src="([^"]+)"', html)]
        self.assertEqual(scripts[0], "/boot.js")
        self.assertEqual(scripts[1:], ["/icons.js", "/core.js", "/dashboard.js", "/modals.js", "/pages.js"])

    def test_design_system_css_tokens_themes_and_motion(self):
        css = (ROOT / "app" / "app.css").read_text()
        for token in ("--color-bg:#FFFFFF", "--color-ink:#15140F", "--color-amber:#FFB020",
                      "--color-amber-text:#A35F00", "--color-ok-text:#157A40", "--color-danger:#C2321B",
                      "--color-stale:#4A463A", "--radius-sheet:12px", "--spacing-touch:44px"):
            self.assertIn(token, css)
        self.assertIn(':root[data-theme="dark"]{', css)
        self.assertIn('@media (prefers-color-scheme: dark){\n :root[data-theme="auto"]{', css)
        self.assertIn("@media (prefers-reduced-motion:reduce)", css)
        self.assertIn("@media (max-width:600px)", css)
        self.assertNotRegex(css, r"font:\s*[0-9]{3}\s+[0-9.]+px\s+inherit")   # 'font: 600 13px inherit' is invalid CSS

    def test_service_worker_cache_is_bumped(self):
        sw = (ROOT / "app" / "sw.js").read_text()
        self.assertIn("wgui-shell-v29", sw)
        self.assertIn("cacheablePath", sw)
        for asset in ("/core.js", "/dashboard.js", "/icons.js", "/app.css"):
            self.assertIn("'%s?v='+V" % asset, sw)       # versioned URL, see asset_version() in wg-ui.py
        self.assertIn("SHELL.indexOf(p+u.search)", sw)
        for gone in ("/app.js", "/clients.js", "/cascade.js", "/inter.woff2"):
            self.assertNotIn("'%s'" % gone, sw)

    def test_core_header_documents_the_stage_contract(self):
        src = (ROOT / "app" / "core.js").read_text()
        head = src[:src.index("(function(){")]
        for name in ("WG.tr(", "WG.plural(", "WG.fmtBytes(", "WG.fmtMbit(", "WG.fmtAgo(", "WG.fmtDate(", "WG.esc(",
                     "WG.icon(", "WG.state", "WG.on('status'", "WG.api(", "WG.admin(", "WG.ops.run(",
                     "WG.modal.open(", "WG.modal.close()", "WG.confirm(", "WG.menu.open(", "WG.router.register(",
                     "WG.banner.set(", "WG.actions"):
            self.assertIn(name, head)
        for action in ("addClient()", "showConfig(pubkey", "editClient(pubkey)", "toggleEnabled(pubkey)",
                       "deleteClient(pubkey)", "switchExit(pubkey, exit)", "exitsSettings()", "revertSwitch(eventId)",
                       "splitSettings()", "backup()", "logoutAll()"):
            self.assertIn(action, head)


@unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
class TestFrontendDashboard(unittest.TestCase):
    def test_monthly_quota_gauges_follow_thresholds(self):
        run_node(self, r"""
        (async()=>{
          await feed(snapshot());
          const g=element('view').querySelector('.gauges').innerHTML;
          const us=g.slice(g.indexOf('data-exit="us"'));
          if(!/g-num is-warn">371</.test(us))throw new Error('74% must be amber: '+us.slice(0,300));
          const nl=g.slice(g.indexOf('data-exit="nl"'),g.indexOf('data-exit="us"'));
          if(!/g-num ">96</.test(nl)||nl.includes('is-warn">'))throw new Error('10% must stay ink');
          const bar=us.slice(us.indexOf('<span class="bar"'));
          if((bar.slice(0,bar.indexOf('</span>')).match(/class="is-warn/g)||[]).length!==15)throw new Error('74% fills 15 of 20 segments');
          const s=snapshot();s.exit_policy.exits.us.used=500*GiB;s.exit_policy.exits.us.exhausted=true;
          await feed(s);
          const full=element('view').querySelector('.gauges').innerHTML;
          if(!/g-num is-bad">500</.test(full))throw new Error('used-up quota must be red');
          if(!visibleText(full).includes('NL 2 · US 1'))throw new Error('cascade summary missing: '+visibleText(full));
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_stale_snapshot_is_grey_and_never_green_or_red(self):
        run_node(self, r"""
        (async()=>{
          const s=snapshot({stale:true,snapshot_age:372});
          s.tunnel.state='unknown';
          await feed(s);
          const view=element('view');
          const gauges=view.querySelector('.gauges').innerHTML,rows=rowsHTML(view.querySelector('.ct-body'));
          if(!visibleText(gauges).includes('Unknown'))throw new Error('stale must read Unknown');
          for(const bad of ['is-ok','is-bad','is-on"','dot is-warn'])
            if(gauges.includes(bad)||rows.includes(bad))throw new Error('stale data painted '+bad);
          if(!rows.includes('dot is-u'))throw new Error('was-online client must be grey');
          if(!/at \d\d:\d\d/.test(visibleText(rows)))throw new Error('handshake must read as a clock time: '+visibleText(rows));
          if(!bannerText().includes('Data is stale')||!bannerText().includes('6 min'))throw new Error('stale plaque missing: '+bannerText());
          if(!element('age').innerHTML.includes('ago'))throw new Error('top bar must show the data age');
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_outage_marks_clients_entry_ok_no_exit_and_wins_priority(self):
        run_node(self, r"""
        (async()=>{
          const s=snapshot();
          s.tunnel={state:'down',affected_clients:2,exits:exits({
            nl:{ok:false,health:'down',health_since:s.now-480,checked_age:20,fails:9,affected_clients:2},
            us:{ok:false,health:'down',health_since:s.now-480,checked_age:20,fails:9,affected_clients:0}})};
          s.exit_policy.exits.us.used=480*GiB;
          s.exit_policy.last_switch={ts:s.now-600,source:'us',target:'nl',reason:'health',changed:true,event_id:7,members_count:1,revert_of:null};
          await feed(s);
          const view=element('view');
          if(!visibleText(view.querySelector('.gauges').innerHTML).includes('Outage'))throw new Error('cascade must read Outage');
          const row=rowsHTML({children:[view.querySelector('.ct-body').children[0]]});
          if(!visibleText(row).includes('entry ok · no exit')||!row.includes('dot is-warn')||!row.includes('NL ×'))throw new Error('outage row wrong: '+visibleText(row));
          const html=element('banner').innerHTML;
          if(!/bn bn-crash/.test(html.slice(0,60)))throw new Error('outage plaque must be first: '+html.slice(0,120));
          if(!bannerText().includes('and 2 more'))throw new Error('failover and quota plaques must fold: '+bannerText());
          if(!bannerText().includes('Affected: 2 enabled, 1 of them connected'))throw new Error('affected counts missing: '+bannerText());
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_failover_plaque_offers_revert_only_when_the_source_is_healthy(self):
        run_node(self, r"""
        (async()=>{
          const calls=[];WG.actions.revertSwitch=id=>calls.push(id);
          const s=snapshot();
          s.exit_policy.last_switch={ts:s.now-1700,source:'us',target:'nl',reason:'health',changed:true,event_id:42,members_count:5,revert_of:null};
          await feed(s);
          if(!bannerText().includes('Move 5 back to US'))throw new Error('revert action missing: '+bannerText());
          element('banner').querySelector('[data-act="banner-act"]').click();
          if(calls.join()!=='42')throw new Error('revert must pass the event id: '+calls);
          const down=snapshot();down.exit_policy.last_switch=s.exit_policy.last_switch;
          down.tunnel.exits.us={ok:false,health:'down',health_since:down.now-60,checked_age:20,fails:4,affected_clients:0};
          await feed(down);
          if(bannerText().includes('Move 5 back')||!bannerText().includes('US does not answer')||!bannerText().includes('NL is available'))throw new Error('no revert onto a down exit: '+bannerText());
          const reverted=snapshot();reverted.exit_policy.last_switch=Object.assign({},s.exit_policy.last_switch,{event_id:43,revert_of:42});
          await feed(reverted);
          if(bannerText())throw new Error('a revert is not a failover: '+bannerText());
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_single_exit_failure_keeps_the_healthy_exit_available(self):
        run_node(self, r"""
        (async()=>{
          for(const failed of ['nl','us']){
            const healthy=failed==='nl'?'us':'nl',s=snapshot();
            s.peers.forEach(p=>{p.exit=failed});
            s.exit_policy.exits[failed].clients=3;s.exit_policy.exits[healthy].clients=0;
            s.tunnel.state='down';s.tunnel.affected_clients=2;
            s.tunnel.exits[failed]={ok:false,health:'down',health_since:s.now-300,checked_age:2,fails:3,affected_clients:2};
            await feed(s);
            const gauges=visibleText(element('view').querySelector('.gauges').innerHTML),banner=bannerText();
            for(const text of [gauges,banner]){
              if(/both exits|Outage/.test(text))throw new Error('a single exit failure became a total outage: '+text);
              if(!text.includes(failed.toUpperCase())||!text.includes(healthy.toUpperCase()+' is available'))throw new Error('healthy alternative is missing: '+text);
            }
          }
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_two_failed_exit_checks_are_an_outage_even_with_live_tunnels(self):
        run_node(self, r"""
        (async()=>{
          const s=snapshot();s.tunnel.state='degraded';
          for(const key of ['nl','us'])s.tunnel.exits[key]={ok:false,health:'down',wg_up:true,health_since:s.now-300,checked_age:2,fails:3,affected_clients:key==='nl'?2:0};
          await feed(s);
          if(WG.dashboard.mode(WG.state)!=='crash'||!bannerText().includes('Both exits are down'))throw new Error('both failed probes must mean outage: '+bannerText());
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_pending_and_unknown_exit_checks_never_claim_success(self):
        run_node(self, r"""
        (async()=>{
          for(const health of ['warn','unknown']){
            const s=snapshot();s.tunnel.state='up';s.exit_policy.exits.us.clients=0;
            s.tunnel.exits.us={ok:false,health:health==='warn'?'up':'unknown',checked_age:health==='warn'?1:-1,fails:health==='warn'?1:0,affected_clients:0};
            await feed(s);
            const gauges=element('view').querySelector('.gauges').innerHTML,scheme=visibleText(element('view').querySelector('.scheme').innerHTML);
            if(gauges.includes('g-state is-ok'))throw new Error('unverified checks claim Working');
            if(/US[^·]*·[^·]*· ok/.test(scheme))throw new Error('unverified scheme branch claims ok: '+scheme);
            if(!bannerText().includes(health==='warn'?'check 1/3':'status unknown'))throw new Error('check state absent from plaque: '+bannerText());
          }
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_unknown_snapshot_disables_every_client_action(self):
        run_node(self, r"""
        (async()=>{
          for(const state of [{loaded:false},{stale:true},{offline:true}]){
            const s=Object.assign(snapshot(),{loaded:true},state),p=s.peers[0];p.expires=s.now+3600;
            WG.state=s;
            const row=new FakeElement();row.innerHTML=WG.dashboard.rowHTML(s,WG.dashboard.mode(s),p);
            if(row.querySelectorAll('[data-live]').some(b=>!b.disabled))throw new Error('unknown row contains an active server action');
            if(WG.dashboard.clientMenu(p).some(it=>it.act&&!it.disabled))throw new Error('unknown client menu contains an active action');
          }
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_plaques_rerender_only_when_their_content_changes_and_escape_text(self):
        run_node(self, r"""
        (async()=>{
          const s=snapshot();s.exit_policy.exits.us.used=470*GiB;
          await feed(s);
          const box=element('banner'),before=box.innerHTMLWrites;
          await feed(s);await feed(s);
          if(box.innerHTMLWrites!==before)throw new Error('unchanged plaque re-rendered');
          if(!bannerText().includes('US used 94% of its monthly quota'))throw new Error('quota plaque: '+bannerText());
          const evil=snapshot();evil.exit_policy.blocked={code:'<img src=x onerror=alert(1)>'};
          await feed(evil);
          if(box.innerHTML.includes('<img')||bannerText().includes('onerror'))throw new Error('server code leaked into HTML');
          if(!bannerText().includes('Exit switching is blocked.'))throw new Error('unknown code needs the generic text: '+bannerText());
          await feed(snapshot());
          if(bannerText()||!box.hidden)throw new Error('plaques must clear');
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_reason_and_target_texts_never_expose_server_codes(self):
        body = r"""
        const codes=['invalid_target','target_unhealthy','target_stale','target_exhausted','both_exhausted','both_unhealthy',
          'failover_cooldown','counter_unavailable','helper_failed','missing_policy','invalid_policy','no_clients_to_switch'];
        for(const code of codes){
          const m=WG.reasonText(code);
          if(!m||m.includes(code)||/^[_a-z]+$/.test(m))throw new Error('raw code: '+code+' => '+m);
        }
        for(const code of ['target_unhealthy','target_exhausted','target_stale','target_unverified'])
          if(!WG.targetText(code)||WG.targetText(code).includes(code))throw new Error('target text: '+code);
        if(WG.reasonText('future_server_identifier').includes('future'))throw new Error('unknown code leaked');
        if(WG.lang==='ru'&&!/[а-я]/.test(WG.reasonText('counter_unavailable')))throw new Error('Russian text missing');
        console.log('__OK__');
        """
        run_node(self, body)
        run_node(self, body, lang="ru")

    def test_russian_plurals_units_and_ages(self):
        run_node(self, r"""
        const c=n=>WG.count(n,'client');
        if([c(1),c(2),c(5),c(11),c(21),c(22)].join('|')!=='1 клиент|2 клиента|5 клиентов|11 клиентов|21 клиент|22 клиента')
          throw new Error('plural forms: '+[c(1),c(2),c(5),c(11),c(21),c(22)]);
        if(WG.plural(3,{one:'{n} попытка',few:'{n} попытки',many:'{n} попыток'})!=='3 попытки')throw new Error('plural()');
        if(WG.fmtBytes(33*1024**3)!=='33.0 ГиБ'||WG.fmtBytes(0)!=='0 Б')throw new Error('bytes: '+WG.fmtBytes(33*1024**3));
        if(WG.fmtMbit(525000)!=='4.2 Мбит/с')throw new Error('Mbit/s is bytes/s × 8 / 1e6: '+WG.fmtMbit(525000));
        if(WG.fmtAgo(12)!=='12 с назад'||WG.fmtAgo(360)!=='6 мин назад'||WG.fmtAgo(3*86400)!=='3 дня назад')throw new Error('ages: '+WG.fmtAgo(3*86400));
        if(WG.fmtAgo(4,{suffix:false})!=='4 с')throw new Error('short age');
        if(WG.fmtClock(150)!=='2:30')throw new Error('clock');
        if(!/^\d{1,2} [а-я]{3}/.test(WG.fmtDate(Date.now()/1000)))throw new Error('date: '+WG.fmtDate(Date.now()/1000));
        if(WG.tr('Clients')!=='Клиенты')throw new Error('catalog');
        console.log('__OK__');
        """, lang="ru")

    def test_client_menu_blocks_a_down_or_used_up_exit_with_a_reason(self):
        run_node(self, r"""
        (async()=>{
          const s=snapshot();s.tunnel.exits.us={ok:false,health:'down',health_since:s.now-60,checked_age:20,fails:5,affected_clients:0};
          await feed(s);
          const items=WG.dashboard.clientMenu(WG.peer('pk-a'));
          const move=items.find(i=>i.icon==='switch-exit');
          if(!move.disabled||move.hint!=='US is down')throw new Error('down target must be blocked: '+JSON.stringify(move));
          const q=snapshot();q.exit_policy.exits.us.exhausted=true;await feed(q);
          const m2=WG.dashboard.clientMenu(WG.peer('pk-a')).find(i=>i.icon==='switch-exit');
          if(!m2.disabled||!/quota/.test(m2.hint))throw new Error('used-up target must be blocked: '+m2.hint);
          const ok=snapshot();await feed(ok);
          const m3=WG.dashboard.clientMenu(WG.peer('pk-a')).find(i=>i.icon==='switch-exit');
          if(m3.disabled||m3.hint!=='US ok · 74%'||m3.hintTone!=='warn')throw new Error('healthy target: '+JSON.stringify(m3));
          const off=WG.dashboard.clientMenu(WG.peer('pk-c'));
          if(!off.some(i=>i.label==='Turn on'))throw new Error('disabled client offers Turn on');
          if(!items.some(i=>i.danger&&i.icon==='delete'))throw new Error('delete must be the danger item');
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_actions_go_through_hooks_and_offline_disables_live_buttons(self):
        run_node(self, r"""
        (async()=>{
          const seen=[];
          Object.assign(WG.actions,{showConfig:pk=>seen.push('qr:'+pk),toggleEnabled:pk=>seen.push('on:'+pk),addClient:()=>seen.push('add')});
          await feed(snapshot());
          const rows=element('view').querySelector('.ct-body').children;
          rows[0].querySelector('[data-act="cl-qr"]').click();
          rows[2].querySelector('[data-act="cl-enable"]').click();
          element('addbtn').click();
          if(seen.join()!=='qr:pk-a,on:pk-c,add')throw new Error('hooks: '+seen);
          const qrBefore=rows[0].querySelector('[data-act="cl-qr"]'),later=snapshot();later.peers[0].age=19;
          await feed(later);
          if(element('view').querySelector('.ct-body').children[0].querySelector('[data-act="cl-qr"]')!==qrBefore||!qrBefore.isConnected)
            throw new Error('a poll that only ages the handshake must keep the row buttons (keyboard focus)');
          timers.clear();
          context.fetch=()=>Promise.reject(new Error('offline'));
          await WG._poll.tick();await flush();
          if(!WG.state.offline||!element('addbtn').disabled)throw new Error('offline must disable live actions');
          const qr=element('view').querySelector('.ct-body').children[0].querySelector('[data-act="cl-qr"]');
          if(!qr.disabled)throw new Error('row actions must be off without a connection');
          if(!bannerText().includes('No connection')||!bannerText().includes('Retry now'))throw new Error('offline plaque: '+bannerText());
          if(element('banner').querySelector('[data-act="banner-act"]').disabled)throw new Error('«Retry now» must work offline');
          const rowsText=visibleText(rowsHTML(element('view').querySelector('.ct-body')));
          if(!rowsText.includes('kirill-iphone'))throw new Error('offline keeps the last data');
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)

    def test_search_and_filters_narrow_the_rows(self):
        run_node(self, r"""
        (async()=>{
          await feed(snapshot());
          const body=element('view').querySelector('.ct-body'),names=()=>body.children.map(r=>r.getAttribute('data-pk')).join();
          element('view').querySelector('.cl-filter').querySelector('[data-f="us"]').click();
          if(names()!=='pk-c')throw new Error('US filter: '+names());
          if(store.get('wgui-clients-filter')!=='us')throw new Error('filter must persist');
          element('view').querySelector('.cl-filter').querySelector('[data-f="offline"]').click();
          if(names()!=='pk-b,pk-c')throw new Error('offline filter: '+names());
          element('view').querySelector('.cl-filter').querySelector('[data-f="all"]').click();
          const input=element('view').querySelector('.search-in');
          input.value='198.51.100.10';input.dispatchEvent(makeEvent('input',input));
          if(names()!=='pk-a')throw new Error('search by endpoint IP: '+names());
          input.value='zzz';input.dispatchEvent(makeEvent('input',input));
          if(names()!==''||element('view').querySelector('.ct-empty').hidden)throw new Error('empty result needs a message');
          console.log('__OK__');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        """)


if __name__ == "__main__":
    unittest.main()
