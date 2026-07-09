function themeIcon(light){
 return light
  ?'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 14.5A8.5 8.5 0 1 1 12.5 3 7 7 0 0 0 21 14.5z"/></svg>'
  :'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
}
function setThemeBtn(){var b=document.getElementById('theme');if(!b)return;
 var light=document.documentElement.dataset.theme==='light';b.innerHTML=themeIcon(light);
 var meta=document.querySelectorAll('meta[name=theme-color]');
 meta.forEach(function(m){if(!m.media||m.media.indexOf(light?'light':'dark')>=0)m.content=light?'#FFFFFF':'#101010'});
}
function toggleTheme(){var h=document.documentElement;h.dataset.theme=h.dataset.theme==='light'?'dark':'light';
 try{localStorage.setItem('wgui-theme',h.dataset.theme)}catch(e){}setThemeBtn();}
setThemeBtn();
