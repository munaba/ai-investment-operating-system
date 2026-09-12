// Ikhtisar page - UMD wrapper
(function(root, factory) {
    if (typeof define === 'function' && define.amd) {
        define([], factory);
    } else if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.initIkhtisar = factory();
    }
}(typeof self !== 'undefined' ? self : this, function() {
    'use strict';
    
/* ===== AIOS motion — reveal scrub + parallax + header morph + bars ===== */
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduce) return;

  var sel = 'h2, h3, p, a[href^="aios-"], div[class*="rounded"], img[src*="logo"]';
  var items = [].slice.call(document.querySelectorAll(sel)).filter(function(el){ return !el.closest('header'); });

  // set awal: tersembunyi tapi akan dipaksa tampil kalau IO gagal
  // R7b: no static willChange — apply on entry, remove on settle via IO callback
  items.forEach(function(el){
    el.style.transition = 'opacity .75s cubic-bezier(.22,1,.36,1), transform .75s cubic-bezier(.22,1,.36,1)';
    el.style.opacity = '0';
    el.style.transform = 'translateY(28px)';
  });

  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(!e.isIntersecting) return;
      var el=e.target;
      el.style.willChange = 'opacity, transform'; // R7b: apply on entry
      var sibs=[].slice.call(el.parentNode?el.parentNode.children:[]);
      var idx=Math.max(0,sibs.indexOf(el));
      el.style.transitionDelay = Math.min(idx*55,420)+'ms';
      el.style.opacity='1';
      el.style.transform='none';
      setTimeout(function(){ el.style.willChange='auto'; },850); // remove after settle
      io.unobserve(el);
    });
  },{threshold:0.12, rootMargin:'0px 0px -6% 0px'});
  items.forEach(function(el){ io.observe(el); });

  // pengaman: hanya paksa yang SUDAH di viewport tapi masih 0 (IO gagal total)
  // yang masih di bawah layar biarkan 0 — akan reveal pas discroll
  setTimeout(function(){
    items.forEach(function(el){
      var r=el.getBoundingClientRect();
      var inView = r.top < innerHeight && r.bottom > 0;
      if(inView && parseFloat(getComputedStyle(el).opacity) < 0.1){
        el.style.transition='none'; el.style.opacity='1'; el.style.transform='none';
      }
    });
  },1400);

  // header morph + hero parallax + bars heights + parallax foto
  var surf=document.querySelector('.header-surface'),
      scrim=document.querySelector('.header-scrim'),
      wm=document.querySelector('.header-wordmark'),
      bar=document.querySelector('header'),
      h1=document.querySelector('h1'),
      heroImg=document.querySelector('img[src*="fotoHero"]'),
      barsWrap=document.querySelector('div[style*="height:280px"]'),
      bars=barsWrap? [].slice.call(barsWrap.querySelectorAll('div[style*="bars.webp"]')) : [],
      about=document.getElementById('about'),
      highlights=document.querySelector('[aria-label="Highlights"]'),
      ticking=false, tickParallax=false;

  // simpan tinggi awal bars untuk lerp
  var barsBase = bars.map(function(b){
    var m=(b.style.height||'').match(/([\d.]+)%/);
    return m? parseFloat(m[1]) : 50;
  });

  function onScroll(){
    ticking=false;
    var y=scrollY;
    var p=Math.min(y/220,1);
    if(surf) surf.style.opacity=String(p);
    if(scrim) scrim.style.textShadow = p>.5 ? '0 1px 10px rgba(0,0,51,.85)' : 'none';
    if(wm){ wm.style.opacity=String(1-p*.7); wm.style.maxWidth=(9*(1-p))+'rem'; wm.style.transform='translate('+(-8*p)+'px)'; }
    if(bar) bar.style.backdropFilter = p>.5 ? 'blur(14px)' : 'none';
    if(h1){ var q=Math.min(y/720,1); h1.style.transform='translateY('+(q*-34)+'px) scale('+(1-q*.05)+')'; h1.style.opacity=String(1-q*.45); }
    if(heroImg){ var r=Math.min(y/1100,1); heroImg.style.transform='translateY('+(r*36)+'px) scale('+(1+r*.04)+')'; }
  }

  var barsVisible=true, barsInterval=0;
  try{ new IntersectionObserver(function(e){ barsVisible=e[0].isIntersecting; if(barsVisible&&!barsInterval&&!document.hidden) barsInterval=setInterval(function(){ if(document.hidden||!barsVisible) return; if(!tickParallax){tickParallax=true; requestAnimationFrame(onScrollParallax);} }, 32); },{threshold:0}).observe(barsWrap||highlights||document.body); }catch(e){}
  function onScrollParallax(){
    tickParallax=false;
    if(barsVisible&&bars.length){
      var tt = Date.now()/1100;
      bars.forEach(function(b,i){
        var base=barsBase[i];
        var amp = 8 + (i%3)*3.5;
        // eased sinus + small drift, no jump
        var off = Math.sin(tt*.9 + i*.52) * amp + Math.cos(tt*.45 + i*.31)*2;
        // smooth lerp to target instead of snap
        var target = Math.max(14, Math.min(88, base + off));
        var cur = parseFloat(b.style.height)||base;
        var next = cur + (target - cur)*0.18;
        b.style.height = next.toFixed(1)+'%';
      });
    }
    if(highlights){
      var rect=highlights.getBoundingClientRect();
      var vh = innerHeight||900;
      var prog = Math.max(0, Math.min(1, (vh*0.85 - rect.top) / (vh*0.7 + rect.height)));
      var bar2 = highlights.querySelector('div[style*="scaleX"]');
      if(bar2){
        var cur = bar2._prog || 0;
        bar2._prog = cur + (prog - cur)*0.12;
        bar2.style.transform='scaleX('+bar2._prog.toFixed(4)+')';
      }
    }
  }

  addEventListener('scroll', function(){ if(!ticking){ticking=true; requestAnimationFrame(onScroll);} if(barsVisible&&!tickParallax){tickParallax=true; requestAnimationFrame(onScrollParallax);} }, {passive:true});
  onScroll();
  // bars loop — IO+visibility guard (PERF P1-2b)
  barsInterval=setInterval(function(){ if(document.hidden||!barsVisible) return; if(!tickParallax){tickParallax=true; requestAnimationFrame(onScrollParallax);} }, 32);
  document.addEventListener('visibilitychange', function(){ if(document.hidden){ if(barsInterval)clearInterval(barsInterval); barsInterval=0; } else if(barsVisible&&!barsInterval) barsInterval=setInterval(function(){ if(document.hidden||!barsVisible) return; if(!tickParallax){tickParallax=true; requestAnimationFrame(onScrollParallax);} }, 32); });

  // paksa lazy eager + smooth anchor
  document.querySelectorAll('img[loading="lazy"]').forEach(function(img){ img.loading='eager'; });
  document.querySelectorAll('a[href^="#"]').forEach(function(a){
    a.addEventListener('click', function(ev){
      var el=document.getElementById(a.getAttribute('href').slice(1));
      if(!el) return; ev.preventDefault(); el.scrollIntoView({behavior:'smooth',block:'start'});
    });
  });
})();

/* ===== threeui components (additive) ===== */
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(reduce) return;

  /* 1. meteors — hero */
  var mc = document.getElementById('tuMeteors');
  if(mc){
    var g = mc.getContext('2d'), ms = [], W=0, H=0, dpr = Math.min(devicePixelRatio||1,2), mcVisible=true, mcRaf=0;
    try{ new IntersectionObserver(function(e){ mcVisible=e[0].isIntersecting; if(mcVisible&&!mcRaf) mcRaf=requestAnimationFrame(draw); },{threshold:0}).observe(mc); }catch(e){}
    function mSize(){ W = mc.width = Math.max(1, mc.clientWidth*dpr); H = mc.height = Math.max(1, mc.clientHeight*dpr); }
    function spawn(){ ms.push({x: Math.random()*W*1.3, y: -120*dpr, vx: -(3+Math.random()*5)*dpr, vy: (1.6+Math.random()*1.8)*dpr, len: (70+Math.random()*110)*dpr}); }
    function draw(){ mcRaf=0; if(!mcVisible){ mcRaf=requestAnimationFrame(draw); return; } g.clearRect(0,0,W,H); for(var i=0;i<ms.length;i++){ var m = ms[i]; m.x += m.vx; m.y += m.vy; var grad = g.createLinearGradient(m.x, m.y, m.x+m.len, m.y-m.len*0.5); grad.addColorStop(0,'rgba(255,229,0,0)'); grad.addColorStop(0.55,'rgba(255,229,0,.55)'); grad.addColorStop(1,'rgba(255,255,255,.92)'); g.strokeStyle = grad; g.lineWidth = 1.5*dpr; g.beginPath(); g.moveTo(m.x,m.y); g.lineTo(m.x+m.len, m.y-m.len*0.5); g.stroke(); g.fillStyle = 'rgba(255,255,255,.9)'; g.beginPath(); g.arc(m.x,m.y,1.7*dpr,0,Math.PI*2); g.fill(); } ms = ms.filter(function(m){ return m.y < H+160*dpr && m.x > -420*dpr; }); if(Math.random() < 0.035) spawn(); mcRaf=requestAnimationFrame(draw); }
    mSize();
    for(var i=0;i<7;i++) spawn();
    addEventListener('resize', mSize, {passive:true});
    mcRaf=requestAnimationFrame(draw);
    document.addEventListener('visibilitychange', function(){ if(document.hidden){ if(mcRaf)cancelAnimationFrame(mcRaf); mcRaf=0; } else if(mcVisible&&!mcRaf) mcRaf=requestAnimationFrame(draw); });
  }

  /* 2. retro grid — section More to Come */
  var rc = document.getElementById('tuJEJAKGrid');
  if(rc){
    var r2 = rc.getContext('2d'), off = 0, RW=0, RH=0, rdpr = Math.min(devicePixelRatio||1,2), rcVisible=true, rcRaf=0;
    try{ new IntersectionObserver(function(e){ rcVisible=e[0].isIntersecting; if(rcVisible&&!rcRaf) rcRaf=requestAnimationFrame(drawR); },{threshold:0}).observe(rc); }catch(e){}
    function drawR(){ rcRaf=0; if(!rcVisible){ rcRaf=requestAnimationFrame(drawR); return; } RW = rc.width = Math.max(1, rc.clientWidth*rdpr); RH = rc.height = Math.max(1, rc.clientHeight*rdpr); var horizon = RH*0.55; r2.clearRect(0,0,RW,RH); r2.strokeStyle = 'rgba(120,180,255,.20)'; r2.lineWidth = 1*rdpr; off = (off + 0.55) % 34; for(var i=-22;i<=22;i++){ var x = RW/2 + i*40*rdpr; r2.beginPath(); r2.moveTo(x,RH); r2.lineTo(RW/2 + i*4*rdpr, horizon); r2.stroke(); } for(var y2=0;y2<26;y2++){ var t = y2/26; var yy = horizon + Math.pow(t,1.6)*(RH-horizon) + off*rdpr*t; if(yy > RH) continue; r2.beginPath(); r2.moveTo(0,yy); r2.lineTo(RW,yy); r2.stroke(); } var lg = r2.createLinearGradient(0, horizon-46*rdpr, 0, horizon+46*rdpr); lg.addColorStop(0,'transparent'); lg.addColorStop(0.5,'rgba(120,180,255,.16)'); lg.addColorStop(1,'transparent'); r2.fillStyle = lg; r2.fillRect(0, horizon-46*rdpr, RW, 92*rdpr); rcRaf=requestAnimationFrame(drawR); }
    rcRaf=requestAnimationFrame(drawR);
    document.addEventListener('visibilitychange', function(){ if(document.hidden){ if(rcRaf)cancelAnimationFrame(rcRaf); rcRaf=0; } else if(rcVisible&&!rcRaf) rcRaf=requestAnimationFrame(drawR); });
  }

  /* 3. marquee emas — infinite */
  var track = document.getElementById('tuMqTrack');
  if(track){
    var html = track.innerHTML;
    for(var k=0;k<3;k++) track.insertAdjacentHTML('beforeend', html);
    var mx = 0, seg = 0;
    function meas(){ seg = track.scrollWidth/4 || 1; }
    meas(); addEventListener('resize', meas, {passive:true});
    (function loop(){
      mx -= 0.4;
      if(seg > 0 && mx <= -seg) mx = 0;
      track.style.transform = 'translateX(' + mx + 'px)';
      requestAnimationFrame(loop);
    })();
  }

  /* 4. aurora text — Highlights */
  var au = document.getElementById('tuAurora');
  if(au){
    var pos = 0;
    (function loopA(){ pos = (pos + 0.16) % 220; au.style.backgroundPosition = pos + '% 50%'; requestAnimationFrame(loopA); })();
  }

  /* 5. border beam — kartu highlight (mengambang, tidak mengubah layout) */
  var hlRoot = document.querySelector('[aria-label="Highlights"]');
  var cards = hlRoot ? [].slice.call(hlRoot.querySelectorAll('div[class*="group/carousel"]')) : [];
  var beamDeg = 0;
  var made = [];
  cards.forEach(function(c, i){
    if(i > 11) return;
    if(c.querySelector('.tu-beam')) return;
    var cs = getComputedStyle(c);
    if(cs.position === 'static') c.style.position = 'relative';
    var b = document.createElement('div');
    b.className = 'tu-beam';
    c.appendChild(b);
    made.push(b);
  });
  if(made.length){
    (function loopB(){
      beamDeg = (beamDeg + 0.5) % 360;
      for(var i=0;i<made.length;i++) made[i].style.setProperty('--tu-a', beamDeg + 'deg');
      requestAnimationFrame(loopB);
    })();
  }
})();

try{var lenis=new Lenis({duration:1.15,easing:function(t){return 1-Math.pow(1-t,3)},smoothWheel:true,smoothTouch:false});function raf(time){lenis.raf(time);requestAnimationFrame(raf)}requestAnimationFrame(raf);document.addEventListener('visibilitychange',function(){if(document.hidden)try{lenis.stop()}catch(e){}else try{lenis.start()}catch(e){}});}catch(e){}

(function(){
  // keep files, override src via JS + inline style per TASK B
  var reduce = false;
  try{ reduce = matchMedia('(prefers-reduced-motion: reduce)').matches; }catch(e){}
  // hero fotoHero -> fieldSvg navy-gold + overlay 70·5·ACTIVE
  var fieldSvgRaw = "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='800' viewBox='0 0 1200 800'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='0'><stop offset='0%' stop-color='#0b1842'/><stop offset='100%' stop-color='#111e6a'/></linearGradient><linearGradient id='gg' x1='0' y1='1' x2='0' y2='0'><stop offset='0%' stop-color='#0b1842' stop-opacity='1'/><stop offset='100%' stop-color='#1a2a8a' stop-opacity='.85'/></linearGradient></defs><rect width='1200' height='800' fill='url(#g)'/><rect width='1200' height='800' fill='url(#gg)' opacity='.92'/><g stroke='#ffe500' stroke-opacity='.08' stroke-width='1'><path d='M0 120 H1200 M0 240 H1200 M0 360 H1200 M0 480 H1200 M0 600 H1200'/><path d='M200 0 V800 M400 0 V800 M600 0 V800 M800 0 V800 M1000 0 V800'/></g><circle cx='760' cy='260' r='180' fill='none' stroke='#ffe500' stroke-opacity='.10' stroke-width='1.5'/><circle cx='760' cy='260' r='88' fill='#ffe500' fill-opacity='.06' stroke='#ffe500' stroke-opacity='.14'/><text x='600' y='360' text-anchor='middle' font-family='ui-monospace,monospace' font-size='26' letter-spacing='.28em' fill='#ffe500' fill-opacity='.95'>70 &#183; 5 &#183; ACTIVE</text><text x='600' y='400' text-anchor='middle' font-family='ui-monospace,monospace' font-size='11' letter-spacing='.22em' fill='white' fill-opacity='.62'>AIOS &#183; 24 Agt &#8211; 23 Sep 2026 &#183; 68 MEDIUM / 2 LOW</text></svg>";
  var fieldSvg = 'data:image/svg+xml,' + encodeURIComponent(fieldSvgRaw);
  document.querySelectorAll('img[src*="fotoHero"]').forEach(function(img){
    img.src = fieldSvg;
    img.removeAttribute('srcset');
    img.style.objectFit='cover';
    img.style.objectPosition='center 42%';
    img.style.filter='none';
    img.alt='AIOS — 70 · 5 · ACTIVE';
    var wrap = img.closest('div.relative');
    if(wrap && !wrap.querySelector('.aios-hero-overlay')){
      var ov=document.createElement('div');
      ov.className='aios-hero-overlay';
      ov.setAttribute('aria-hidden','true');
      ov.style.cssText='position:absolute;inset:auto 0 18% 0;display:flex;flex-direction:column;align-items:center;gap:6px;z-index:6;pointer-events:none';
      ov.innerHTML='<span style="font-family:ui-monospace,monospace;font-size:.72rem;letter-spacing:.26em;color:#ffe500;background:rgba(11,24,66,.72);border:1px solid rgba(255,229,0,.22);padding:6px 14px;border-radius:999px;backdrop-filter:blur(6px)">70 · 5 · ACTIVE</span>';
      wrap.appendChild(ov);
    }
  });

  // 12 logoAkpro..Wirus -> badge SVG ticker + 6 concepts
  var badges = ['ANTM','BBCA','BMRI','TLKM','BRIS','ASII','ATRIUM','ATLAS','ARC','MATERI','JEJAK','WINDOW'];
  var sel = 'img[src*="logoAkpro"],img[src*="logoKastrat"],img[src*="logoKema"],img[src*="logoKesma"],img[src*="logoKestari"],img[src*="logoKomin"],img[src*="logoLitbang"],img[src*="logoPengmas"],img[src*="logoPiptek"],img[src*="logoRetro"],img[src*="logoSiwa"],img[src*="logoWirus"]';
  var logos = document.querySelectorAll(sel);
  // if count mismatched (after text replace src still contains logoX), try broader selector
  if(logos.length<6){
    // fallback: about section imgs
    var about=document.getElementById('about');
    if(about) logos = about.querySelectorAll('img');
  }
  logos.forEach(function(img,i){
    var label = badges[i % badges.length];
    var shortLabel = label.slice(0,5);
    var svg2 = "<svg xmlns='http://www.w3.org/2000/svg' width='280' height='280' viewBox='0 0 280 280'><rect width='280' height='280' rx='36' fill='#0b1842'/><rect x='1' y='1' width='278' height='278' rx='35' fill='none' stroke='#ffe500' stroke-opacity='.14'/><circle cx='140' cy='112' r='48' fill='#ffe500'/><text x='140' y='121' text-anchor='middle' font-family='ui-monospace,monospace' font-size='20' font-weight='800' fill='#0b1842' letter-spacing='.04em'>"+shortLabel+"</text><text x='140' y='182' text-anchor='middle' font-family='ui-monospace,monospace' font-size='12' letter-spacing='.16em' fill='#ffe500'>"+label+"</text><text x='140' y='204' text-anchor='middle' font-family='ui-monospace,monospace' font-size='9' letter-spacing='.18em' fill='white' fill-opacity='.58'>AIOS</text></svg>";
    img.src = 'data:image/svg+xml,'+encodeURIComponent(svg2);
    img.removeAttribute('srcset');
    img.alt = label;
    img.loading='eager';
  });

  // highlights2-10 9 cards -> gradient FIELD_AMBER/OCEAN each hue
  var hlSel = 'img[src*="highlights"],img[src*="highlight10"]';
  var hlImgs = document.querySelectorAll(hlSel);
  hlImgs.forEach(function(img,i){
    var hueA = (38 + i*22) % 360;
    var hueB = (212 + i*16) % 360;
    var cA = 'hsl('+hueA+' 94% 58%)';
    var cB = 'hsl('+hueB+' 82% 56%)';
    var svgH = "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='600' viewBox='0 0 600 600'><defs><linearGradient id='hg' x1='0' y1='0' x2='1' y2='1'><stop offset='0%' stop-color='"+cA+"'/><stop offset='100%' stop-color='"+cB+"'/></linearGradient><linearGradient id='hg2' x1='0' y1='1' x2='0' y2='0'><stop offset='0%' stop-color='black' stop-opacity='.18'/><stop offset='100%' stop-color='black' stop-opacity='0'/></linearGradient></defs><rect width='600' height='600' rx='16' fill='url(#hg)'/><rect width='600' height='600' rx='16' fill='url(#hg2)'/><text x='300' y='272' text-anchor='middle' font-family='ui-monospace,monospace' font-size='13' letter-spacing='.20em' fill='white' fill-opacity='.96'>AIOS &#183; "+(i+1)+"</text><text x='300' y='302' text-anchor='middle' font-family='ui-monospace,monospace' font-size='10' letter-spacing='.16em' fill='white' fill-opacity='.72'>70 &#183; 5 &#183; ACTIVE</text></svg>";
    img.src='data:image/svg+xml,'+encodeURIComponent(svgH);
    img.removeAttribute('srcset');
    img.style.objectFit='cover';
  });

  // element1-4 opacity .04 tint navy
  document.querySelectorAll('img[src*="element"]').forEach(function(img){
    img.style.opacity='.04';
    img.style.filter='sepia(1) hue-rotate(205deg) saturate(1.35) brightness(0.95)';
    img.style.mixBlendMode='normal';
  });

  // logo wolf -> orb AIOS amber
  document.querySelectorAll('img[src*="logo.webp"]').forEach(function(img){
    var orb = "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'><defs><radialGradient id='o' cx='50%' cy='38%'><stop offset='0%' stop-color='#ffd36a'/><stop offset='52%' stop-color='#ff9f1c'/><stop offset='100%' stop-color='#0b1842'/></radialGradient><linearGradient id='ring' x1='0' y1='0' x2='1' y2='1'><stop offset='0%' stop-color='#ffe500' stop-opacity='.85'/><stop offset='100%' stop-color='#ff9f1c' stop-opacity='.55'/></linearGradient></defs><rect width='200' height='200' rx='100' fill='#0b1842'/><circle cx='100' cy='100' r='66' fill='url(#o)' stroke='url(#ring)' stroke-width='1.5'/><text x='100' y='108' text-anchor='middle' font-family='ui-monospace,monospace' font-size='21' font-weight='800' fill='#0b1842' letter-spacing='.04em'>AIOS</text></svg>";
    img.src='data:image/svg+xml,'+encodeURIComponent(orb);
    img.removeAttribute('srcset');
    img.alt='AIOS';
  });

  // phonecta tw1-3 file.webp keep but caption handled via text replacement already; ensure alt updated
  document.querySelectorAll('img[src*="phonecta"],img[src*="tw1_card"],img[src*="tw2_card"],img[src*="tw3_card"],img[src*="file.webp"]').forEach(function(img){
    if(img.alt && img.alt.indexOf('IME')>-1) img.alt='AIOS — Atrium';
    if(img.alt==='') img.alt='AIOS';
  });
})();

addEventListener("DOMContentLoaded",function(){var s=document.querySelector("a.skip"),m=document.getElementById("main");if(s&&m){s.addEventListener("click",function(e){try{m.focus({preventScroll:true});}catch(_){m.focus();}});}});
    
    function initIkhtisar() {}
    return initIkhtisar;
}));
