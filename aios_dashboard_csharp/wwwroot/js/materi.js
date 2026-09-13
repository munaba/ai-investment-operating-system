// Materi — knowledge cards filter + canvas
export function initMateri() {
if(window.__materiInit)return;window.__materiInit=true;

// ponytail: shader via Canvas2D fragment emulation (no Three import) - ceiling: true ShaderMaterial, upgrade: import three + ShaderMaterial per panel if GPU weave needed.
const $=s=>document.querySelector(s);
// GSAP intro — already GSAP, keep as-is
gsap.from('#t1',{y:22,opacity:0,duration:.7,ease:'power2.out'});
gsap.from('.spec-card',{y:16,opacity:0,duration:.6,stagger:.08,delay:.15});
gsap.from('.phone-hero',{y:20,opacity:0,scale:.98,duration:.8,delay:.2,ease:'back.out(1.2)'});
// hero tilt — rAF → gsap.ticker (demand-driven)
const stage=document.getElementById('heroCenter'), phone=document.getElementById('phoneHero');
let tx=0,ty=0,rx=0,ry=0;
let tiltActive=false;
function tickTilt(){
  rx+=(tx-rx)*.09; ry+=(ty-ry)*.09;
  phone.style.transform=`rotateX(${rx}deg) rotateY(${ry}deg)`;
  if(Math.abs(rx-tx)<.05&&Math.abs(ry-ty)<.05){
    gsap.ticker.remove(tickTilt);
    tiltActive=false;
  }
}
function ensureTilt(){
  if(!tiltActive){ tiltActive=true; gsap.ticker.add(tickTilt); }
}
stage.addEventListener('mousemove',e=>{
  const r=stage.getBoundingClientRect();
  const x=(e.clientX-(r.left+r.width/2))/r.width, y=(e.clientY-(r.top+r.height/2))/r.height;
  tx=y*-10; ty=x*14; ensureTilt();
});
stage.addEventListener('mouseleave',()=>{tx=0;ty=0; ensureTilt()});
// canvases - fragment-like paint
function paintSilk(c,t,boost){
  const w=c.width,h=c.height,g=c.getContext('2d'); g.clearRect(0,0,w,h);
  for(let y=0;y<h;y++){ for(let x=0;x<w;x++){ const uvx=x/w, uvy=y/h;
    const weave=( ( (uvx*28)%1>.5?1:0)*.08 + ((uvy*28)%1>.5?1:0)*.08 );
    const sheen=Math.pow(Math.max(0, .62),12)*.4 + Math.sin(uvx*6 + t*.9)*.04*boost + Math.sin(uvy*3+t*.6)*.02;
    const fold=Math.sin(uvx*6+t*.5)*.06;
    let r=.85+weave*.6+sheen*.7+fold, g2=.2+weave*.35+sheen*.35, b=.42+weave*.3+sheen*.3;
    r=Math.min(1,Math.max(0,r)); g2=Math.min(1,Math.max(0,g2)); b=Math.min(1,Math.max(0,b));
    g.fillStyle=`rgb(${r*255|0},${g2*255|0},${b*255|0})`; g.fillRect(x,y,1,1);
  }}
}
function paintLinen(c,t){
  const w=c.width,h=c.height,g=c.getContext('2d');
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const uvx=x/w, uvy=y/h;
    const warp=(uvx*22)%1>.5?1:0, weft=(uvy*22)%1>.5?1:0;
    const weave=warp*.18+weft*.18-warp*weft*.12;
    const slub=(Math.sin(uvx*127+uvy*311)*43758%1)>.985? .18:0;
    const ao=Math.hypot(uvx-.5,uvy-.5)*1.2; const dark=ao>.5?(ao-.5)*-.16:0;
    let v=.92+weave+slub+dark; v=Math.min(1,v);
    const r=v*242, gg=v*225, b=v*198;
    g.fillStyle=`rgb(${r|0},${gg|0},${b|0})`; g.fillRect(x,y,1,1);
  }}
function paintTartan(c){
  const w=c.width,h=c.height,g=c.getContext('2d');
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const uvx=x/w, uvy=y/h;
    const rx=(uvx*6)%1, ry=(uvy*6)%1;
    let bandX=(rx>.02&&rx<.22)||(rx>.48&&rx<.52)?1:0;
    let bandY=(ry>.02&&ry<.22)||(ry>.48&&ry<.52)?1:0;
    let r=18,g2=34,b=50;
    if(bandX){r=209;g2=46;b=46} if(bandY){r=209;g2=46;b=46} if(bandX&&bandY){r=235;g2=199;b=36}
    const wX=(rx>.49&&rx<.51)?1:0, wY=(ry>.49&&ry<.51)?1:0; if(wX||wY){r=r*.3+242*.7; g2=g2*.3+242*.7; b=b*.3+235*.7}
    const twill=Math.sin((uvx-uvy)*44)*10+10; r+=twill; g2+=twill; b+=twill;
    g.fillStyle=`rgb(${r|0},${g2|0},${b|0})`; g.fillRect(x,y,1,1);
  }}
function paintBamboo(c,t){
  const w=c.width,h=c.height,g=c.getContext('2d'); g.fillStyle='#141210'; g.fillRect(0,0,w,h);
  const slats=12;
  for(let i=0;i<slats;i++){
    const y=(i/slats)*h + Math.sin(t*.6+i)*2;
    const hh=h/slats-2; const isDark=i%3===0;
    g.fillStyle=isDark?'#8a6a3a':'#c9a86a'; g.fillRect(6,y,w-12,hh);
    g.fillStyle='rgba(255,255,255,.12)'; g.fillRect(6,y,w-12,2);
  }
  g.fillStyle='#2b1d0e';
  for(let i=0;i<5;i++){ const x=18+i*(w-36)/4; g.fillRect(x,0,6,h); }
}
const cvS=document.getElementById('cv-silk'), cvL=document.getElementById('cv-linen'), cvT=document.getElementById('cv-tartan'), cvB=document.getElementById('cv-bamboo');
let t=0, silkBoost=1;
let lastSilk=0;
function loopSilk(time){
  if(time&&time-lastSilk<33) return;
  if(time) lastSilk=time;
  t+=0.016*silkBoost;
  paintSilk(cvS,t,silkBoost); if(t%2<0.02){paintLinen(cvL,t); paintTartan(cvT); paintBamboo(cvB,t);}
}
paintLinen(cvL,0); paintTartan(cvT); paintBamboo(cvB,0);
gsap.ticker.add(loopSilk);
document.querySelectorAll('.woven').forEach(el=>{
  el.addEventListener('mouseenter',()=>silkBoost=1.7);
  el.addEventListener('mouseleave',()=>silkBoost=1);
});
// orbs 23
const orbNames=["AURA SILK","KINA LINEN","TERRA TARTAN","BAMBU NARA","SORA WEAVE","MORI COTTON","HANA JUTE","RIN HEMP","KAZE WOOL","YUME CASHMERE","IKAT","SHIBORI","BINGKAI","TENUN","LURIK","SONGKET","TAPIS","ULOS","GRINGSING","ABACA","RAMIE","KOZO","WASHI"];
const orbs=document.getElementById('orbs');
orbNames.forEach((n,i)=>{
  const d=document.createElement('div'); d.className='orb'; d.tabIndex=0; d.setAttribute('role','button'); d.setAttribute('aria-label',n);
  d.innerHTML=`<b></b><label>${String(i+1).padStart(2,'0')} - ${n}</label>`;
  d.style.animationDelay=(i*0.07)+'s'; orbs.appendChild(d);
  d.addEventListener('click',()=>{d.animate([{transform:'scale(1)'},{transform:'scale(1.12)'},{transform:'scale(1)'}],{duration:380,easing:'ease-out'}); bPulse(d)});
});
function bPulse(el){ const b=el.querySelector('b'); b.animate([{transform:'scale(1)',opacity:1},{transform:'scale(1.9)',opacity:0}],{duration:420,easing:'ease-out'}) }
gsap.to('.orb',{y:-6,duration:1.8+Math.random(),repeat:-1,yoyo:true,ease:'sine.inOut',stagger:{each:.06,from:'random'}});
// devices 8 - LS graphics frames lookbook
const devices=[
 {k:'phone',t:'iPhone 15 Pro - Silk Cover',d:'Editorial drape untuk product card & hero.',c:'linear-gradient(135deg,#d94a6a,#f7a8b8)'},
 {k:'ipad',t:'iPad Pro 12.9 - Linen Atelier',d:'Katalog tenun matte untuk lookbook.',c:'linear-gradient(135deg,#ece6db,#d9c8a8)'},
 {k:'mac',t:'MacBook Air - Tartan System',d:'Plaid grid untuk landing & packaging.',c:'linear-gradient(135deg,#1a365d,#2a5a8a)'},
 {k:'watch',t:'Watch Ultra - Bamboo Strap',d:'Anyam bambu untuk aksesori & alas.',c:'linear-gradient(135deg,#c9a86a,#8a6a3a)'},
 {k:'phone',t:'iPhone Stack - Swatch Pack',d:'Tumpukan swatch untuk picker warna.',c:'linear-gradient(135deg,#111,#3a3a4a)'},
 {k:'ipad',t:'iPad Landscape - Journal',d:'Layout editorial material & care.',c:'linear-gradient(135deg,#f7f5f1,#c9a86a)'},
 {k:'mac',t:'MacBook Pro 16 - Atelier Desk',d:'Workspace penata koleksi tekstur.',c:'linear-gradient(135deg,#0f172a,#2d3a5a)'},
 {k:'watch',t:'Plop 3D Icons - Material Kit',d:'80 ikon glossy turunan weave.',c:'linear-gradient(135deg,#ff6b9d,#ffd93d)'},
];
const devWrap=document.getElementById('devices');
devices.forEach(o=>{
  const el=document.createElement('div'); el.className='device';
  el.innerHTML=`<div class="mini-frame ${o.k}"><div class="mini-screen ${o.k}"><div style="position:absolute;inset:0;background:${o.c}"></div><div style="position:absolute;left:10px;right:10px;top:10px;background:#fff;border-radius:10px;padding:8px;display:flex;gap:8px;align-items:center"><div style="width:28px;height:28px;border-radius:8px;background:#111;display:grid;place-items:center;color:#fff;font-size:.7rem">◨</div><div><div style="font-size:.68rem;font-weight:800">AIOS</div><div style="font-size:.6rem;opacity:.5">Materi</div></div><span style="margin-left:auto;font-size:.6rem;background:#111;color:#fff;padding:4px 8px;border-radius:999px">View</span></div></div></div><h3>${o.t}</h3><p>${o.d}</p>`;
  devWrap.appendChild(el);
});
// swatches
const sw=document.getElementById('swatches');
['#d94a6a','#ece6db','#1a365d','#c9a86a','#6c5cff','#0f172a','#f7a8b8','#8a6a3a'].forEach(hex=>{
  const b=document.createElement('button'); b.style.cssText=`width:100%;aspect-ratio:1;border-radius:10px;border:2px solid #fff;box-shadow:0 4px 12px rgba(0,0,0,.12);background:${hex};cursor:pointer`; b.setAttribute('aria-label',hex);
  b.onclick=()=>{document.querySelector('.look h2').style.color=hex; gsap.fromTo(b,{scale:.9},{scale:1,duration:.25,ease:'back.out(1.6)'})};
  sw.appendChild(b);
});
document.getElementById('cta').onclick=()=>document.getElementById('studio').scrollIntoView({behavior:'smooth'});

/* ─── POLISH · komponen threeui ─── */
const REDUCE=matchMedia('(prefers-reduced-motion: reduce)').matches;
const DPR_MOBILE=()=>Math.min(devicePixelRatio||1,innerWidth<=640?1:2);

/* blur-fade - reveal saat masuk viewport */
(function(){
  if(REDUCE||!('IntersectionObserver' in window)){
    document.querySelectorAll('.rv').forEach(e=>e.classList.add('in'));return;
  }
  const io=new IntersectionObserver(es=>{
    es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}});
  },{rootMargin:'0px 0px -8% 0px',threshold:.1});
  document.querySelectorAll('.rv').forEach(e=>io.observe(e));
})();

/* magic-card - spotlight di tiap panel woven */
document.querySelectorAll('.woven').forEach(card=>{
  const spot=card.querySelector('.spot');if(!spot)return;
  card.addEventListener('pointermove',e=>{
    const r=card.getBoundingClientRect();
    spot.style.opacity='1';
    spot.style.background='radial-gradient(360px 220px at '+(e.clientX-r.left)+'px '+(e.clientY-r.top)+'px, rgba(251,207,232,.20), transparent 60%)';
  });
  card.addEventListener('pointerleave',()=>spot.style.opacity='0');
});

/* border-beam - tepi menyala pada panel woven · rAF → gsap.ticker */
(function(){
  if(REDUCE)return;
  const beams=[...document.querySelectorAll('.woven .beam')];
  if(!beams.length)return;
  let a=0;
  let lastBeam=0;
  function frameBeam(time){
    if(time&&time-lastBeam<33) return;
    if(time) lastBeam=time;
    a=(a+0.5)%360;
    beams.forEach((el,i)=>{
      const ang=(a+i*90)%360;
      el.style.background='conic-gradient(from '+ang+'deg at 50% 50%, transparent 0deg, transparent 300deg, rgba(251,207,232,.85) 360deg)';
      el.style.mask='linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)';
      el.style.webkitMask='linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)';
      el.style.maskComposite='exclude'; el.style.webkitMaskComposite='xor';
      el.style.padding='1.5px';
    });
  }
  gsap.ticker.add(frameBeam);
})();

/* marquee - magic/marquee-01, nama material · rAF → gsap.ticker */
(function(){
  const track=document.getElementById('marqMat');if(!track)return;
  const names=orbNames.slice(0,12);
  const seq=[];for(let i=0;i<4;i++)seq.push(...names);
  seq.forEach(n=>{const d=document.createElement('span');d.className='marq-item';d.textContent=n;track.appendChild(d)});
  if(REDUCE)return;
  let x=0,dir=-1;
  let lastMarqM=0;
  function loopMarq(time){
    if(time&&time-lastMarqM<33) return;
    if(time) lastMarqM=time;
    x+=dir*.7;
    const w=track.scrollWidth/4;
    if(x<-w)x=0; if(x>0)x=-w;
    track.style.transform='translateX('+x+'px)';
  }
  gsap.ticker.add(loopMarq);
})();

/* animated-dock - etalase material · rAF → gsap.ticker */
(function(){
  const dock=document.getElementById('mDock');if(!dock)return;
  const icons=['◐','⬢','⬣','◆','✦','◎','▣','⬔'];
  const cols=['#fbcfe8','#ece6db','#1a365d','#c9a86a','#d94a6a','#6c5cff','#f7a8b8','#8a6a3a'];
  const apps=icons.map((ic,i)=>{
    const el=document.createElement('div');el.className='app';el.textContent=ic;
    el.style.background=cols[i];el.style.color='#0b1a18';el.title=orbNames[i]||('Material '+(i+1));
    el.setAttribute('role','listitem');dock.appendChild(el);return el;
  });
  let mx=-1;
  dock.addEventListener('pointermove',e=>{mx=e.clientX-dock.getBoundingClientRect().left});
  dock.addEventListener('pointerleave',()=>{mx=-1;apps.forEach(a=>a.style.transform='scale(1) translateY(0)')});
  apps.forEach(el=>el.addEventListener('click',()=>{
    el.animate([{transform:'scale(1.2) translateY(-14px)'},{transform:'scale(.92) translateY(2px)'},{transform:'scale(1) translateY(0)'}],
      {duration:520,easing:'cubic-bezier(.34,1.56,.64,1)'});
  }));
  if(REDUCE)return;
  function frameDock(){
    if(mx>=0){
      const dr=dock.getBoundingClientRect();
      apps.forEach(el=>{
        const r=el.getBoundingClientRect(),cx=r.left+r.width/2-dr.left;
        const mag=Math.max(0,1-Math.abs(cx-mx)/130);
        el.style.transform='scale('+(1+mag*.8)+') translateY('+(-mag*16)+'px)';
      });
    }
  }
  gsap.ticker.add(frameDock);
})();

/* particles-01 - bidang tolak kursor · rAF → gsap.ticker */
(function(){
  const cv=document.getElementById('mPart');if(!cv)return;
  const ctx=cv.getContext('2d');
  let W=0,H=0,ps=[],mouse={x:-999,y:-999};
  const DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2);
  function rs(){
    const r=cv.getBoundingClientRect();if(!r.width)return;
    W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);
    ps=[];for(let i=0;i<40;i++)ps.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.6,vy:(Math.random()-.5)*.6,r:1+Math.random()*1.6});
  }
  addEventListener('resize',rs);rs();
  cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();mouse.x=e.clientX-r.left;mouse.y=e.clientY-r.top});
  cv.addEventListener('pointerleave',()=>{mouse.x=mouse.y=-999});
  let lastMp=0;
  function drawMp(time){
    if(time&&time-lastMp<33) return;
    if(time) lastMp=time;
    ctx.clearRect(0,0,W,H);
    ps.forEach(p=>{
      p.x+=p.vx;p.y+=p.vy;
      if(p.x<0||p.x>W)p.vx*=-1; if(p.y<0||p.y>H)p.vy*=-1;
      const dx=p.x-mouse.x,dy=p.y-mouse.y,d=Math.hypot(dx,dy);
      if(d<70&&d>0){p.x+=dx/d*1.2;p.y+=dy/d*1.2}
      ctx.fillStyle='rgba(251,207,232,.85)';ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill();
    });
    for(let i=0;i<ps.length;i++)for(let j=i+1;j<ps.length;j++){
      const dx=ps[i].x-ps[j].x,dy=ps[i].y-ps[j].y,d=Math.hypot(dx,dy);
      if(d<70){ctx.strokeStyle='rgba(251,207,232,'+(0.18*(1-d/70))+')';ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(ps[i].x,ps[i].y);ctx.lineTo(ps[j].x,ps[j].y);ctx.stroke()}
    }
  }
  if(!REDUCE) gsap.ticker.add(drawMp);
})();

/* laser-01 - sweep / pulse / split · rAF → gsap.ticker */
(function(){
  const cv=document.getElementById('mLaser');if(!cv)return;
  const ctx=cv.getContext('2d');
  const C1='#fbcfe8',C2='#6c5cff';
  let W=0,H=0,mode=1,tL=0;
  const DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2);
  function rs(){const r=cv.getBoundingClientRect();if(!r.width)return;W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0)}
  addEventListener('resize',rs);rs();
  cv.style.cursor='pointer';
  cv.addEventListener('click',()=>{mode=(mode+1)%3});
  cv.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();mode=(mode+1)%3}});
  let lastLaser=0;
  function drawL(time){
    if(time&&time-lastLaser<33) return;
    if(time) lastLaser=time;
    if(!W) return;
    if(!REDUCE)tL+=0.02;
    ctx.fillStyle='#0a0a0f';ctx.fillRect(0,0,W,H);
    ctx.strokeStyle='rgba(255,255,255,.04)';ctx.lineWidth=1;
    for(let x=0;x<W;x+=28){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke()}
    for(let y=0;y<H;y+=28){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}
    const cx=W/2,cy=H/2;
    if(mode===1){
      const sx=(Math.sin(tL*.7)*W*.42)+cx;
      const g=ctx.createLinearGradient(sx-100,0,sx+100,0);
      g.addColorStop(0,'transparent');g.addColorStop(.5,C1);g.addColorStop(1,'transparent');
      ctx.fillStyle=g;ctx.fillRect(sx-100,0,200,H);
      ctx.strokeStyle=C1;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(sx,0);ctx.lineTo(sx,H);ctx.stroke();
      ctx.shadowBlur=20;ctx.shadowColor=C1;ctx.fillStyle=C1;ctx.beginPath();ctx.arc(sx,cy,5,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
    }else if(mode===0){
      for(let k=0;k<5;k++){
        const a=tL*.6+k*1.26,len=Math.min(W,H)*.42+Math.sin(tL*2+k)*26;
        const x2=cx+Math.cos(a)*len,y2=cy+Math.sin(a)*len;
        ctx.shadowBlur=16;ctx.shadowColor=C1;ctx.strokeStyle=C1;ctx.lineWidth=2.2;
        ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(x2,y2);ctx.stroke();ctx.shadowBlur=0;
        ctx.fillStyle=C1;ctx.beginPath();ctx.arc(x2,y2,3.5,0,Math.PI*2);ctx.fill();
      }
      ctx.strokeStyle=C1;ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(cx,cy,40,0,Math.PI*2);ctx.stroke();
    }else{
      for(let k=-2;k<=2;k++){
        const y=cy+k*38+Math.sin(tL*1.2+k)*7;
        ctx.shadowBlur=10;ctx.shadowColor=k===0?C1:C2;ctx.strokeStyle=k===0?C1:C2;ctx.lineWidth=k===0?2.6:1.4;
        ctx.beginPath();ctx.moveTo(0,y);
        for(let x=0;x<W;x+=16)ctx.lineTo(x,y+Math.sin(x*.02+tL+k)*5);
        ctx.stroke();ctx.shadowBlur=0;
      }
    }
  }
  gsap.ticker.add(drawL);
})();

/* number-ticker - magic/number-ticker-01 · rAF → gsap.to (already GSAP-friendly) */
(function(){
  function runTicker(){
    const pairs=[['tk1',4],['tk2',orbNames.length],['tk3',devices.length],['tk4',8]];
    pairs.forEach(([id,target])=>{
      const el=document.getElementById(id);if(!el)return;
      if(REDUCE){el.textContent=target;return}
      const obj={v:0};
      gsap.to(obj,{v:target,duration:1.3,ease:'power3.out',onUpdate:()=>{el.textContent=Math.floor(obj.v)}});
    });
  }
  const sec=document.getElementById('angka');
  if(sec&&'IntersectionObserver' in window){
    let done=false;
    const io=new IntersectionObserver(e=>{if(e[0].isIntersecting&&!done){done=true;runTicker();io.disconnect()}},{threshold:.3});
    io.observe(sec);
  } else runTicker();
})();

/* spark-badge - pulse pada orb saat diklik */
document.querySelectorAll('.orb').forEach(o=>{
  o.addEventListener('click',()=>{
    o.classList.remove('pulse');void o.offsetWidth;o.classList.add('pulse');
  });
});

/* word-rotate - magic/word-rotate-01 di judul hero */
(function(){
  const el=document.getElementById('matWords');if(!el)return;
  const words=['Materi','Tenun','Anyam','Tekstur'];
  if(REDUCE)return;
  let i=0;
  setInterval(()=>{
    el.style.transition='none';el.style.transform='translateY(12px)';el.style.opacity='0';
    setTimeout(()=>{i=(i+1)%words.length;el.textContent=words[i];
      el.style.transition='all .5s cubic-bezier(.16,1,.3,1)';el.style.transform='none';el.style.opacity='1'},60);
  },2400);
})();


addEventListener("DOMContentLoaded",function(){var s=document.querySelector("a.skip"),m=document.getElementById("main");if(s&&m){s.addEventListener("click",function(e){try{m.focus({preventScroll:true});}catch(_){m.focus();}});}});

console.log('Materi initialized');
}
