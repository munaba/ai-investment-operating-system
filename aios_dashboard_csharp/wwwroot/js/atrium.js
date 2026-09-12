// Full port of aios-atrium.html module script — UMD (window.Lenis), no bundler needed
export function initAtrium() {
if (window.__atriumInit) return; window.__atriumInit = true;
// Components inventory — AIOS Atrium
// Hero: bg FIELD_AMBER (heroImg) + parallax 12% | Header: nav-left/nav-right/burger/menu overlay | Trust: ghost 8.2vw + coach-figure rotate6 + slides[3]
// Programs: 4 rows + orb thumb + arrow | Facilities: fac-icon + 2 cards (FIELD_AMBER/FIELD_OCEAN) | Stats: 4 cols bg FIELD_OCEAN overlay
// Testimonials: 3 cards + avatar orb | Footer: 3 cols + modal (f-name/f-email/f-msg) + Atur Notifikasi (bookHeader/footerCta/menuBook)
// Assets: ORB_OCEAN/AMBER/LAVA/EMERALD + FIELD_AMBER/OCEAN (data SVG) | Motion: Lenis + IntersectionObserver .15 + clip translateY(115%)
const Lenis = window.Lenis;
// THREE unused — aurora uses raw WebGL, rest is 2D canvas/WAAPI
/* M-07: data di file ini literal const (bukan URL/API). esc()/safeHref() kunci sink bila sumber berubah; tanpa ubah visual. */
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function safeHref(h){h=String(h);return /^(#|\/(?!\/)|aios-[a-z0-9-]+\.html([#?].*)?$)/i.test(h)?h:'#'}
function orbSvg(stops){
  const grad=stops.map(s=>'<stop offset="'+s[0]+'" stop-color="'+s[1]+'"/>').join('');
  return 'data:image/svg+xml;utf8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><defs><radialGradient id="g" cx="32%" cy="30%" r="75%">'+grad+'</radialGradient></defs><rect width="200" height="200" fill="#0a0a0f"/><circle cx="100" cy="100" r="92" fill="url(#g)"/></svg>');
}
function fieldSvg(c1,c2,c3){
  return 'data:image/svg+xml;utf8,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="'+c1+'"/><stop offset="100%" stop-color="'+c3+'"/></linearGradient><filter id="b"><feGaussianBlur stdDeviation="30"/></filter></defs><rect width="300" height="400" fill="url(#lg)"/><circle cx="90" cy="120" r="90" fill="'+c2+'" opacity="0.55" filter="url(#b)"/><circle cx="230" cy="300" r="110" fill="'+c1+'" opacity="0.4" filter="url(#b)"/></svg>');
}
// AIOS palette: navy #0f2f63 / amber #ffb347 / gold #ffe500 — ponytail: 4 orbs only, add more when brand expands
const ORB_NAVY=orbSvg([['0%','#dbe6ff'],['35%','#2a5db0'],['65%','#0f2f63'],['100%','#071633']]);
const ORB_AMBER=orbSvg([['0%','#fff8e7'],['22%','#ffb347'],['52%','#ff7a00'],['88%','#7a2e00']]);
const ORB_GOLD=orbSvg([['0%','#fffbe6'],['25%','#ffe500'],['55%','#ffb347'],['90%','#8a5a00']]);
const ORB_NAVY_GOLD=orbSvg([['0%','#ffe500'],['30%','#ffb347'],['62%','#1a3a7a'],['100%','#0f2f63']]);
const FIELD_AMBER=fieldSvg('#0f2f63','#ffb347','#ffe500');
const FIELD_OCEAN=fieldSvg('#071633','#0f2f63','#ffb347');
const I1=ORB_AMBER, I2=ORB_NAVY, I3=ORB_GOLD, I4=ORB_NAVY_GOLD, I5=ORB_NAVY;
const ORB_OCEAN=ORB_NAVY, ORB_LAVA=ORB_NAVY_GOLD, ORB_EMERALD=ORB_GOLD;
document.getElementById('memberImg').src=ORB_OCEAN;
document.getElementById('facIconImg').src=ORB_AMBER;
document.getElementById('facImg1').src=FIELD_AMBER;
document.getElementById('facImg2').src=FIELD_OCEAN;
document.getElementById('heroImg').src=FIELD_AMBER;
// bg images for sections
try{
  document.getElementById('stats').style.setProperty('--bg','url('+FIELD_OCEAN+')');
  document.querySelector('#stats').style.backgroundImage='url('+FIELD_OCEAN+')';
  document.querySelector('#stats').style.backgroundSize='cover';
  document.querySelector('#stats').style.backgroundBlendMode='overlay';
}catch{}
// apply via pseudo element content trick: set ::before background via JS
(function(){
  const s=document.getElementById('stats');
  const pr=document.getElementById('programs');
  const te=document.getElementById('testimonials');
  // inject style for ::before
  const st=document.createElement('style');
  st.textContent='#stats::before{background-image:url('+FIELD_OCEAN+')} #programs::before{background-image:url('+FIELD_AMBER+')} #testimonials::before{background-image:url('+ORB_OCEAN+')}';
  document.head.appendChild(st);
})();
window.scrollTo(0,0);
const lenis=new Lenis({duration:1.15,easing:function(t){return 1-Math.pow(1-t,3)},smoothWheel:true,smoothTouch:false,gestureOrientation:'vertical'});
function raf(t){lenis.raf(t);requestAnimationFrame(raf)}
requestAnimationFrame(raf);
document.addEventListener('visibilitychange',function(){if(document.hidden)try{lenis.stop()}catch(e){}else try{lenis.start()}catch(e){}});
function lock(){try{lenis.stop()}catch{};document.documentElement.style.position='relative';document.documentElement.style.overflow='hidden';document.documentElement.style.height='100%'}
function unlock(){try{lenis.start()}catch{};document.documentElement.style.removeProperty('position');document.documentElement.style.removeProperty('overflow');document.documentElement.style.removeProperty('height')}
const FONT_BASE=16,BASE_W=1920,COEF=.6666;
function adaptive(){const w=innerWidth;const reduction=((BASE_W-w)/BASE_W)*100*COEF;const size=FONT_BASE-(FONT_BASE*reduction)/100;if(size>FONT_BASE) document.documentElement.style.fontSize=size+'px';else document.documentElement.style.removeProperty('font-size')}
adaptive();addEventListener('resize',adaptive);
function springStep(s){const dt=1/60; s.v+=(-s.tension*(s.x-s.target)-s.friction*s.v)*dt; s.x+=s.v*dt; if(Math.abs(s.x-s.target)<.001&&Math.abs(s.v)<.001){s.x=s.target;s.v=0;s.done=true}}
function easeOutExpo(t){return t===1?1:1-Math.pow(2,-10*t)}
function easeInOutCubic(t){return t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2}
function easeOutQuart(t){return 1-Math.pow(1-t,4)}
lock();
const loader=document.getElementById('loader'),fill=document.getElementById('loaderFill'),mark=document.getElementById('loaderMark');
const MIN_VISIBLE_MS=1400,MAX_VISIBLE_MS=2600,EXIT_MS=850;
let ready=false;
requestAnimationFrame(()=>mark.classList.add('show'));
let loadFired=document.readyState==='complete';
addEventListener('load',()=>loadFired=true);
let maxTimer=setTimeout(()=>{if(!loadFired) startCountdown()},MAX_VISIBLE_MS);
function startCountdown(){
  const start=performance.now();
  const delay=120, dur=MIN_VISIBLE_MS-delay;
  function tick(now){
    const t=Math.min((now-start)/dur,1);
    const tt=Math.max(0,(now-start-delay)/dur);
    const e=easeInOutCubic(Math.min(tt,1));
    fill.style.transform='scaleX('+e+')';
    if(t<1) requestAnimationFrame(tick);
    else finish();
  }
  setTimeout(()=>requestAnimationFrame(tick),delay);
  requestAnimationFrame(tick);
}
if(loadFired) startCountdown(); else {
  const check=setInterval(()=>{if(loadFired){clearInterval(check);clearTimeout(maxTimer);startCountdown()}},50);
  setTimeout(()=>{clearInterval(check)},MAX_VISIBLE_MS);
}
function finish(){
  ready=true;
  unlock();
  loader.classList.add('out');
  setTimeout(()=>loader.remove(),EXIT_MS);
  revealHero();
  startCollection();
}
const reduceMotion=matchMedia('(prefers-reduced-motion:reduce)').matches;
// 4+5) stats/woven dipindah ke halaman Arc/Materi — Atrium ringan (aurora+constellation saja)

if(reduceMotion){
  fill.style.transition='transform .2s';
  fill.style.transform='scaleX(1)';
  setTimeout(()=>{ready=true;unlock();loader.remove();revealHero();startCollection()},200);
}
function revealHero(){
  const title=document.getElementById('hero-title');
  const words="Cerita Di Balik Angka".split(' ');
  title.innerHTML='';
  words.forEach((w,i)=>{
    const c=document.createElement('span');c.className='clip';c.style.paddingBottom='.02em';
    const inner=document.createElement('span');inner.textContent=w;inner.style.transition='transform 1.1s cubic-bezier(.16,1,.3,1),opacity 1.1s cubic-bezier(.16,1,.3,1)';inner.style.transitionDelay=(i*140)+'ms';
    c.appendChild(inner);title.appendChild(c);title.appendChild(document.createTextNode(' '));
    requestAnimationFrame(()=>requestAnimationFrame(()=>{inner.style.transform='translateY(0)';inner.style.opacity='1'}));
  });
  document.querySelectorAll('#hero-tagline .clip span').forEach((el,i)=>{
    el.style.transition='transform .9s cubic-bezier(.16,1,.3,1),opacity .9s';el.style.transitionDelay=(350+i*110)+'ms';
    requestAnimationFrame(()=>requestAnimationFrame(()=>{el.style.transform='translateY(0)';el.style.opacity='1'}));
  });
  document.querySelectorAll('#programs-title .clip span, #facilities-title .clip span, #stats-title .clip span, #contact .clip span, #modalTitle .clip span').forEach(el=>{
    el.style.transform='translateY(115%)';el.style.opacity='0';el.style.display='inline-block';
  });
}
const io=new IntersectionObserver(es=>es.forEach(e=>{
  if(e.isIntersecting){
    const d=parseInt(e.target.dataset.delay||'0');
    setTimeout(()=>e.target.classList.add('show'),d);
    e.target.querySelectorAll('.clip span').forEach((s,i)=>{
      s.style.transition='transform .95s cubic-bezier(.16,1,.3,1),opacity .95s';s.style.transitionDelay=(i*120)+'ms';
      requestAnimationFrame(()=>{s.style.transform='translateY(0)';s.style.opacity='1'});
    });
    io.unobserve(e.target);
  }
}),{threshold:.15});
document.querySelectorAll('.inview, #programs-title, #facilities-title, #stats-title, #contact h2, #modalTitle').forEach(el=>io.observe(el));
document.getElementById('collectionSlider').dataset.delay='650';
document.getElementById('membershipCard').dataset.delay='780';
document.getElementById('facIcon').dataset.delay='0';
const hero=document.getElementById('hero'),parallax=document.getElementById('heroParallax');
function onScroll(){
  const rect=hero.getBoundingClientRect(),h=innerHeight;
  const p=Math.max(0,Math.min(1,(h-rect.top)/(h+rect.height)));
  parallax.style.transform='translateY('+(p*12)+'%)';
  const trust=document.getElementById('trust');
  const tr=trust.getBoundingClientRect();
  const tp=Math.max(0,Math.min(1,(h-tr.top)/(h+tr.height)));
  document.querySelectorAll('.ghost-word').forEach((el,i)=>{
    const maps=[[-3,3],[3,-3],[-2,4],[4,-3]];
    const m=maps[i%4]||[0,0];
    const x=m[0]+(m[1]-m[0])*tp;
    el.style.transform='translateX('+x+'%)';
  });
}
addEventListener('scroll',onScroll,{passive:true}); onScroll();
const collections=[
  {img:I2,brand:'POLICY_BLOCKED',title:'ANTM — tanpa risk, ditahan',cta:'Lihat alasan →',alt:'Sinyal ditahan'},
  {img:I3,brand:'SUCCESS',title:'ANTM 3170 → 3296 rasio 2,0',cta:'Buka jejak →',alt:'Sinyal terbuka'},
  {img:I5,brand:'ACTIVE',title:'Phase H 24 Ags–23 Sep 2026',cta:'Lihat window →',alt:'Window aktif'},
];
let colIdx=0,colTimer=null;
const colCard=document.getElementById('collectionCard'),colDots=document.getElementById('collectionDots');
function renderCollection(){
  const c=collections[colIdx];
  colCard.innerHTML='<img src="'+esc(c.img)+'" alt="'+esc(c.alt)+'" loading="lazy"><div style="min-width:0"><div style="font-size:.7rem;font-weight:500;text-transform:uppercase;letter-spacing:.06em">'+esc(c.brand)+'</div><div style="font-size:.7rem;text-transform:uppercase;opacity:.8">'+esc(c.title)+'</div><a href="aios-atrium.html" style="font-size:.65rem;text-decoration:underline">'+esc(c.cta)+' →</a></div>';
  colDots.innerHTML=collections.map((_,i)=>'<button aria-label="Go to '+(i+1)+'" data-i="'+i+'"><i style="width:'+(i===colIdx?'1.25rem':'.375rem')+';background:'+(i===colIdx?'#fff':'rgba(255,255,255,.4)')+'"></i></button>').join('');
  colDots.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{colIdx=parseInt(b.dataset.i);renderCollection();restartCol()}));
}
function restartCol(){clearInterval(colTimer);colTimer=setInterval(()=>{colIdx=(colIdx+1)%collections.length;colCard.style.opacity='0';colCard.style.transform='translateY(16px) scale(.96)';setTimeout(()=>{renderCollection();colCard.style.opacity='1';colCard.style.transform='translateY(0) scale(1)'},220)},3800)}
function startCollection(){renderCollection();restartCol()}
const slides=[
  {headline:['Dua','Ditahan','Tiga','Terbuka'],img:I1,name:'2 POLICY_BLOCKED',role:'Tanpa entry/stop/target — tidak pernah dikarang',alt:'Orb ditahan amber'},
  {headline:['Tiga','Terbuka','Rasio','2,0'],img:I3,name:'3 SUCCESS',role:'ANTM 3170 → 3106 → 3296 — plan lengkap',alt:'Orb terbuka emerald'},
  {headline:['Satu','Window','Masih','Aktif'],img:I4,name:'Phase H ACTIVE',role:'24 Ags – 23 Sep 2026 · belum closed',alt:'Orb window lava'},
];
let trustIdx=0;
const ghostHeading=document.getElementById('ghostHeading'),coachImg=document.getElementById('coachImg'),coachName=document.getElementById('coachName'),coachRole=document.getElementById('coachRole'),trustDots=document.getElementById('trustDots');
function renderTrust(){
  const s=slides[trustIdx];
  ghostHeading.innerHTML='<div class="ghost-row"><span class="ghost-word" style="color:#d7dae1"><span>'+esc(s.headline[0])+'</span></span><span class="ghost-word" style="color:#d7dae1"><span>'+esc(s.headline[1])+'</span></span></div><div class="ghost-row"><span class="ghost-word" style="color:#0a0a0a"><span>'+esc(s.headline[2])+'</span></span><span class="ghost-word" style="color:#d7dae1"><span>'+esc(s.headline[3])+'</span></span></div>';
  requestAnimationFrame(()=>ghostHeading.querySelectorAll('.ghost-word').forEach((el,i)=>setTimeout(()=>el.classList.add('show'),i*80)));
  coachImg.style.opacity='0';setTimeout(()=>{coachImg.src=s.img;coachImg.alt=s.alt;coachName.textContent=s.name;coachRole.textContent=s.role;coachImg.style.opacity='1'},180);
  trustDots.innerHTML=slides.map((_,i)=>'<button aria-label="Go to '+(i+1)+'" data-i="'+i+'" aria-current="'+(i===trustIdx?'true':'false')+'"><i style="width:'+(i===trustIdx?'1.25rem':'.375rem')+';background:'+(i===trustIdx?'#0a0a0a':'#d7dae1')+'"></i></button>').join('');
  trustDots.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{trustIdx=parseInt(b.dataset.i);renderTrust()}));
}
renderTrust();
document.getElementById('trustPrev').addEventListener('click',()=>{trustIdx=(trustIdx-1+slides.length)%slides.length;renderTrust()});
document.getElementById('trustNext').addEventListener('click',()=>{trustIdx=(trustIdx+1)%slides.length;renderTrust()});
const programs=[
  {n:'01',name:'Ranking 70',desc:'70 snapshot diranking skor 38 MEDIUM — belum ada yang naik kelas, semua ditahan di watchlist.',href:'#ranking',w:100,col:'#2563c9'},
  {n:'02',name:'Keputusan 5',desc:'2 ditahan (tanpa risk param) · 3 terbuka (3170 → 3296 rasio 2,0). POLICY_BLOCKED bukan bug.',href:'#briefs',w:60,col:'#2ecc71'},
  {n:'03',name:'Window ACTIVE',desc:'Phase H 24 Ags – 23 Sep 2026 Asia/Jakarta — observasi berjalan, belum ditutup.',href:'#window',w:45,col:'#ffb347'},
  {n:'04',name:'Jurnal 0',desc:'Belum ada entry. 3 posisi tertutup (BBCA×2, TLKM) menunggu catatan.',href:'#journal',w:8,col:'#595959'},
];
const progList=document.getElementById('programList');
programs.forEach((p,i)=>{
  const li=document.createElement('li');li.className='program-row inview';li.dataset.delay=i*90;
  const orb=[I1,I2,I3,I4][i%4]; li.innerHTML='<a class="program-link" href="'+safeHref(p.href)+'"><img src="'+orb+'" alt="" loading="lazy" style="width:2.75rem;height:2.75rem;border-radius:.75rem;object-fit:cover;flex-shrink:0;border:1px solid #e6e8ec"><span class="program-index">'+esc(p.n)+'</span><span style="flex:1"><span class="program-name">'+esc(p.name)+'</span><span class="program-desc" style="display:block">'+esc(p.desc)+'</span><span class="prog-meter"><i data-w="'+p.w+'" style="background:'+p.col+'"></i></span></span><span class="program-arrow"><span><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></span></span></a>';
  progList.appendChild(li);io.observe(li);
});
const facText="Semua narasi ditarik dari ranking_snapshots (70) dan decision_briefs (5) — data yang sama di layar, bukan kotak hitam.";
const facBody=document.getElementById('facBody');
facText.split(' ').forEach((w,i)=>{
  const s=document.createElement('span');s.textContent=w+' ';s.style.display='inline-block';s.style.opacity='0';s.style.transform='translateY(18px)';s.style.transition='opacity .7s cubic-bezier(.165,.84,.44,1),transform .7s cubic-bezier(.165,.84,.44,1)';s.style.transitionDelay=(250+i*28)+'ms';
  facBody.appendChild(s);
});
const facIo=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){facBody.querySelectorAll('span').forEach(el=>{el.style.opacity='1';el.style.transform='translateY(0)'});facIo.unobserve(e.target)}}),{threshold:.2});
facIo.observe(facBody);
const stats=[
  {v:'5',l:'Keputusan tercatat',n:5,f:v=>Math.floor(v)},
  {v:'70',l:'Snapshot diranking',n:70,f:v=>Math.floor(v)},
  {v:'3',l:'Posisi tertutup',n:3,f:v=>Math.floor(v)},
  {v:'0',l:'Jurnal belum ditulis',n:0,f:v=>Math.floor(v)}
];
const statsGrid=document.getElementById('statsGrid');
stats.forEach((s,i)=>{
  const el=document.createElement('div');el.className='stat inview';el.dataset.delay=i*110;
  el.innerHTML='<dt class="sr-only">'+esc(s.l)+'</dt><dd><div class="stat-val" data-n="'+s.n+'">'+esc(s.v)+'</div><div class="stat-label">'+esc(s.l)+'</div></dd>';
  statsGrid.appendChild(el);io.observe(el);
});
const tests=[
  {q:'Snapshot is actionable (BUY, fresh data) but no risk parameters were supplied — entry/stop/target never invented.',name:'Brief #1 · ANTM',role:'POLICY_BLOCKED'},
  {q:'3170 → 3106,6 → 3296,8 rasio 2,0 — plan lengkap, tinggal eksekusi manual di broker.',name:'Brief #2 · ANTM',role:'SUCCESS'},
  {q:'0 journal entries — 3 posisi closed (BBCA×2, TLKM) menunggu catatan refleksi.',name:'Journal · kosong',role:'Belum ditulis'},
];
const testGrid=document.getElementById('testGrid');
tests.forEach((t,i)=>{
  const li=document.createElement('li');li.className='test-card inview';li.dataset.delay=i*120;
  const av=[I1,I3,I4][i%3]; li.innerHTML='<div><div style="display:flex;gap:.75rem;align-items:center"><img src="'+av+'" alt="" loading="lazy" style="width:2.25rem;height:2.25rem;border-radius:9999px;object-fit:cover;flex-shrink:0;border:1px solid #e6e8ec"><div class="test-quote">"</div></div><blockquote class="test-block">'+esc(t.q)+'</blockquote></div><figcaption class="test-foot"><div style="font-weight:500">'+esc(t.name)+'</div><div class="test-role">'+esc(t.role)+'</div></figcaption>';
  testGrid.appendChild(li);io.observe(li);
});
document.querySelectorAll('a[href^="#"]').forEach(a=>{
  a.addEventListener('click',e=>{
    const id=a.getAttribute('href').slice(1);
    const target=document.getElementById(id);
    if(target){e.preventDefault();const top=target.getBoundingClientRect().top+scrollY;scrollTo({top,behavior:'smooth'});closeMenu()}
  });
});
const menu=document.getElementById('menu');
function openMenu(){menu.classList.add('open');menu.setAttribute('aria-hidden','false');menu.removeAttribute('inert');lock()}
function closeMenu(){menu.classList.remove('open');menu.setAttribute('aria-hidden','true');menu.setAttribute('inert','');unlock()}
document.getElementById('burger').addEventListener('click',openMenu);
document.getElementById('menuClose').addEventListener('click',closeMenu);
document.getElementById('menuBackdrop').addEventListener('click',closeMenu);
document.getElementById('menuBook').addEventListener('click',()=>{closeMenu();openModal()});
menu.querySelectorAll('a').forEach(a=>a.addEventListener('click',closeMenu));
const modal=document.getElementById('modal'),form=document.getElementById('contactForm'),successPanel=document.getElementById('successPanel'),successText=document.getElementById('successText');
function openModal(){modal.classList.add('open');modal.setAttribute('aria-hidden','false');modal.removeAttribute('inert');lock();setTimeout(()=>document.getElementById('f-name').focus(),120)}
function closeModal(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true');modal.setAttribute('inert','');unlock();setTimeout(()=>{form.reset();form.style.display='';successPanel.style.display='none';document.getElementById('modalSubmit').textContent='Aktifkan notifikasi';document.getElementById('modalSubmit').disabled=false},350)}
window.openModal=openModal;window.closeMenu=closeMenu;
document.getElementById('bookHeader').addEventListener('click',openModal);
document.getElementById('footerCta').addEventListener('click',openModal);
document.getElementById('modalClose').addEventListener('click',closeModal);
document.getElementById('modalBackdrop').addEventListener('click',closeModal);
document.getElementById('successDone').addEventListener('click',closeModal);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(modal.classList.contains('open')) closeModal();if(menu.classList.contains('open')) closeMenu()}});
form.addEventListener('submit',e=>{
  e.preventDefault();
  const btn=document.getElementById('modalSubmit');btn.textContent='Mengaktifkan…';btn.disabled=true;
  const name=document.getElementById('f-name').value.trim().split(' ')[0]||'Trader';
  setTimeout(()=>{form.style.display='none';successPanel.style.display='block';successText.textContent='Sip, '+name+' — AIOS bakal kirim notifikasi kalau ada perubahan penting.'},600);
});
// ── threeui polish ──
// 1) Aurora hero — WebGL from shaders/aurora.html, no controls, respects reduced-motion
(function(){
  const canvas=document.getElementById('auroraHero'); if(!canvas) return;
  const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
  const gl=canvas.getContext('webgl',{antialias:true});
  if(!gl){canvas.style.display='none'; return;}
  const vert=`attribute vec2 position; void main(){ gl_Position=vec4(position,0.,1.); }`;
  const frag=`precision mediump float; uniform float u_time; uniform vec2 u_resolution; uniform float u_speed; uniform float u_intensity;
  float hash(vec2 p){ return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }
  float noise(vec2 p){ vec2 i=floor(p),f=fract(p); f=f*f*(3.-2.*f); float a=hash(i),b=hash(i+vec2(1.,0.)),c=hash(i+vec2(0.,1.)),d=hash(i+vec2(1.,1.)); return mix(mix(a,b,f.x),mix(c,d,f.x),f.y); }
  void main(){ vec2 uv=(gl_FragCoord.xy - .5*u_resolution)/u_resolution.y; uv.x*=1.1; float t=u_time*u_speed*.5; vec3 col=vec3(0.02,0.04,0.12);
    float stars=pow(hash(floor(uv*420.)),18.)*1.4; col+=stars;
    for(float i=0.; i<3.; i++){ float fi=i/3.; float y=-0.1+fi*0.55+sin(uv.x*1.2+t*0.4+fi*3.1)*0.22+cos(uv.x*2.8-t*0.3)*0.07; float d=abs(uv.y-y);
      float band=exp(-d*(8.+fi*6.))*(0.9-fi*0.25); float wave=noise(vec2(uv.x*3.+t*0.7,fi*5.))*0.5+0.5; band*=0.7+0.3*wave;
      vec3 c1=vec3(0.10,0.95,0.55), c2=vec3(0.20,0.55,1.0), c3=vec3(0.75,0.35,0.95); vec3 bandCol=mix(mix(c1,c2,fi),c3,pow(fi,2.)*0.5); col+=bandCol*band*u_intensity*1.15;
      float glow=exp(-d*2.2)*0.12; col+=bandCol*glow*u_intensity*0.32; }
    float haze=smoothstep(0.35,-0.55,uv.y)*0.15; col+=vec3(0.05,0.12,0.18)*haze; float vig=1.-dot(uv,uv)*0.35; col*=vig;
    gl_FragColor=vec4(pow(col,vec3(0.95)),1.); }`;
  function compile(type,src){const s=gl.createShader(type); gl.shaderSource(s,src); gl.compileShader(s); if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s;}
  const vs=compile(gl.VERTEX_SHADER,vert), fs=compile(gl.FRAGMENT_SHADER,frag);
  const prog=gl.createProgram(); gl.attachShader(prog,vs); gl.attachShader(prog,fs); gl.linkProgram(prog); gl.useProgram(prog);
  const buf=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,buf); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  const loc=gl.getAttribLocation(prog,'position'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
  const u_time=gl.getUniformLocation(prog,'u_time'), u_res=gl.getUniformLocation(prog,'u_resolution'), u_speed=gl.getUniformLocation(prog,'u_speed'), u_int=gl.getUniformLocation(prog,'u_intensity');
  let speed=reduce?0:0.7, intensity=reduce?0.55:0.95;
  function resize(){const isMobile=innerWidth<768; const dpr=Math.min(devicePixelRatio,isMobile?1:1.5); const rect=canvas.getBoundingClientRect(); canvas.width=Math.floor(rect.width*dpr); canvas.height=Math.floor(rect.height*dpr); gl.viewport(0,0,canvas.width,canvas.height); gl.uniform2f(u_res,canvas.width,canvas.height);}
  addEventListener('resize',resize); resize(); gl.uniform1f(u_speed,speed); gl.uniform1f(u_int,intensity);
  let t0=performance.now();
  let last=0, raf=0, visible=true;
  const io=new IntersectionObserver(es=>{ visible=es[0].isIntersecting; if(visible&&!raf) loop(); },{threshold:0});
  io.observe(canvas);
  function loop(now){ raf=requestAnimationFrame(loop); if(!visible) return; if(now-last < 33) return; last=now; const elapsed=(now-t0)/1000; gl.uniform1f(u_time,elapsed); gl.drawArrays(gl.TRIANGLE_STRIP,0,4); }
  loop();
})();
// 2) Constellation trust — 24 AIOS labels (10 ticker + 6 konsep + 8 status), rotasi 4 label per bola
(function(){
  const cv=document.getElementById('constellationTrust'); if(!cv) return;
  if(matchMedia('(prefers-reduced-motion:reduce)').matches){
    const ctx=cv.getContext('2d'); const rect=cv.getBoundingClientRect(); cv.width=rect.width; cv.height=rect.height;
    ctx.fillStyle='rgba(15,47,99,.06)'; ctx.fillRect(0,0,rect.width,rect.height);
    ctx.fillStyle='#0f2f63'; ctx.font='12px Onest'; ctx.fillText('ANTM — AIOS constellation (reduced-motion)', 16, 24);
    cv.dataset.labels='ANTM,AUTO,BBCA,BBRI,BMRI,BRIS,BBNI,BBTN,AKRA,ASII,SCAN,RANK,BRIEF,GATE,WINDOW,AUDIT,MEDIUM,BUY,SUCCESS,BLOCKED,ACTIVE,HOLD,WATCH,READY';
    return;
  }
  const ctx=cv.getContext('2d');
  const LABELS=['ANTM','AUTO','BBCA','BBRI','BMRI','BRIS','BBNI','BBTN','AKRA','ASII','SCAN','RANK','BRIEF','GATE','WINDOW','AUDIT','MEDIUM','BUY','SUCCESS','BLOCKED','ACTIVE','HOLD','WATCH','READY'];
  const GROUPS=[['ANTM','AUTO','BBCA','BBRI'],['BMRI','BRIS','BBNI','BBTN'],['AKRA','ASII','SCAN','RANK'],['BRIEF','GATE','WINDOW','AUDIT'],['MEDIUM','BUY','SUCCESS','BLOCKED'],['ACTIVE','HOLD','WATCH','READY']];
  const N=LABELS.length;
  cv.dataset.labels=LABELS.join(',');
  let W=0,H=0,DPR=Math.min(devicePixelRatio,innerWidth<768?1:1.5);
  let pts=[];
  function rs(){ const rect=cv.getBoundingClientRect(); W=rect.width; H=rect.height; cv.width=W*DPR; cv.height=H*DPR; ctx.setTransform(DPR,0,0,DPR,0,0); if(!pts.length) pts=[...Array(N)].map((_,i)=>({x:26+Math.random()*(W-52),y:26+Math.random()*(H-52),vx:(Math.random()-.5)*0.11,vy:(Math.random()-.5)*0.11,r:20+Math.random()*7,gi:i%GROUPS.length})); }
  addEventListener('resize',rs); rs();
  let last2=0, visible2=true;
  const io2=new IntersectionObserver(es=> visible2=es[0].isIntersecting,{threshold:0}); io2.observe(cv);
  function draw(now){
    requestAnimationFrame(draw); if(!visible2) return; if(now-last2 < 42) return; last2=now;
    ctx.clearRect(0,0,W,H);
    const liBase=Math.floor(now/2200)%4;
    pts.forEach(p=>{ p.x+=p.vx; p.y+=p.vy; if(p.x<24||p.x>W-24) p.vx*=-1; if(p.y<24||p.y>H-24) p.vy*=-1; p.x=Math.max(24,Math.min(W-24,p.x)); p.y=Math.max(24,Math.min(H-24,p.y)); });
    for(let i=0;i<N;i++){
      const dists=[];
      for(let j=0;j<N;j++){ if(i===j) continue; const dx=pts[i].x-pts[j].x, dy=pts[i].y-pts[j].y; dists.push([Math.hypot(dx,dy),j]); }
      dists.sort((a,b)=>a[0]-b[0]);
      for(let k=0;k<2;k++){ const [d,j]=dists[k]; if(d<150){ const a=(1-d/150)*0.22; ctx.strokeStyle='rgba(15,47,99,'+a+')'; ctx.lineWidth=.7; ctx.beginPath(); ctx.moveTo(pts[i].x,pts[i].y); ctx.lineTo(pts[j].x,pts[j].y); ctx.stroke(); } }
    }
    pts.forEach((p)=>{
      const label=GROUPS[p.gi][(liBase+p.gi)%4];
      ctx.save();
      ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
      const grd=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,p.r);
      grd.addColorStop(0,'rgba(255,255,255,.92)'); grd.addColorStop(0.6,'rgba(255,244,200,.85)'); grd.addColorStop(1,'rgba(255,179,71,.22)');
      ctx.fillStyle=grd; ctx.fill(); ctx.strokeStyle='rgba(15,47,99,.18)'; ctx.lineWidth=1; ctx.stroke(); ctx.clip();
      ctx.fillStyle='#0f2f63'; ctx.font='600 '+(p.r*0.42)+'px Onest, system-ui, sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(label, p.x, p.y+0.5);
      ctx.restore();
    });
  }
  draw(performance.now());
})();

// 3) Border beam — magic/border-beam-01.html conic-gradient on cards
(function(){
  if(matchMedia('(prefers-reduced-motion:reduce)').matches) return;
  const cards=document.querySelectorAll('.trust-card,.test-card');
  cards.forEach(el=>{
    const beam=document.createElement('div'); beam.className='border-beam'; beam.setAttribute('aria-hidden','true'); el.appendChild(beam);
  });
  let a=0; function frame(){ a+=0.45; document.querySelectorAll('.border-beam').forEach(b=> b.style.setProperty('--a',a+'deg')); requestAnimationFrame(frame); } frame();
})();
if(reduceMotion){
  document.querySelectorAll('.inview').forEach(el=>el.classList.add('show'));
  document.querySelectorAll('.clip span').forEach(s=>{s.style.transform='translateY(0)';s.style.opacity='1'});
  facBody.querySelectorAll('span').forEach(s=>{s.style.opacity='1';s.style.transform='translateY(0)'});
}

// ══════════ threeui polish — round 2 ══════════
// shared: pause any rAF loop when off-screen (battery + jank guard)
function whenVisible(el,fn){ const io=new IntersectionObserver(e=>{fn(e[0].isIntersecting);},{threshold:0}); io.observe(el); return io; }

// 1) Meteors — magic/meteors-01.html, adapted for hero (white/brand streaks)
(function(){
  const c=document.getElementById('meteorHero'); if(!c) return;
  const ctx=c.getContext('2d'); if(!ctx) return;
  let W=0,H=0,dpr=1,meteors=[],vis=true;
  function rs(){
    dpr=Math.min(devicePixelRatio||1,1.5);
    W=c.width=Math.max(1,Math.floor(c.clientWidth*dpr));
    H=c.height=Math.max(1,Math.floor(c.clientHeight*dpr));
  }
  function spawn(){
    meteors.push({x:Math.random()*W+200*dpr, y:Math.random()*-200*dpr,
      vx:-(2.4+Math.random()*3.4)*dpr, vy:(1.1+Math.random()*1.2)*dpr,
      len:(70+Math.random()*110)*dpr, life:1});
  }
  rs(); addEventListener('resize',rs);
  whenVisible(c,v=>{vis=v;});
  function draw(){
    if(!reduceMotion) requestAnimationFrame(draw);
    if(!vis) return;
    ctx.clearRect(0,0,W,H);
    for(let i=0;i<meteors.length;i++){
      const m=meteors[i];
      m.x+=m.vx; m.y+=m.vy; m.life-=0.0035;
      const g=ctx.createLinearGradient(m.x,m.y,m.x+m.len,m.y-m.len*0.5);
      g.addColorStop(0,'rgba(255,255,255,0)');
      g.addColorStop(0.5,'rgba(87,144,230,.55)');
      g.addColorStop(1,'rgba(255,255,255,.85)');
      ctx.strokeStyle=g; ctx.lineWidth=1.4*dpr;
      ctx.beginPath(); ctx.moveTo(m.x,m.y); ctx.lineTo(m.x+m.len,m.y-m.len*0.5); ctx.stroke();
      ctx.fillStyle='rgba(255,255,255,.85)';
      ctx.beginPath(); ctx.arc(m.x,m.y,1.5*dpr,0,Math.PI*2); ctx.fill();
    }
    meteors=meteors.filter(m=>m.y<H+120*dpr && m.x>-420*dpr && m.life>0);
    if(meteors.length<5 && Math.random()<0.035) spawn();
  }
  if(reduceMotion){
    // static streaks placed inside the viewport (no motion, still visible)
    for(let i=0;i<4;i++){
      meteors.push({x:(0.15+Math.random()*0.75)*W, y:(0.08+Math.random()*0.5)*H,
        vx:0, vy:0, len:(70+Math.random()*110)*dpr, life:1});
    }
    draw();
    return;
  }
  for(let i=0;i<5;i++) spawn();
  draw();
})();

// 2) Dot pattern — magic/dot-pattern-01.html, pointer-reactive on #facilities
(function(){
  const c=document.getElementById('facDots'); if(!c) return;
  const ctx=c.getContext('2d'); if(!ctx) return;
  const sec=document.getElementById('facilities');
  let mx=-9999,my=-9999,W=0,H=0,dpr=1,vis=true;
  function rs(){
    dpr=Math.min(devicePixelRatio||1,1.5);
    W=c.width=Math.max(1,Math.floor(c.clientWidth*dpr));
    H=c.height=Math.max(1,Math.floor(c.clientHeight*dpr));
  }
  rs(); addEventListener('resize',rs);
  whenVisible(c,v=>{vis=v;});
  if(!reduceMotion){
    sec.addEventListener('pointermove',e=>{
      const r=c.getBoundingClientRect();
      mx=(e.clientX-r.left)*dpr; my=(e.clientY-r.top)*dpr;
    });
    sec.addEventListener('pointerleave',()=>{mx=-9999;my=-9999;});
  }
  function draw(){
    if(!reduceMotion) requestAnimationFrame(draw);
    if(!vis) return;
    ctx.clearRect(0,0,W,H);
    const gap=17*dpr, rad=1.3*dpr;
    for(let y=gap;y<H;y+=gap) for(let x=gap;x<W;x+=gap){
      const d=Math.hypot(x-mx,y-my);
      const a=Math.max(0.05,Math.min(0.30,0.30-d/900));
      ctx.fillStyle='rgba(37,99,201,'+a.toFixed(3)+')';
      ctx.beginPath(); ctx.arc(x,y,rad,0,Math.PI*2); ctx.fill();
    }
  }
  if(reduceMotion){ draw(); return; }
  draw();
})();

// 3) Orbiting circles — magic/orbiting-circles-01.html, 5 tags around coach figure
(function(){
  const wrap=document.getElementById('orbitWrap'); if(!wrap) return;
  const tags=['70','5','3','38','24/7'];
  const R=[128,182,232], S=[30,34,30], DUR=[22000,30000,38000];
  tags.forEach((t,i)=>{
    const el=document.createElement('span');
    el.className='orbit-node'; el.textContent=t;
    const s=S[i%S.length], r=R[i%R.length];
    el.style.cssText+='width:'+s+'px;height:'+s+'px;margin:-'+(s/2)+'px;';
    wrap.appendChild(el);
    if(reduceMotion) return;
    const off=(i/tags.length)*360, dur=DUR[i%DUR.length];
    el.animate([
      {transform:'rotate('+off+'deg) translateX('+r+'px) rotate(-'+off+'deg)'},
      {transform:'rotate('+(off+360)+'deg) translateX('+r+'px) rotate(-'+(off+360)+'deg)'}
    ],{duration:dur,iterations:Infinity,easing:'linear',direction:i%2?'reverse':'normal'});
  });
})();

// 4) Spotlight glare — magic/magic-card-01.html, follows pointer over hero
(function(){
  const heroEl=document.getElementById('hero'), glare=document.getElementById('heroGlare');
  if(!heroEl||!glare) return;
  heroEl.addEventListener('pointermove',e=>{
    const r=heroEl.getBoundingClientRect();
    const x=e.clientX-r.left, y=e.clientY-r.top;
    glare.style.opacity='1';
    glare.style.background='radial-gradient(420px 300px at '+x+'px '+y+'px, rgba(255,179,71,.13), transparent 62%)';
  });
  heroEl.addEventListener('pointerleave',()=>glare.style.opacity='0');
})();

// 5) Shimmer buttons — magic/shimmer-button-01.html
(function(){
  if(reduceMotion) return;
  const glares=document.querySelectorAll('.shimmer-glare');
  glares.forEach(g=>{
    const host=g.parentElement;
    let x=-60, vis=true;
    whenVisible(host,v=>{vis=v;});
    (function loop(){
      requestAnimationFrame(loop);
      if(!vis) return;
      x+=0.55; if(x>170) x=-60;
      g.style.transform='translateX('+x+'%)';
    })();
  });
})();

// 6) Number ticker — magic/number-ticker-01.html on .stat-val
(function(){
  const vals=[...document.querySelectorAll('.stat-val[data-n]')];
  if(!vals.length) return;
  function tick(el){
    const target=parseFloat(el.dataset.n)||0;
    if(reduceMotion){ el.textContent=String(target); return; }
    const dur=1400; let start=0;
    function f(now){
      if(!start) start=now;
      const p=Math.min(1,(now-start)/dur), e=1-Math.pow(1-p,3);
      el.textContent=Math.floor(target*e);
      if(p<1) requestAnimationFrame(f); else el.textContent=String(target);
    }
    requestAnimationFrame(f);
  }
  const io=new IntersectionObserver(es=>es.forEach(e=>{
    if(e.isIntersecting){ tick(e.target); io.unobserve(e.target); }
  }),{threshold:.5});
  vals.forEach(v=>io.observe(v));
})();

// 7) Ripple — magic/ripple-01.html on trust prev/next arrows
(function(){
  const btns=[document.getElementById('trustPrev'),document.getElementById('trustNext')].filter(Boolean);
  btns.forEach(btn=>{
    btn.addEventListener('click',e=>{
      const d=document.createElement('span'); d.className='ripple';
      const r=btn.getBoundingClientRect();
      d.style.left=(e.clientX-r.left)+'px';
      d.style.top=(e.clientY-r.top)+'px';
      btn.appendChild(d);
      d.animate([{transform:'translate(-50%,-50%) scale(.2)',opacity:.9},
                 {transform:'translate(-50%,-50%) scale(2.6)',opacity:0}],
                {duration:620,easing:'cubic-bezier(.16,1,.3,1)'}).onfinish=()=>d.remove();
    });
  });
})();

// 8) Progress meters — programs (gauge-01-radial-progress.html motion language)
(function(){
  const bars=[...document.querySelectorAll('.prog-meter i')];
  if(!bars.length) return;
  const set=b=>b.style.width=b.dataset.w+'%';
  if(reduceMotion){ bars.forEach(set); return; }
  const io=new IntersectionObserver(es=>es.forEach(e=>{
    if(e.isIntersecting){ set(e.target); io.unobserve(e.target); }
  }),{threshold:.4});
  bars.forEach(b=>io.observe(b));
})();

// 9) Word rotate — magic/word-rotate-01.html on hero tagline second line
(function(){
  const host=document.querySelector('#hero-tagline .clip:nth-of-type(2) span');
  if(!host) return;
  if(reduceMotion) return;
  const words=['Bukan Tebak','Bukan Sinyal','Bukan Janji'];
  let i=0, timer=null;
  const rot=document.createElement('span');
  rot.className='word-rot'; rot.textContent=host.textContent;
  host.textContent=''; host.appendChild(rot);
  function step(){
    rot.style.transition='transform .3s cubic-bezier(.16,1,.3,1),opacity .3s';
    rot.style.transform='translateY(-9px)'; rot.style.opacity='0';
    setTimeout(()=>{
      rot.textContent=words[i]; i=(i+1)%words.length;
      rot.style.transition='transform .45s cubic-bezier(.16,1,.3,1),opacity .45s';
      rot.style.transform='translateY(9px)';
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        rot.style.transform='translateY(0)'; rot.style.opacity='1';
      }));
    },300);
  }
  function start(){ if(!timer) timer=setInterval(step,3400); }
  const io=new IntersectionObserver(e=>{
    if(e[0].isIntersecting) start(); else { clearInterval(timer); timer=null; }
  },{threshold:0});
  io.observe(document.getElementById('hero'));
})();

// 10) Animated list — magic/animated-list-01.html + blur-fade-01.html stagger on stats
(function(){
  const items=[...document.querySelectorAll('#statsGrid .stat')];
  if(!items.length||reduceMotion) return;
  items.forEach((el,i)=>{
    el.style.filter='blur(6px)';
    el.style.transitionDelay=(i*90)+'ms';
  });
  const io=new IntersectionObserver(es=>es.forEach(e=>{
    if(e.isIntersecting){
      e.target.style.filter='blur(0)';
      setTimeout(()=>e.target.style.transitionDelay='0ms',900);
      io.unobserve(e.target);
    }
  }),{threshold:.15});
  items.forEach(el=>io.observe(el));
})();

// skip-link (moved from inline classic script — Blazor doesn't execute rendered <script> tags)
try {
  const s = document.querySelector('a.skip'), mm = document.getElementById('main');
  if (s && mm) s.addEventListener('click', function() { try { mm.focus({preventScroll:true}); } catch(_) { mm.focus(); } });
} catch {}

console.log('Atrium initialized (Lenis + full motion suite)');
}
