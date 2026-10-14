(function(){
 /* Runs in <head> before CSS paints: theme (light by default; 'auto' follows the
    system through CSS) and document language. */
 var t,L;
 try{t=localStorage.getItem('wgui-theme')}catch(e){}
 if(t!=='dark'&&t!=='auto')t='light';
 document.documentElement.setAttribute('data-theme',t);
 try{L=localStorage.getItem('wgui-lang')||'ru'}catch(e){L='ru'}
 document.documentElement.lang=L==='en'?'en':'ru';
})();
