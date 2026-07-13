(function(){
 var L;try{L=localStorage.getItem('wgui-lang')||'ru'}catch(e){L='ru'}
 document.documentElement.lang=L==='ru'?'ru':'en';
 var langBtn=document.getElementById('lang');
 if(langBtn)langBtn.textContent=L==='ru'?'EN':'RU';
 if(L==='ru'){
  var R={"sign in to manage the cascade":"войдите для управления каскадом","Invalid username or password":"Неверный логин или пароль","Username":"Логин","Password":"Пароль","Sign in":"Войти","Show password":"Показать пароль","Hide password":"Скрыть пароль","Toggle theme":"Сменить тему","Language / Язык":"Язык / Language","Too many attempts — try again in a few minutes":"Слишком много попыток — подождите несколько минут"};
  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),ns=[],n;while(n=w.nextNode())ns.push(n);
  ns.forEach(function(t){var k=t.nodeValue.trim();if(k&&R[k])t.nodeValue=t.nodeValue.replace(k,R[k])});
  document.querySelectorAll('[aria-label]').forEach(function(e){var k=e.getAttribute('aria-label');if(R[k])e.setAttribute('aria-label',R[k]);});
  document.querySelectorAll('[data-tip]').forEach(function(e){var k=e.getAttribute('data-tip');if(R[k])e.setAttribute('data-tip',R[k]);});
 }
})();
(function(){var e=document.getElementById('err'),ru;try{ru=(localStorage.getItem('wgui-lang')||'ru')==='ru'}catch(x){ru=true}
 if(location.search.indexOf('e=2')>=0){e.textContent=ru?'Слишком много попыток — подождите несколько минут':'Too many attempts — try again in a few minutes';e.style.display='block';e.setAttribute('role','alert')}
 else if(location.search.indexOf('e=1')>=0){e.style.display='block';e.setAttribute('role','alert')}
})();
(function(){
 var btn=document.getElementById('pwtoggle'),inp=document.getElementById('pw');
 if(!btn||!inp)return;
 var eye='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
 var eyeOff='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.9 17.9A10.9 10.9 0 0 1 12 19c-7 0-11-7-11-7a18.5 18.5 0 0 1 5.2-5.7"/><path d="M9.9 4.2A10.3 10.3 0 0 1 12 4c7 0 11 7 11 7a18.7 18.7 0 0 1-2.7 3.5"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2M1 1l22 22"/></svg>';
 var ru;try{ru=(localStorage.getItem('wgui-lang')||'ru')==='ru'}catch(x){ru=true}
 btn.addEventListener('click',function(){
  var show=inp.type==='password';
  inp.type=show?'text':'password';
  btn.setAttribute('aria-pressed',show?'true':'false');
  btn.setAttribute('aria-label',show?(ru?'Скрыть пароль':'Hide password'):(ru?'Показать пароль':'Show password'));
  btn.innerHTML=show?eyeOff:eye;
 });
})();
document.addEventListener('click',function(e){
 var t=e.target&&e.target.closest&&e.target.closest('[data-act]');
 if(!t)return;
 var a=t.getAttribute('data-act');
 if(a==='theme'&&typeof toggleTheme==='function')toggleTheme();
 if(a==='lang'){
  var L;try{L=localStorage.getItem('wgui-lang')||'ru'}catch(x){L='ru'}
  L=L==='ru'?'en':'ru';
  try{localStorage.setItem('wgui-lang',L)}catch(x){}
  location.reload();
 }
});
