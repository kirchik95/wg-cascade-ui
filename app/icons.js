/* Icon set of the Tablo Light design system (DS-4): linear, 24×24 grid, round caps
 * and joins, colour = currentColor. 16 px in buttons, 18–20 px in navigation.
 * WGIcons.icon(name, size=16) → '<svg…>' string; WG.icon is the same function. */
(function(){
'use strict';
const root=typeof globalThis!=='undefined'?globalThis:window;
const P={
 clients:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14a6 6 0 0 1 3.5 6"/>',
 exits:'<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7.5 12h3l4-6h2M10.5 12l4 6h2"/>',
 split:'<path d="M12 21V11"/><path d="M12 11L5 4M12 11l7-7"/><path d="M5 4v4M5 4h4"/><path d="M19 4h-4M19 4v4"/>',
 usage:'<path d="M3 3v18h18"/><path d="M7 16v-4M11 16V8M15 16v-6M19 16V6"/>',
 journal:'<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
 more:'<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
 add:'<path d="M12 5v14M5 12h14"/>',
 qr:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3M21 14v.01M14 21h3M21 18v3h-3"/>',
 download:'<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
 copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
 share:'<path d="M12 15V3M7 8l5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>',
 edit:'<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
 power:'<path d="M12 3v8"/><path d="M6.5 7a8 8 0 1 0 11 0"/>',
 delete:'<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13M9 7V4h6v3"/>',
 'switch-exit':'<path d="M7 4L3 8l4 4"/><path d="M3 8h13"/><path d="M17 12l4 4-4 4"/><path d="M21 16H8"/>',
 refresh:'<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
 ok:'<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
 warning:'<path d="M12 3l9.5 17h-19L12 3z"/><path d="M12 10v4M12 17v.01"/>',
 error:'<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
 unknown:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 16.5v.01"/>',
 offline:'<path d="M3 3l18 18"/><path d="M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 4-2.4M12 20v.01M15 10.5a10 10 0 0 1 4 2.5M2 9a15 15 0 0 1 4.5-3M10.5 5.1A15 15 0 0 1 22 9"/>',
 server:'<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5v.01M7 16.5v.01"/>',
 internet:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
 device:'<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
 moon:'<path d="M21 14.5A8.5 8.5 0 1 1 12.5 3 7 7 0 0 0 21 14.5z"/>',
 logout:'<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
 lock:'<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 search:'<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
 x:'<path d="M6 6l12 12M18 6L6 18"/>',
 user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
 chevron:'<path d="M9 6l6 6-6 6"/>',
 'arrow-right':'<path d="M5 12h14M13 6l6 6-6 6"/>',
 'arrow-down':'<path d="M12 5v14M6 13l6 6 6-6"/>'
};
P.globe=P.lang=P.internet;
function icon(name,size){
 const body=P[name];if(!body)return'';
 const s=+size||16,w=s<=16?1.9:1.8;
 return '<svg class="ic ic-'+name+'" width="'+s+'" height="'+s+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="'+w
  +'" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+body+'</svg>';
}
root.WGIcons={icon,has:name=>Object.prototype.hasOwnProperty.call(P,name),names:Object.keys(P)};
})();
