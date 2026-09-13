// Profil page interactivity - UMD wrapper for Blazor
(function(root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.initProfil = factory();
    }
}(typeof self !== 'undefined' ? self : this, function() {
    'use strict';
    
    function initProfil() {
        if (window.__profilInit) return;
        window.__profilInit = true;
// scroll reveal
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('show');io.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll('.in').forEach(el=>io.observe(el));
// border-beam rotate — GSAP ticker (was rAF)
let a=0;const beams=document.querySelectorAll('.beam');
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
let tickVisible=true;
function tickBeam(){ if(!tickVisible||reduce) return; a=(a+0.32)%360;beams.forEach(b=>b.style.setProperty('--a',a+'deg')); }
if(!reduce){
    gsap.ticker.add(tickBeam);
    try{ new IntersectionObserver(function(e){ tickVisible=e[0].isIntersecting; if(!tickVisible) gsap.ticker.remove(tickBeam); else gsap.ticker.add(tickBeam); },{threshold:0}).observe(beams[0]||document.body); }catch(e){}
    document.addEventListener('visibilitychange', function(){ if(document.hidden) gsap.ticker.remove(tickBeam); else if(tickVisible) gsap.ticker.add(tickBeam); });
}
// mobile nav — identik aios-atlas.html
const mnav=document.getElementById('mnav');
document.getElementById('burger').onclick=()=>mnav.classList.add('open');
document.getElementById('closeNav').onclick=()=>mnav.classList.remove('open');
mnav.querySelectorAll('a').forEach(x=>x.addEventListener('click',()=>mnav.classList.remove('open')));
// smooth anchor
document.querySelectorAll('a[href^="#"]').forEach(x=>x.addEventListener('click',e=>{const el=document.getElementById(x.getAttribute('href').slice(1));if(el){e.preventDefault();el.scrollIntoView({behavior:'smooth'})}}));
// blueprint lattice — GSAP ticker (was rAF)
(function(){
  const cv=document.getElementById('blueprint');if(!cv)return;
  const ctx=cv.getContext('2d');let w,h,dpr,pts=[];
  function size(){
    dpr=Math.min(window.devicePixelRatio||1,2);
    const r=cv.getBoundingClientRect();w=r.width;h=r.height;
    cv.width=w*dpr;cv.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    const cols=Math.max(4,Math.round(w/120)),rows=Math.max(3,Math.round(h/120));
    pts=[];
    for(let i=0;i<cols;i++)for(let j=0;j<rows;j++){
      pts.push({bx:(i+.5)*(w/cols)+((j%2)?w/cols/2:0),by:(j+.5)*(h/rows),px:0,py:0,ph:Math.random()*6.283});
    }
  }
  size();addEventListener('resize',size);
  function draw(){
    ctx.clearRect(0,0,w,h);
    const T=reduce?0:gsap.ticker.time/2.6;
    pts.forEach(p=>{p.px=p.bx+Math.sin(T+p.ph)*9;p.py=p.by+Math.cos(T*0.8+p.ph)*7});
    ctx.strokeStyle='rgba(87,144,230,.16)';ctx.lineWidth=1;
    for(let i=0;i<pts.length;i++){
      const A=pts[i];
      for(let j=i+1;j<pts.length;j++){
        const B=pts[j],dx=A.px-B.px,dy=A.py-B.py,d=Math.hypot(dx,dy);
        if(d<135){ctx.globalAlpha=1-d/135;ctx.beginPath();ctx.moveTo(A.px,A.py);ctx.lineTo(B.px,B.py);ctx.stroke()}
      }
    }
    ctx.globalAlpha=1;ctx.fillStyle='rgba(87,144,230,.5)';
    pts.forEach(p=>{ctx.beginPath();ctx.arc(p.px,p.py,1.6,0,6.283);ctx.fill()});
  }
  gsap.ticker.add(draw);
})();

addEventListener("DOMContentLoaded",function(){var s=document.querySelector("a.skip"),m=document.getElementById("main");if(s&&m){s.addEventListener("click",function(e){try{m.focus({preventScroll:true});}catch(_){m.focus();}});}});
        console.log('Profil initialized');
    }
    
    // Auto-init fallback for non-Blazor load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function(){ try{ initProfil(); }catch(e){} });
    } else {
        try{ initProfil(); }catch(e){}
    }
    
    return initProfil;
}));
