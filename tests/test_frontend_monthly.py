#!/usr/bin/env python3
import pathlib, shutil, subprocess, textwrap, unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestFrontendMonthlyTraffic(unittest.TestCase):
    def test_header_has_monthly_usage_mount(self):
        html = (ROOT / "app" / "index.html").read_text()
        self.assertIn('id="monthuse"', html)
        self.assertIn('data-tip="Traffic this calendar month"', html)

    @unittest.skipIf(shutil.which("node") is None, "node is required to execute frontend helpers")
    def test_monthly_helper_sums_and_renders_status_usage(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');
            const elements = new Map();
            function element(id){
              if(!elements.has(id)){
                elements.set(id, {
                  id, textContent: '', innerHTML: '', dataset: {}, style: {},
                  classList: {add(){}, remove(){}},
                  querySelectorAll(){ return []; }
                });
              }
              return elements.get(id);
            }
            const document = {
              body: {querySelectorAll(){ return []; }},
              querySelector(){ return {content: 'csrf'}; },
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
              window: {matchMedia(){ return {matches: true}; }},
              localStorage: {getItem(){ return 'en'; }, setItem(){}},
              requestAnimationFrame(){ return 0; },
              cancelAnimationFrame(){},
              setInterval(){ return 0; },
              setTimeout(){ return 0; },
              fetch(){ return Promise.reject(new Error('network disabled in test')); },
              location: {href: ''},
              performance: {now(){ return 0; }}
            };
            context.globalThis = context;
            vm.createContext(context);
            vm.runInContext(
              fs.readFileSync('app/app.js', 'utf8') +
              '\\nglobalThis.__monthlyTest = {trafficTotals, monthSummaryHTML, renderMonthPill, renderUsage};',
              context,
              {filename: 'app/app.js'}
            );
            const helpers = context.__monthlyTest;
            const totals = helpers.trafficTotals(
              [{mrx: 1024, mtx: 2048}, {mrx: 512, mtx: 0}, {mrx: null, mtx: 256}],
              'mrx',
              'mtx'
            );
            if(totals.rx !== 1536 || totals.tx !== 2304){
              throw new Error('unexpected totals ' + JSON.stringify(totals));
            }
            helpers.renderMonthPill([{mrx: 1024, mtx: 2048}]);
            const html = element('monthuse').innerHTML;
            if(!html.includes('Month') || !html.includes('1.0 KiB') || !html.includes('2.0 KiB') || !html.includes('3.0 KiB')){
              throw new Error('unexpected month pill HTML: ' + html);
            }
            helpers.renderUsage({daily: [], clients: []});
            const modalHtml = element('ubody').innerHTML;
            if(!modalHtml.includes('Month') || !modalHtml.includes('0.0 B')){
              throw new Error('empty usage modal should include zero total: ' + modalHtml);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
