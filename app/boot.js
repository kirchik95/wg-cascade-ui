(function(){
 var t,L;
 try{t=localStorage.getItem('wgui-theme')}catch(e){}
 if(!t)t=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';
 document.documentElement.dataset.theme=t;
 try{L=localStorage.getItem('wgui-lang')||'ru'}catch(e){L='ru'}
 document.documentElement.lang=L==='ru'?'ru':'en';
})();
