// Jejak — timeline cards
export function initJejak() {
if(window.__jejakInit)return;window.__jejakInit=true;

const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('show');io.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll('.in').forEach(el=>io.observe(el));

/* ===== threeui components ===== */
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 1. animated grid pattern — header */
  var hg = document.getElementById('tuHeroGrid');
  if(hg){
    var g = hg.getContext('2d'), goff = 0, gridVisible=true, gridRaf=0;
    try{ new IntersectionObserver(function(e){ gridVisible=e[0].isIntersecting; if(gridVisible&&!gridRaf&&!reduce) gridRaf=requestAnimationFrame(drawGrid); },{threshold:0}).observe(hg); }catch(e){}
    function drawGrid(){
      gridRaf=0;
      if(!gridVisible){ gridRaf=requestAnimationFrame(drawGrid); return; }
      var dpr = Math.min(devicePixelRatio||1, 2);
      var W = hg.width = Math.max(1, hg.clientWidth*dpr), H = hg.height = Math.max(1, hg.clientHeight*dpr);
      g.clearRect(0,0,W,H);
      var sp = 26*dpr;
      g.strokeStyle = 'rgba(37,99,201,.16)'; g.lineWidth = 1*dpr;
      g.setLineDash([5*dpr, 9*dpr]); g.lineDashOffset = -goff*dpr;
      for(var x=0;x<W;x+=sp){ g.beginPath(); g.moveTo(x,0); g.lineTo(x,H); g.stroke(); }
      for(var y=0;y<H;y+=sp){ g.beginPath(); g.moveTo(0,y); g.lineTo(W,y); g.stroke(); }
      if(!reduce){ goff += 0.45; gridRaf=requestAnimationFrame(drawGrid); }
    }
    if(reduce){ drawGrid(); addEventListener('resize', drawGrid, {passive:true}); } else { gridRaf=requestAnimationFrame(drawGrid); document.addEventListener('visibilitychange', function(){ if(document.hidden){ if(gridRaf)cancelAnimationFrame(gridRaf); gridRaf=0; } else if(gridVisible&&!gridRaf) gridRaf=requestAnimationFrame(drawGrid); }); }
  }

  /* 2. marquee — infinite horizontal */
  var track = document.getElementById('tuMqTrack');
  if(track && !reduce){
    var seq = track.innerHTML;
    for(var k=0;k<3;k++) track.insertAdjacentHTML('beforeend', seq);
    var mx = 0, third = 0;
    function measure(){ third = track.scrollWidth/4 || 1; }
    measure(); addEventListener('resize', measure, {passive:true});
    function mqLoop(){
      mx -= 0.45;
      if(third>0 && mx <= -third) mx = 0;
      track.style.transform = 'translateX('+mx+'px)';
      requestAnimationFrame(mqLoop);
    }
    requestAnimationFrame(mqLoop);
  }

  /* 3. particles — ledger snapshot panel */
  var pc = document.getElementById('tuSnapParticles');
  if(pc){
    var q = pc.getContext('2d'), pts = [], Wp=0, Hp=0;
    function initPts(){
      var dpr = Math.min(devicePixelRatio||1, 2);
      Wp = pc.width = Math.max(1, pc.clientWidth*dpr); Hp = pc.height = Math.max(1, pc.clientHeight*dpr);
      var n = Math.min(56, Math.round(Wp*Hp/26000));
      pts = [];
      for(var i=0;i<n;i++) pts.push({x:Math.random()*Wp, y:Math.random()*Hp,
        vx:(Math.random()-0.5)*0.35*dpr, vy:(Math.random()-0.5)*0.35*dpr, r:(0.8+Math.random()*1.4)*dpr});
    }
    initPts(); addEventListener('resize', initPts, {passive:true});
    function drawPts(){
      q.clearRect(0,0,Wp,Hp);
      for(var i=0;i<pts.length;i++){
        var p = pts[i];
        p.x += p.vx; p.y += p.vy;
        if(p.x<0||p.x>Wp) p.vx*=-1;
        if(p.y<0||p.y>Hp) p.vy*=-1;
        q.fillStyle = 'rgba(255,255,255,.5)';
        q.beginPath(); q.arc(p.x,p.y,p.r,0,Math.PI*2); q.fill();
      }
      q.strokeStyle = 'rgba(255,255,255,.10)'; q.lineWidth = 1;
      for(var a=0;a<pts.length;a++) for(var b=a+1;b<pts.length;b++){
        var dx=pts[a].x-pts[b].x, dy=pts[a].y-pts[b].y, d=Math.hypot(dx,dy);
        if(d < 90*(devicePixelRatio||1)){
          q.globalAlpha = 1 - d/(90*(devicePixelRatio||1));
          q.beginPath(); q.moveTo(pts[a].x,pts[a].y); q.lineTo(pts[b].x,pts[b].y); q.stroke();
        }
      }
      q.globalAlpha = 1;
      if(!reduce) requestAnimationFrame(drawPts);
    }
    drawPts();
  }

  /* 4. magic card spotlight — brief cards */
  if(!reduce){
    document.querySelectorAll('.card, .pos').forEach(function(card){
      if(card.querySelector('.tu-spot')) return;
      var spot = document.createElement('div');
      spot.className = 'tu-spot';
      card.insertBefore(spot, card.firstChild);
      card.addEventListener('pointermove', function(e){
        var r = card.getBoundingClientRect();
        spot.style.opacity = '1';
        spot.style.background = 'radial-gradient(340px 220px at '+(e.clientX-r.left)+'px '+(e.clientY-r.top)+'px, rgba(37,99,201,.13), transparent 62%)';
      });
      card.addEventListener('pointerleave', function(){ spot.style.opacity = '0'; });
    });
  }

  /* 5. number ticker — KPI snapshot + realized total */
  function ticker(el, target, fmt, dur){
    if(!el) return;
    if(reduce){ el.textContent = fmt ? fmt(target) : String(target); return; }
    var start = performance.now(); dur = dur || 1300;
    (function f(now){
      var t = Math.min(1, (now-start)/dur);
      var e = 1 - Math.pow(1-t, 3);
      el.textContent = fmt ? fmt(target*e) : Math.round(target*e).toLocaleString('id-ID');
      if(t < 1) requestAnimationFrame(f); else el.textContent = fmt ? fmt(target) : String(target);
    })(start);
  }
  var kpis = document.querySelectorAll('.kpi strong');
  if(kpis.length){
    var vals = [70, 70, 0];
    var kio = new IntersectionObserver(function(es){
      es.forEach(function(e){
        if(!e.isIntersecting) return;
        var idx = [].indexOf.call(kpis, e.target);
        ticker(e.target, vals[idx] != null ? vals[idx] : parseFloat(e.target.textContent.replace(/\D/g,'')) || 0);
        kio.unobserve(e.target);
      });
    }, {threshold:.4});
    kpis.forEach(function(k){ kio.observe(k); });
  }
})();

// border-beam rotate
let a=0; const beams=document.querySelectorAll('.beam');
const reduceTick=matchMedia('(prefers-reduced-motion:reduce)').matches;
let tickVisible=true, tickRaf=0;
try{ new IntersectionObserver(function(e){ tickVisible=e[0].isIntersecting; if(tickVisible&&!tickRaf&&!reduceTick) tickRaf=requestAnimationFrame(tick); },{threshold:0}).observe(beams[0]||document.body); }catch(e){}
function tick(){ tickRaf=0; if(reduceTick||!tickVisible){ tickRaf=requestAnimationFrame(tick); return; } a=(a+0.32)%360; beams.forEach(b=>b.style.setProperty('--a',a+'deg')); tickRaf=requestAnimationFrame(tick); }
if(!reduceTick) tickRaf=requestAnimationFrame(tick);
document.addEventListener('visibilitychange', function(){ if(document.hidden){ if(tickRaf)cancelAnimationFrame(tickRaf); tickRaf=0; } else if(tickVisible&&!tickRaf&&!reduceTick) tickRaf=requestAnimationFrame(tick); });


addEventListener("DOMContentLoaded",function(){var s=document.querySelector("a.skip"),m=document.getElementById("main");if(s&&m){s.addEventListener("click",function(e){try{m.focus({preventScroll:true});}catch(_){m.focus();}});}});
console.log('Jejak initialized');
}
