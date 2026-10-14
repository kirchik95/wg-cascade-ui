/* Sign-in page (E1). No inline handlers (CSP). Theme and language come from boot.js. */
function loginLang(){var L;try{L=localStorage.getItem('wgui-lang')||'ru'}catch(e){L='ru'}return L==='en'?'en':'ru'}
(function(){
 if(typeof document==='undefined')return;
 var ru=loginLang()==='ru';
 document.documentElement.lang=ru?'ru':'en';
 if(ru){
  var R={"Sign in to the panel":"Вход в панель","after 5 failed attempts sign-in is blocked for a while":"после 5 неудачных попыток вход временно блокируется",
   "Username":"Логин","Password":"Пароль","Show":"Показать","Sign in":"Войти","Show password":"Показать пароль"};
  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),ns=[],n;while(n=w.nextNode())ns.push(n);
  ns.forEach(function(t){var k=t.nodeValue.trim();if(k&&R[k])t.nodeValue=t.nodeValue.replace(k,R[k])});
  document.querySelectorAll('[aria-label]').forEach(function(e){var k=e.getAttribute('aria-label');if(R[k])e.setAttribute('aria-label',R[k])});
  document.title='Вход · WG Cascade';
 }
 document.querySelectorAll('[data-act="lang"]').forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-l')===(ru?'ru':'en')))});
 /* the status bar follows the theme boot.js applied (light by default) */
 var t=document.documentElement.getAttribute('data-theme'),dark=t==='dark';
 if(t==='auto'){try{dark=matchMedia('(prefers-color-scheme: dark)').matches}catch(e){}}
 document.querySelectorAll('meta[name=theme-color]').forEach(function(m){m.content=dark?'#121210':'#FFFFFF'});
})();
function plural(n,one,few,many){var a=Math.abs(n)%100,b=a%10;
 if(a>10&&a<20)return many;if(b===1)return one;if(b>=2&&b<=4)return few;return many}
/* ?e=1&left=N (wrong password) / ?e=2&retry=S (throttled): the server counts both. */
function loginMessage(search,ru){
 var q={};(search||'').replace(/^\?/,'').split('&').forEach(function(kv){var p=kv.split('=');if(p[0])q[p[0]]=p[1]||''});
 var num=function(v){return /^\d+$/.test(v||'')?parseInt(v,10):null};
 if(q.e==='2'){
  var s=num(q.retry);
  if(s===null)return ru?'Слишком много попыток — подождите несколько минут':'Too many attempts — try again in a few minutes';
  var m=Math.max(1,Math.ceil(s/60));
  return ru?'Слишком много попыток. Повторите через '+m+' '+plural(m,'минуту','минуты','минут')
           :'Too many attempts. Try again in '+m+' minute'+(m===1?'':'s');
 }
 if(q.e==='1'){
  var base=ru?'Неверный логин или пароль':'Invalid username or password',n=num(q.left);
  if(n===null)return base;
  return base+(ru?' · осталось '+n+' '+plural(n,'попытка','попытки','попыток')
                 :' · '+n+' attempt'+(n===1?'':'s')+' left');
 }
 return '';
}
if(typeof module!=='undefined')module.exports={loginMessage:loginMessage,plural:plural};
/* the error sits under the password field (E1); a wrong password marks the field */
(function(){
 if(typeof document==='undefined')return;
 var e=document.getElementById('err'),pw=document.getElementById('pw'),ru=loginLang()==='ru';
 var m=loginMessage(location.search,ru);
 if(!m||!e)return;
 e.textContent=m;e.hidden=false;e.setAttribute('role','alert');
 if(/[?&]e=1(&|$)/.test(location.search)&&pw){
  pw.setAttribute('aria-invalid','true');
  var u=document.getElementById('user');
  if(u&&u.value)pw.focus();
 }
})();
(function(){
 if(typeof document==='undefined')return;
 var btn=document.getElementById('pwtoggle'),inp=document.getElementById('pw');
 if(!btn||!inp)return;
 var ru=loginLang()==='ru';
 btn.addEventListener('click',function(){
  var show=inp.type==='password';
  inp.type=show?'text':'password';
  btn.setAttribute('aria-pressed',show?'true':'false');
  btn.textContent=show?(ru?'Скрыть':'Hide'):(ru?'Показать':'Show');
  btn.setAttribute('aria-label',show?(ru?'Скрыть пароль':'Hide password'):(ru?'Показать пароль':'Show password'));
  inp.focus();
 });
 inp.addEventListener('input',function(){if(inp.getAttribute('aria-invalid')==='true')inp.removeAttribute('aria-invalid')});
})();
if(typeof document!=='undefined')document.addEventListener('click',function(e){
 var t=e.target&&e.target.closest&&e.target.closest('[data-act="lang"]');
 if(!t)return;
 var L=t.getAttribute('data-l')==='en'?'en':'ru';
 if(L===loginLang())return;
 try{localStorage.setItem('wgui-lang',L)}catch(x){}
 location.reload();
});
