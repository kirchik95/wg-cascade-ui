# Monthly Traffic Total Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show current calendar-month traffic totals on the main screen and in the Usage modal.

**Architecture:** Keep all data flow client-side because the backend already exposes monthly traffic per peer. Add one pure helper to sum `rx/tx` pairs, render a header pill from `/api/status`, and render a matching summary inside `/api/history` usage details.

**Tech Stack:** Vanilla JavaScript, static HTML, CSS, Python stdlib unit tests for existing backend coverage.

---

### Task 1: Header And Usage Modal Monthly Totals

**Files:**
- Modify: `app/index.html`
- Modify: `app/app.js`
- Modify: `app/app.css`
- Verify: `python3 -m unittest discover -s tests`

- [x] **Step 1: Add the header mount point**

In `app/index.html`, add a new pill in `.meta` immediately after the live throughput pill:

```html
<span class="pill monthpill" id="monthuse" data-tip="Traffic this calendar month">…</span>
```

- [x] **Step 2: Add monthly-total helpers**

In `app/app.js`, add these helpers near the existing formatting helpers:

```javascript
function trafficTotals(items,rxKey,txKey){
 items=items||[];rxKey=rxKey||'rx';txKey=txKey||'tx';
 return items.reduce((a,x)=>({rx:a.rx+(+x[rxKey]||0),tx:a.tx+(+x[txKey]||0)}),{rx:0,tx:0});
}
function monthSummaryHTML(t){
 const total=t.rx+t.tx;
 return '<span class="mlbl">'+tr('Month')+'</span> <span class="dn">↓ <b>'+fmtB(t.rx)+'</b></span> <span class="up">↑ <b>'+fmtB(t.tx)+'</b></span> <span class="msum">· '+fmtB(total)+'</span>';
}
function renderMonthPill(peers){
 const el=document.getElementById('monthuse');if(!el)return;
 el.innerHTML=monthSummaryHTML(trafficTotals(peers,'mrx','mtx'));
}
```

- [x] **Step 3: Translate the new label**

In the `RU` dictionary in `app/app.js`, add:

```javascript
"Month":"Месяц",
```

- [x] **Step 4: Update status rendering**

In `tick()`, call `renderMonthPill(d.peers);` after `renderClients(d.peers);`:

```javascript
renderAlert(d.tunnel);renderCascade(d.tunnel,d.rud);renderHost(d.host);renderClients(d.peers);renderMonthPill(d.peers);
```

- [x] **Step 5: Add Usage modal summary**

In `renderUsage(r)`, compute `mt` before the empty-state branch and prepend the summary:

```javascript
const mt=trafficTotals(r.clients||[]);
```

Initialize the HTML with:

```javascript
let h='<div class="utotal">'+monthSummaryHTML(mt)+'</div>';
```

- [x] **Step 6: Style the summary**

In `app/app.css`, add:

```css
.monthpill .dn,.utotal .dn{color:var(--dn)}.monthpill .up,.utotal .up{color:var(--up)}
.monthpill .mlbl,.monthpill .msum{color:var(--dim)}
.utotal{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin:0 0 12px;font-size:12.5px}
.utotal .mlbl,.utotal .msum{color:var(--dim)}.utotal b{font-weight:600}
```

- [x] **Step 7: Run verification**

Run:

```bash
python3 -m unittest discover -s tests
```

Expected: all existing tests pass.

- [ ] **Step 8: Manual browser check**

Load the app and verify:

- Header shows a `Month` pill next to live throughput.
- The pill shows zero values when there is no monthly history.
- The `Usage` modal shows the same combined monthly total above the chart.
- Russian UI shows `Месяц`.
