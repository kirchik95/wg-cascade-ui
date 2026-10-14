/* Dashboard (A1–A5): the «Клиенты» section, plus placeholders for the sections that
 * stage 2C fills in pages.js (re-registering a route replaces its placeholder). */
(function(){
'use strict';
const WG=(typeof globalThis!=='undefined'?globalThis:window).WG;
const {tr,esc}=WG;

WG.addStrings('ru',{
 'Placeholder':'Раздел','Open exit settings':'Открыть настройки выходов','Open split tunnel':'Открыть сплит-туннель'
});

/* ------------------------------------------------------------ placeholders */
function placeholder(name,title,action){
 return function(el){
  el.innerHTML='<div class="ph"><h1 class="ph-t">'+esc(title)+'</h1>'
   +'<p class="prose muted">'+esc(tr('This section moves to the new design in the next step.'))+'</p>'
   +(action?'<div><button class="btn btn-outline" type="button" data-act="ph-'+name+'">'+esc(tr(action))+'</button></div>':'')+'</div>';
 };
}
WG.delegate('ph-exits',()=>WG.actions.exitsSettings());
WG.delegate('ph-split',()=>WG.actions.splitSettings());

WG.router.register('clients',{title:tr('Clients'),icon:'clients',mobileTab:true,render:placeholder('clients',tr('Clients'))});
WG.router.register('exits',{title:tr('Exits'),icon:'exits',mobileTab:true,render:placeholder('exits',tr('Exits'),'Open exit settings')});
WG.router.register('split',{title:tr('Split'),icon:'split',render:placeholder('split',tr('Split tunnel'),'Open split tunnel')});
WG.router.register('usage',{title:tr('Usage'),icon:'usage',mobileTab:true,render:placeholder('usage',tr('Usage'))});
WG.router.register('journal',{title:tr('Journal'),icon:'journal',render:placeholder('journal',tr('Journal'))});
})();
