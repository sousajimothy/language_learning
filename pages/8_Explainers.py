"""
Explainers — Interactive grammar widgets.

Currently includes the Konjunktiv II Explorer: reality toggle,
conjugation table with quiz mode, usage cards, and würde guide.
"""

import streamlit as st
import streamlit.components.v1 as components

# ── Page-scoped CSS ──────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 1rem; }
    iframe { border: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("## Konjunktiv II — Interactive Explorer")
st.caption(
    "Toggle between Indikativ and Konjunktiv II, explore conjugation "
    "patterns with color-coded anatomy, quiz yourself, and learn when "
    "to use würde + infinitive vs. the verb's own form."
)

# ── The self-contained HTML widget ───────────────────────────────────
# Everything (CSS + markup + JS) lives in one string so it can be
# dropped into st.components.v1.html() without external dependencies.

WIDGET_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
:root {
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "Cascadia Code", "Fira Code", Menlo, monospace;
  --bg1: #ffffff; --bg2: #f7f7f5; --bg3: #f0efe9;
  --tx1: #1a1a1a; --tx2: #6b6b6b; --tx3: #9a9a9a;
  --br1: rgba(0,0,0,.4); --br2: rgba(0,0,0,.15); --br3: rgba(0,0,0,.08);
  --radius-md: 8px; --radius-lg: 12px;
  --c-suc-bg: #eaf3de; --c-suc-tx: #3b6d11;
  --c-inf-bg: #e6f1fb; --c-inf-tx: #185fa5; --c-inf-br: #85b7eb;
  --c-wrn-bg: #faeeda; --c-wrn-tx: #854f0b; --c-wrn-br: #ef9f27;
  --c-dng-bg: #fcebeb; --c-dng-tx: #a32d2d;
}
@media(prefers-color-scheme:dark){:root{
  --bg1:#2c2c2a;--bg2:#3d3d3a;--bg3:#1e1e1c;
  --tx1:#e8e6de;--tx2:#a8a69e;--tx3:#73726c;
  --br1:rgba(255,255,255,.35);--br2:rgba(255,255,255,.2);--br3:rgba(255,255,255,.1);
  --c-suc-bg:#27500a;--c-suc-tx:#c0dd97;
  --c-inf-bg:#0c447c;--c-inf-tx:#85b7eb;--c-inf-br:#378add;
  --c-wrn-bg:#633806;--c-wrn-tx:#fac775;--c-wrn-br:#ba7517;
  --c-dng-bg:#501313;--c-dng-tx:#f09595;
}}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-sans);color:var(--tx1);background:transparent;padding:4px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1.5rem}
.tab{padding:6px 14px;border-radius:var(--radius-md);font-size:13px;font-weight:500;border:0.5px solid var(--br3);background:transparent;color:var(--tx2);cursor:pointer;transition:all .15s}
.tab:hover{background:var(--bg2)}
.tab.on{background:var(--c-inf-bg);color:var(--c-inf-tx);border-color:var(--c-inf-br)}
.hidden{display:none}
.mode-row{display:flex;align-items:center;gap:8px;margin-bottom:1rem;flex-wrap:wrap}
.mbtn{padding:5px 12px;border-radius:var(--radius-md);font-size:12px;font-weight:500;border:0.5px solid var(--br3);background:transparent;color:var(--tx2);cursor:pointer;transition:all .15s}
.mbtn:hover{background:var(--bg2)}
.mbtn.on{background:var(--c-inf-bg);color:var(--c-inf-tx);border-color:var(--c-inf-br)}
.pair{margin-bottom:1.25rem;animation:fu .3s ease both}
.pair-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:540px){.pair-row{grid-template-columns:1fr}}
.half{padding:12px 16px;border-radius:var(--radius-md)}
.half.rbg{background:var(--c-suc-bg)}.half.ubg{background:var(--c-inf-bg)}
.half .ml{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.half.rbg .ml{color:var(--c-suc-tx)}.half.ubg .ml{color:var(--c-inf-tx)}
.half .de{font-size:16px;line-height:1.5}.half .en{font-size:12px;color:var(--tx2);font-style:italic;margin-top:3px}
.vr{font-weight:500;color:var(--c-suc-tx)}.vu{font-weight:500;color:var(--c-inf-tx)}
.morph-card{padding:14px 16px;border-radius:var(--radius-md);border:0.5px solid var(--br3);background:var(--bg2);margin-bottom:1rem}
.morph-de{font-size:18px;line-height:1.6}.morph-en{font-size:12px;color:var(--tx2);font-style:italic;margin-top:2px}
.slt{position:relative;width:100%;height:6px;background:var(--br3);border-radius:3px;cursor:pointer;margin:8px 0 4px}
.slf{position:absolute;top:0;left:0;height:100%;border-radius:3px;transition:width .35s,background .35s}
.slf.ar{width:0%;background:var(--c-suc-tx)}.slf.au{width:100%;background:var(--c-inf-tx)}
.sll{display:flex;justify-content:space-between;font-size:12px}.sll .al{font-weight:500}
.vpk{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1rem}
.vb{padding:5px 12px;border-radius:var(--radius-md);font-size:13px;border:0.5px solid var(--br3);background:transparent;color:var(--tx2);cursor:pointer;transition:all .15s}
.vb:hover{background:var(--bg2)}.vb.on{background:var(--c-inf-bg);color:var(--c-inf-tx);border-color:var(--c-inf-br)}
.anatomy{background:var(--bg2);border-radius:var(--radius-md);padding:14px 18px;margin-bottom:1rem}
.anatomy-t{font-size:12px;color:var(--tx3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
.sr{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:15px;flex-wrap:wrap}
.sn{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:500;flex-shrink:0}
.sn.s1{background:var(--c-suc-bg);color:var(--c-suc-tx)}.sn.s2{background:var(--c-wrn-bg);color:var(--c-wrn-tx)}.sn.s3{background:var(--c-inf-bg);color:var(--c-inf-tx)}
.stm{font-family:var(--font-mono);font-weight:500;font-size:16px}
.sb{color:var(--c-suc-tx)}.su{color:var(--c-wrn-tx)}.se{color:var(--c-inf-tx)}
.sla{font-size:12px;color:var(--tx2)}
.card{background:var(--bg1);border:0.5px solid var(--br3);border-radius:var(--radius-lg);padding:1rem 1.25rem;margin-bottom:1rem;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:420px}
th{text-align:left;font-weight:500;font-size:12px;color:var(--tx3);padding:6px 10px;border-bottom:0.5px solid var(--br3)}
td{padding:8px 10px;border-bottom:0.5px solid var(--br3);vertical-align:middle}
td:first-child{color:var(--tx2);font-size:13px;width:80px}
.f{font-weight:500;font-family:var(--font-mono);font-size:14px;letter-spacing:.2px}
.f .base{color:var(--c-suc-tx)}.f .uml{color:var(--c-wrn-tx)}.f .end{color:var(--c-inf-tx)}.f.pl{color:var(--tx1)}
.qi{width:110px;padding:4px 8px;border-radius:6px;border:0.5px solid var(--br2);background:var(--bg2);font-family:var(--font-mono);font-size:14px;font-weight:500;color:var(--tx1);outline:none;transition:border-color .2s,background .2s}
.qi:focus{border-color:var(--c-inf-br)}
.qi.ok{border-color:var(--c-suc-tx);background:var(--c-suc-bg);color:var(--c-suc-tx)}
.qi.no{border-color:var(--c-dng-tx);background:var(--c-dng-bg);color:var(--c-dng-tx)}
.qi:disabled{opacity:1}
.rb{padding:4px 10px;border-radius:6px;font-size:12px;border:0.5px solid var(--br3);background:transparent;color:var(--tx2);cursor:pointer;transition:all .15s}
.rb:hover{background:var(--bg2)}
.scb{display:flex;align-items:center;gap:12px;margin-bottom:1rem;padding:10px 14px;background:var(--bg2);border-radius:var(--radius-md);flex-wrap:wrap}
.scl{font-size:13px;color:var(--tx2)}.pips{display:flex;gap:4px}
.pip{width:10px;height:10px;border-radius:50%;background:var(--br3);transition:background .3s}
.pip.hit{background:var(--c-suc-tx)}.pip.miss{background:var(--c-dng-tx)}
.sct{font-size:13px;font-weight:500;color:var(--tx1);margin-left:auto}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:1rem;font-size:12px;color:var(--tx2)}
.ld{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px;vertical-align:middle}
.note{font-size:12px;color:var(--tx3);margin-top:4px;padding-left:10px;border-left:2px solid var(--br3)}
.ug{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.uc{background:var(--bg2);border-radius:var(--radius-md);padding:1rem}
.uc h4{font-size:14px;font-weight:500;margin-bottom:6px}
.uc .ex{font-size:14px;margin-bottom:4px}.uc .ex .v{font-weight:500;color:var(--c-inf-tx)}
.uc .tr{font-size:12px;color:var(--tx2);font-style:italic}
@keyframes fu{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

.char-toggle{padding:5px 12px;border-radius:var(--radius-md);font-size:12px;font-weight:500;border:0.5px solid var(--br3);background:transparent;color:var(--tx2);cursor:pointer;transition:all .15s;display:inline-flex;align-items:center;gap:5px}
.char-toggle:hover{background:var(--bg2)}
.char-toggle.on{background:var(--c-wrn-bg);color:var(--c-wrn-tx);border-color:var(--c-wrn-br)}
.char-tray{display:flex;gap:4px;flex-wrap:wrap;margin-top:8px;animation:fu .2s ease both}
.char-btn{width:36px;height:36px;border-radius:var(--radius-md);border:0.5px solid var(--br3);background:var(--bg1);color:var(--tx1);font-size:16px;font-weight:500;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;position:relative}
.char-btn:hover{background:var(--bg2);border-color:var(--br2)}
.char-btn:active{transform:scale(.94)}
.char-btn .tip{position:absolute;top:-28px;left:50%;transform:translateX(-50%);background:var(--tx1);color:var(--bg1);font-size:11px;padding:2px 8px;border-radius:4px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .15s}
.char-btn.copied .tip{opacity:1}
</style>
</head>
<body>
<div id="app">
<div class="tabs" id="tabs"></div>
<div id="t-toggle"></div>
<div id="t-conj" class="hidden"></div>
<div id="t-uses" class="hidden"></div>
<div id="t-wuerde" class="hidden"></div>
</div>
<script>
const TABS=[{id:'toggle',label:'Reality toggle'},{id:'conj',label:'Conjugation table'},{id:'uses',label:'When to use it'},{id:'wuerde',label:'würde vs. own form'}];
let activeTab='toggle';
function showTab(id){
  activeTab=id;
  TABS.forEach(t=>{document.getElementById('t-'+t.id).classList.toggle('hidden',t.id!==id)});
  document.querySelectorAll('#tabs .tab').forEach(b=>b.classList.toggle('on',b.dataset.t===id));
  if(id==='conj')renderConj();
  if(id==='toggle'){toggleMode==='side'?renderSide():renderMorph()}
}
document.getElementById('tabs').innerHTML=TABS.map(t=>`<button class="tab ${t.id==='toggle'?'on':''}" data-t="${t.id}" onclick="showTab('${t.id}')">${t.label}</button>`).join('');

// === CHAR TRAY ===
const CHARS=['\u00e4','\u00f6','\u00fc','\u00df','\u00c4','\u00d6','\u00dc'];
let trayOpen=false,lastFocusedInput=null;
function charTrayHTML(){
  return `<div style="margin-bottom:1rem">
    <button class="char-toggle ${trayOpen?'on':''}" onclick="toggleTray()">\u00e4 \u00f6 \u00fc \u00df${trayOpen?' \u25b4':' \u25be'}</button>
    ${trayOpen?`<div class="char-tray">${CHARS.map(c=>`<button class="char-btn" onclick="insertChar('${c}',this)" onmousedown="event.preventDefault()">${c}<span class="tip">inserted</span></button>`).join('')}</div>`:''}
  </div>`;
}
function toggleTray(){trayOpen=!trayOpen;renderConj()}
function insertChar(ch,btn){
  if(lastFocusedInput&&!lastFocusedInput.disabled){
    const inp=lastFocusedInput,s=inp.selectionStart,e=inp.selectionEnd;
    inp.value=inp.value.substring(0,s)+ch+inp.value.substring(e);
    inp.selectionStart=inp.selectionEnd=s+ch.length;inp.focus();
    btn.querySelector('.tip').textContent='inserted';
  }else{
    navigator.clipboard.writeText(ch).catch(()=>{});
    btn.querySelector('.tip').textContent='copied';
  }
  btn.classList.add('copied');setTimeout(()=>btn.classList.remove('copied'),800);
}
document.addEventListener('focusin',e=>{if(e.target.classList.contains('qi'))lastFocusedInput=e.target});

// === TAB 1: REALITY TOGGLE ===
const S=[
  {real:{p:['Ich ',{v:'bin'},' m\u00fcde.'],en:'I am tired.'},unreal:{p:['Ich ',{v:'w\u00e4re'},' gern m\u00fcde.'],en:'I would like to be tired.'}},
  {real:{p:['Er ',{v:'hat'},' ein Auto.'],en:'He has a car.'},unreal:{p:['Er ',{v:'h\u00e4tte'},' gern ein Auto.'],en:'He would like to have a car.'}},
  {real:{p:['Wir ',{v:'k\u00f6nnen'},' kommen.'],en:'We can come.'},unreal:{p:['Wir ',{v:'k\u00f6nnten'},' kommen.'],en:'We could come.'}},
  {real:{p:['Sie ',{v:'spielt'},' Klavier.'],en:'She plays piano.'},unreal:{p:['Sie ',{v:'w\u00fcrde'},' Klavier spielen.'],en:'She would play piano.'}},
  {real:{p:['Ich ',{v:'wei\u00df'},' die Antwort.'],en:'I know the answer.'},unreal:{p:['Wenn ich die Antwort ',{v:'w\u00fcsste'},'!'],en:'If only I knew the answer!'}}
];
function rp(parts,cls){return parts.map(p=>typeof p==='string'?p:`<span class="${cls}">${p.v}</span>`).join('')}
let toggleMode='side',morphSt='real';
function initToggle(){
  document.getElementById('t-toggle').innerHTML=`<div class="mode-row"><span style="font-size:12px;color:var(--tx3)">View:</span>
    <button class="mbtn on" data-m="side" onclick="setTM('side')">Side by side</button>
    <button class="mbtn" data-m="morph" onclick="setTM('morph')">Morph</button></div>
    <div id="side-v"></div>
    <div id="morph-v" class="hidden"><div id="morph-s"></div>
      <div style="max-width:320px;margin-top:.75rem"><div class="slt" onclick="toggleMorph()"><div class="slf ar" id="mf"></div></div>
      <div class="sll"><span id="mlr" class="al" style="color:var(--c-suc-tx)">Indikativ</span><span id="mlu" style="color:var(--tx3)">Konjunktiv II</span></div></div></div>`;
  renderSide();
}
function setTM(m){
  toggleMode=m;
  document.querySelectorAll('#t-toggle .mbtn').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
  document.getElementById('side-v').classList.toggle('hidden',m!=='side');
  document.getElementById('morph-v').classList.toggle('hidden',m!=='morph');
  m==='side'?renderSide():renderMorph();
}
function renderSide(){
  document.getElementById('side-v').innerHTML=S.map((s,i)=>`<div class="pair" style="animation-delay:${i*.05}s"><div class="pair-row">
    <div class="half rbg"><div class="ml">Indikativ</div><div class="de">${rp(s.real.p,'vr')}</div><div class="en">${s.real.en}</div></div>
    <div class="half ubg"><div class="ml">Konjunktiv II</div><div class="de">${rp(s.unreal.p,'vu')}</div><div class="en">${s.unreal.en}</div></div></div></div>`).join('');
}
function renderMorph(){
  const u=morphSt==='unreal',src=u?'unreal':'real',cls=u?'vu':'vr';
  document.getElementById('morph-s').innerHTML=S.map((s,i)=>`<div class="morph-card" style="animation:fu .3s ease ${i*.05}s both"><div class="morph-de">${rp(s[src].p,cls)}</div><div class="morph-en">${s[src].en}</div></div>`).join('');
  document.getElementById('mf').className='slf '+(u?'au':'ar');
  const r=document.getElementById('mlr'),l=document.getElementById('mlu');
  r.className=u?'':'al';r.style.color=u?'var(--tx3)':'var(--c-suc-tx)';
  l.className=u?'al':'';l.style.color=u?'var(--c-inf-tx)':'var(--tx3)';
}
function toggleMorph(){morphSt=morphSt==='real'?'unreal':'real';renderMorph()}
initToggle();

// === TAB 2: CONJUGATION ===
const VD={
  sein:{inf:'sein',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'war',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (a \u2192 \u00e4)',p:[{t:'w\u00e4r',c:'su'}]},{n:3,c:'s3',l:'Add endings (-e, -est, -e, -en, -et, -en)',p:[{t:'w\u00e4r',c:'su'},{t:'e',c:'se'}]}],note:'sein is the most essential Konjunktiv II verb. Never replace with w\u00fcrde sein.',rows:[{pro:'ich',pr:'war',k:'w\u00e4re',cp:[{t:'w\u00e4r',c:'uml'},{t:'e',c:'end'}],ex:'Wenn ich du w\u00e4re...'},{pro:'du',pr:'warst',k:'w\u00e4rest',cp:[{t:'w\u00e4r',c:'uml'},{t:'est',c:'end'}],ex:'Wenn du hier w\u00e4rest...'},{pro:'er/sie/es',pr:'war',k:'w\u00e4re',cp:[{t:'w\u00e4r',c:'uml'},{t:'e',c:'end'}],ex:'Wenn er reich w\u00e4re...'},{pro:'wir',pr:'waren',k:'w\u00e4ren',cp:[{t:'w\u00e4r',c:'uml'},{t:'en',c:'end'}],ex:'Wenn wir dort w\u00e4ren...'},{pro:'ihr',pr:'wart',k:'w\u00e4ret',cp:[{t:'w\u00e4r',c:'uml'},{t:'et',c:'end'}],ex:'Wenn ihr da w\u00e4ret...'},{pro:'sie/Sie',pr:'waren',k:'w\u00e4ren',cp:[{t:'w\u00e4r',c:'uml'},{t:'en',c:'end'}],ex:'Wenn sie hier w\u00e4ren...'}]},
  haben:{inf:'haben',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'hatt',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (a \u2192 \u00e4)',p:[{t:'h\u00e4tt',c:'su'}]},{n:3,c:'s3',l:'Add endings',p:[{t:'h\u00e4tt',c:'su'},{t:'e',c:'se'}]}],note:'h\u00e4tte is the building block for past subjunctive: h\u00e4tte + Partizip II (e.g. h\u00e4tte gemacht).',rows:[{pro:'ich',pr:'hatte',k:'h\u00e4tte',cp:[{t:'h\u00e4tt',c:'uml'},{t:'e',c:'end'}],ex:'Wenn ich Zeit h\u00e4tte...'},{pro:'du',pr:'hattest',k:'h\u00e4ttest',cp:[{t:'h\u00e4tt',c:'uml'},{t:'est',c:'end'}],ex:'Wenn du Geld h\u00e4ttest...'},{pro:'er/sie/es',pr:'hatte',k:'h\u00e4tte',cp:[{t:'h\u00e4tt',c:'uml'},{t:'e',c:'end'}],ex:'Wenn er Lust h\u00e4tte...'},{pro:'wir',pr:'hatten',k:'h\u00e4tten',cp:[{t:'h\u00e4tt',c:'uml'},{t:'en',c:'end'}],ex:'Wenn wir Platz h\u00e4tten...'},{pro:'ihr',pr:'hattet',k:'h\u00e4ttet',cp:[{t:'h\u00e4tt',c:'uml'},{t:'et',c:'end'}],ex:'Wenn ihr Mut h\u00e4ttet...'},{pro:'sie/Sie',pr:'hatten',k:'h\u00e4tten',cp:[{t:'h\u00e4tt',c:'uml'},{t:'en',c:'end'}],ex:'Wenn sie Gl\u00fcck h\u00e4tten...'}]},
  "k\u00f6nnen":{inf:'k\u00f6nnen',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'konnt',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (o \u2192 \u00f6)',p:[{t:'k\u00f6nnt',c:'su'}]},{n:3,c:'s3',l:'Add endings',p:[{t:'k\u00f6nnt',c:'su'},{t:'e',c:'se'}]}],note:'k\u00f6nnte is the go-to for polite requests. All modals with an umlaut in their infinitive get one in KII.',rows:[{pro:'ich',pr:'konnte',k:'k\u00f6nnte',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'e',c:'end'}],ex:'Ich k\u00f6nnte helfen.'},{pro:'du',pr:'konntest',k:'k\u00f6nntest',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'est',c:'end'}],ex:'K\u00f6nntest du kommen?'},{pro:'er/sie/es',pr:'konnte',k:'k\u00f6nnte',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'e',c:'end'}],ex:'Sie k\u00f6nnte gewinnen.'},{pro:'wir',pr:'konnten',k:'k\u00f6nnten',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'en',c:'end'}],ex:'Wir k\u00f6nnten gehen.'},{pro:'ihr',pr:'konntet',k:'k\u00f6nntet',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'et',c:'end'}],ex:'K\u00f6nntet ihr warten?'},{pro:'sie/Sie',pr:'konnten',k:'k\u00f6nnten',cp:[{t:'k\u00f6nnt',c:'uml'},{t:'en',c:'end'}],ex:'K\u00f6nnten Sie mir sagen...?'}]},
  werden:{inf:'werden',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'wurd',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (u \u2192 \u00fc)',p:[{t:'w\u00fcrd',c:'su'}]},{n:3,c:'s3',l:'Add endings',p:[{t:'w\u00fcrd',c:'su'},{t:'e',c:'se'}]}],note:'w\u00fcrde doubles as the helper for w\u00fcrde + infinitive \u2014 the most common KII construction in spoken German.',rows:[{pro:'ich',pr:'wurde',k:'w\u00fcrde',cp:[{t:'w\u00fcrd',c:'uml'},{t:'e',c:'end'}],ex:'Ich w\u00fcrde gehen.'},{pro:'du',pr:'wurdest',k:'w\u00fcrdest',cp:[{t:'w\u00fcrd',c:'uml'},{t:'est',c:'end'}],ex:'W\u00fcrdest du mitkommen?'},{pro:'er/sie/es',pr:'wurde',k:'w\u00fcrde',cp:[{t:'w\u00fcrd',c:'uml'},{t:'e',c:'end'}],ex:'Er w\u00fcrde lachen.'},{pro:'wir',pr:'wurden',k:'w\u00fcrden',cp:[{t:'w\u00fcrd',c:'uml'},{t:'en',c:'end'}],ex:'Wir w\u00fcrden bleiben.'},{pro:'ihr',pr:'wurdet',k:'w\u00fcrdet',cp:[{t:'w\u00fcrd',c:'uml'},{t:'et',c:'end'}],ex:'W\u00fcrdet ihr warten?'},{pro:'sie/Sie',pr:'wurden',k:'w\u00fcrden',cp:[{t:'w\u00fcrd',c:'uml'},{t:'en',c:'end'}],ex:'W\u00fcrden Sie mir helfen?'}]},
  "m\u00fcssen":{inf:'m\u00fcssen',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'musst',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (u \u2192 \u00fc)',p:[{t:'m\u00fcsst',c:'su'}]},{n:3,c:'s3',l:'Add endings',p:[{t:'m\u00fcsst',c:'su'},{t:'e',c:'se'}]}],note:'m\u00fcsste is softer than muss \u2014 "would have to" rather than "must". Great for tactful suggestions.',rows:[{pro:'ich',pr:'musste',k:'m\u00fcsste',cp:[{t:'m\u00fcsst',c:'uml'},{t:'e',c:'end'}],ex:'Ich m\u00fcsste gehen.'},{pro:'du',pr:'musstest',k:'m\u00fcsstest',cp:[{t:'m\u00fcsst',c:'uml'},{t:'est',c:'end'}],ex:'Du m\u00fcsstest lernen.'},{pro:'er/sie/es',pr:'musste',k:'m\u00fcsste',cp:[{t:'m\u00fcsst',c:'uml'},{t:'e',c:'end'}],ex:'Man m\u00fcsste das \u00e4ndern.'},{pro:'wir',pr:'mussten',k:'m\u00fcssten',cp:[{t:'m\u00fcsst',c:'uml'},{t:'en',c:'end'}],ex:'Wir m\u00fcssten reden.'},{pro:'ihr',pr:'musstet',k:'m\u00fcsstet',cp:[{t:'m\u00fcsst',c:'uml'},{t:'et',c:'end'}],ex:'Ihr m\u00fcsstet aufpassen.'},{pro:'sie/Sie',pr:'mussten',k:'m\u00fcssten',cp:[{t:'m\u00fcsst',c:'uml'},{t:'en',c:'end'}],ex:'Sie m\u00fcssten unterschreiben.'}]},
  wissen:{inf:'wissen',an:[{n:1,c:'s1',l:'Pr\u00e4teritum stem',p:[{t:'wusst',c:'sb'}]},{n:2,c:'s2',l:'Add umlaut (u \u2192 \u00fc)',p:[{t:'w\u00fcsst',c:'su'}]},{n:3,c:'s3',l:'Add endings',p:[{t:'w\u00fcsst',c:'su'},{t:'e',c:'se'}]}],note:'wissen conjugates like a modal in KII. Always use w\u00fcsste, not w\u00fcrde wissen.',rows:[{pro:'ich',pr:'wusste',k:'w\u00fcsste',cp:[{t:'w\u00fcsst',c:'uml'},{t:'e',c:'end'}],ex:'Wenn ich das w\u00fcsste!'},{pro:'du',pr:'wusstest',k:'w\u00fcsstest',cp:[{t:'w\u00fcsst',c:'uml'},{t:'est',c:'end'}],ex:'Wenn du es w\u00fcsstest...'},{pro:'er/sie/es',pr:'wusste',k:'w\u00fcsste',cp:[{t:'w\u00fcsst',c:'uml'},{t:'e',c:'end'}],ex:'Wenn er es nur w\u00fcsste!'},{pro:'wir',pr:'wussten',k:'w\u00fcssten',cp:[{t:'w\u00fcsst',c:'uml'},{t:'en',c:'end'}],ex:'Wenn wir das w\u00fcssten...'},{pro:'ihr',pr:'wusstet',k:'w\u00fcsstet',cp:[{t:'w\u00fcsst',c:'uml'},{t:'et',c:'end'}],ex:'Wenn ihr es w\u00fcsstet...'},{pro:'sie/Sie',pr:'wussten',k:'w\u00fcssten',cp:[{t:'w\u00fcsst',c:'uml'},{t:'en',c:'end'}],ex:'Wenn sie es w\u00fcssten...'}]}
};
let curV='sein',cMode='explore',qS={};
function cpH(parts){return parts.map(p=>`<span class="${p.c}">${p.t}</span>`).join('')}
function renderConj(){
  const v=VD[curV];
  let h=`<div class="vpk">${Object.keys(VD).map(k=>`<button class="vb ${k===curV?'on':''}" onclick="pickV('${k}')">${k}</button>`).join('')}</div>`;
  h+=`<div class="mode-row"><span style="font-size:12px;color:var(--tx3)">Mode:</span>
    <button class="mbtn ${cMode==='explore'?'on':''}" onclick="setCM('explore')">Explore</button>
    <button class="mbtn ${cMode==='quiz'?'on':''}" onclick="setCM('quiz')">Quiz me</button></div>`;
  h+=`<div class="anatomy"><div class="anatomy-t">How ${v.inf} forms Konjunktiv II</div>`;
  v.an.forEach(s=>{h+=`<div class="sr"><span class="sn ${s.c}">${s.n}</span><span class="stm">${s.p.map(p=>`<span class="${p.c}">${p.t}</span>`).join('')}</span><span class="sla">${s.l}</span></div>`});
  h+=`</div>`;
  if(cMode==='explore'){
    h+=`<div class="legend"><span><span class="ld" style="background:var(--c-suc-tx)"></span>Pr\u00e4teritum stem</span><span><span class="ld" style="background:var(--c-wrn-tx)"></span>Umlaut change</span><span><span class="ld" style="background:var(--c-inf-tx)"></span>KII ending</span></div>`;
    h+=`<div class="card"><table><thead><tr><th>Pronoun</th><th>Pr\u00e4teritum</th><th>Konjunktiv II</th><th>Example</th></tr></thead><tbody>`;
    v.rows.forEach(r=>{h+=`<tr><td>${r.pro}</td><td><span class="f pl">${r.pr}</span></td><td><span class="f">${cpH(r.cp)}</span></td><td style="font-size:13px;color:var(--tx2);font-style:italic">${r.ex}</td></tr>`});
    h+=`</tbody></table></div>`;
  }else{
    if(!qS[curV])qS[curV]={a:{},rv:{}};
    const qs=qS[curV],total=v.rows.length,correct=Object.values(qs.a).filter(x=>x===true).length;
    h+=charTrayHTML();
    h+=`<div class="scb"><span class="scl">Progress</span><span class="pips">${v.rows.map((_,i)=>{const a=qs.a[i];return`<span class="pip ${a===true?'hit':a===false?'miss':''}"></span>`}).join('')}</span><span class="sct">${correct}/${total}</span><button class="rb" onclick="resetQ()">Reset</button></div>`;
    h+=`<div class="card"><table><thead><tr><th>Pronoun</th><th>Pr\u00e4teritum</th><th>Konjunktiv II</th><th></th></tr></thead><tbody>`;
    v.rows.forEach((r,i)=>{
      const done=qs.a[i]!==undefined,rev=qs.rv[i];let cell;
      if(done){const cls=qs.a[i]?'ok':'no';cell=`<input class="qi ${cls}" value="${rev||r.k}" disabled/>`;if(!qs.a[i]&&!rev)cell+=` <button class="rb" onclick="revealA(${i})">Show</button>`}
      else{cell=`<input class="qi" id="qi${i}" placeholder="?" onkeydown="if(event.key==='Enter')chkA(${i})"/> <button class="rb" onclick="chkA(${i})">Check</button>`}
      h+=`<tr><td>${r.pro}</td><td><span class="f pl">${r.pr}</span></td><td style="white-space:nowrap">${cell}</td><td></td></tr>`;
    });
    h+=`</tbody></table></div>`;
  }
  h+=`<div class="note">${v.note}</div>`;
  document.getElementById('t-conj').innerHTML=h;
}
function pickV(v){curV=v;renderConj()}
function setCM(m){cMode=m;renderConj()}
function chkA(i){const v=VD[curV],qs=qS[curV];if(qs.a[i]!==undefined)return;const inp=document.getElementById('qi'+i);if(!inp)return;const val=inp.value.trim().toLowerCase();if(!val)return;const tgt=v.rows[i].k.toLowerCase(),alts=tgt.includes(' / ')?tgt.split(' / ').map(s=>s.trim()):[tgt];qs.a[i]=alts.some(a=>val===a);renderConj()}
function revealA(i){qS[curV].rv[i]=VD[curV].rows[i].k;renderConj()}
function resetQ(){qS[curV]={a:{},rv:{}};renderConj()}

// === TAB 3: USES ===
document.getElementById('t-uses').innerHTML=`<div class="ug">
  <div class="uc"><h4>Wishes</h4><p class="ex">Wenn ich nur mehr Zeit <span class="v">h\u00e4tte</span>!</p><p class="tr">If only I had more time!</p></div>
  <div class="uc"><h4>Unreal conditions</h4><p class="ex">Wenn ich reich <span class="v">w\u00e4re</span>, <span class="v">w\u00fcrde</span> ich reisen.</p><p class="tr">If I were rich, I would travel.</p></div>
  <div class="uc"><h4>Polite requests</h4><p class="ex"><span class="v">K\u00f6nnten</span> Sie mir helfen?</p><p class="tr">Could you help me?</p></div>
  <div class="uc"><h4>Suggestions</h4><p class="ex">An deiner Stelle <span class="v">w\u00fcrde</span> ich warten.</p><p class="tr">In your place, I would wait.</p></div>
  <div class="uc"><h4>Reported speech (alt.)</h4><p class="ex">Er sagte, er <span class="v">h\u00e4tte</span> keine Zeit.</p><p class="tr">He said he had no time.</p></div>
  <div class="uc"><h4>als ob / als wenn</h4><p class="ex">Er tut, als ob er alles <span class="v">w\u00fcsste</span>.</p><p class="tr">He acts as if he knew everything.</p></div>
</div>`;

// === TAB 4: WÜRDE ===
document.getElementById('t-wuerde').innerHTML=`<div class="card">
  <h4 style="font-size:14px;font-weight:500;margin-bottom:10px">When to use the w\u00fcrde + infinitive form</h4>
  <p style="font-size:14px;line-height:1.7;color:var(--tx2);margin-bottom:12px">Many Konjunktiv II forms sound old-fashioned or identical to the Pr\u00e4teritum. In spoken German, <strong style="color:var(--c-inf-tx)">w\u00fcrde + infinitive</strong> replaces most of them \u2014 but a few core verbs keep their own form.</p>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div class="uc"><h4 style="color:var(--c-inf-tx)">Use own form</h4><p class="ex" style="margin-bottom:2px">sein \u2192 <span class="v">w\u00e4re</span></p><p class="ex" style="margin-bottom:2px">haben \u2192 <span class="v">h\u00e4tte</span></p><p class="ex" style="margin-bottom:2px">werden \u2192 <span class="v">w\u00fcrde</span></p><p class="ex" style="margin-bottom:2px">modals \u2192 <span class="v">k\u00f6nnte, m\u00fcsste, d\u00fcrfte, sollte, wollte</span></p><p class="ex">wissen \u2192 <span class="v">w\u00fcsste</span></p></div>
    <div class="uc"><h4 style="color:var(--c-wrn-tx)">Use w\u00fcrde + infinitive</h4><p class="ex" style="margin-bottom:2px">spielen \u2192 w\u00fcrde spielen</p><p class="ex" style="margin-bottom:2px">kaufen \u2192 w\u00fcrde kaufen</p><p class="ex" style="margin-bottom:2px">gehen \u2192 w\u00fcrde gehen</p><p class="ex">Most regular & many irregular verbs</p><p class="tr" style="margin-top:6px">Because spielte / kaufte / ginge sound archaic or identical to Pr\u00e4teritum</p></div>
  </div>
</div>`;
</script>
</body>
</html>
"""

# ── Render ───────────────────────────────────────────────────────────
components.html(WIDGET_HTML, height=820, scrolling=True)
