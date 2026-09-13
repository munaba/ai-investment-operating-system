// Atlas — wireframe sphere constellation + 70 points filter
export function initAtlas() {
if (window.__atlasInit) return; window.__atlasInit = true;


// clock
function tick(){const el=document.getElementById('clock');if(!el)return;const d=new Date();el.textContent=d.toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'})+' · '+d.toLocaleDateString('id-ID',{day:'numeric',month:'short'})}tick();setInterval(tick,30000);
// mobile nav
const mnav=document.getElementById('mnav');
const burger=document.getElementById('burger');
function setNav(open){mnav.classList.toggle('open',open);if(open){mnav.removeAttribute('inert')}else{mnav.setAttribute('inert','')};mnav.setAttribute('aria-hidden',String(!open));burger.setAttribute('aria-expanded',String(open));burger.setAttribute('aria-label',open?'Close menu':'Open menu')}
const openBtn=document.getElementById('openNav');
if(openBtn) openBtn.onclick=()=>setNav(true);
burger.onclick=()=>setNav(true);
document.getElementById('closeNav').onclick=()=>setNav(false);
mnav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>setNav(false)));
// scroll nav
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>document.getElementById(b.dataset.go).scrollIntoView({behavior:'smooth'})));
document.querySelectorAll('a[href^="#"]').forEach(a=>a.addEventListener('click',e=>{const id=a.getAttribute('href').slice(1);const el=document.getElementById(id);if(el){e.preventDefault();el.scrollIntoView({behavior:'smooth'})}}));
/* M-07: data di file ini literal const (bukan URL/API). esc() kunci sink bila sumber berubah; tanpa ubah visual. */
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
// towers 11
const towers=[
{n:'Jepang',icon:'⛩️',sub:'Pagoda',desc:'Ketenangan yang presisi. Teh pagi, kayu, dan jeda.',tags:['Kyoto','Minimal']},
{n:'Italia',icon:'🏛️',sub:'Colosseo',desc:'Bentuk yang bertahan. Batu, proporsi, dan makan siang panjang.',tags:['Roma','Bentuk']},
{n:'Amerika Serikat',icon:'🗽',sub:'Menara Kaca',desc:'Skala yang melatih mimpi - dan mengingatkan batas.',tags:['New York','Skala']},
{n:'Perancis',icon:'🗼',sub:'Besi & Cahaya',desc:'Gagasan yang diberi cahaya. Jalan kaki dan catatan.',tags:['Paris','Gagasan']},
{n:'Brasil',icon:'⛰️',sub:'Bukit Warna',desc:'Irama yang menggerakkan kaki sebelum kepala.',tags:['Rio','Irama']},
{n:'Mesir',icon:'🔺',sub:'Piramida',desc:'Waktu yang dipadatkan jadi batu. Sabar dan jejak.',tags:['Kairo','Waktu']},
{n:'Kamboja',icon:'🛕',sub:'Angkor',desc:'Akar yang memeluk candi. Alam yang merebut kembali.',tags:['Siem Reap','Akar']},
{n:'Tiongkok',icon:'🏯',sub:'Kota Terlarang',desc:'Lapisan sejarah dan halaman yang luas.',tags:['Beijing','Lapisan']},
{n:'Thailand',icon:'🙏',sub:'Chedi Emas',desc:'Rasa, jalan, dan senyum yang menenangkan.',tags:['Bangkok','Rasa']},
{n:'Turki',icon:'🕌',sub:'Kubah',desc:'Persimpangan benua - kopi, doa, dan selat.',tags:['Istanbul','Ambang']},
{n:'Vietnam',icon:'🏮',sub:'Lentera',desc:'Ketekunan yang lentur. Sepeda, sungai, dan lentera.',tags:['Hoi An','Tekun']}
];
var wireCanvases=[];
const tWrap=document.getElementById('towers');
const TINTS=['#cf8047','#6aa7ff','#4ade80'];
towers.forEach((t,i)=>{
  const el=document.createElement('article');el.className='tower rv';
  el.style.transitionDelay=(i%3*0.07)+'s';
  const tint=TINTS[i%3];
  el.innerHTML=`<div class="tower-top"><canvas width="300" height="120" aria-hidden="true"></canvas><span class="tower-spin"><i style="background:${tint}"></i></span><span>${esc(t.icon)}</span><b>${esc(t.sub)}</b></div><div class="tower-body"><h3>${esc(t.n)}</h3><p>${esc(t.desc)}</p><div class="tower-meta"><s>${esc(t.tags[0])}</s><s>${esc(t.tags[1])}</s></div></div>`;
  tWrap.appendChild(el);
  wireSphere(el.querySelector('.tower-top canvas'),tint);
});
// wireframe-forms/sphere - bola kawat berputar pelan di tiap menara
function wireSphere(cv,tint){
  const ctx=cv.getContext('2d');
  const R=cv.height*0.42, cx=cv.width/2, cy=cv.height/2;
  const nodes=[];const rings=6,seg=14;
  for(let r=0;r<rings;r++)for(let s=0;s<seg;s++){
    const phi=(r+1)*Math.PI/(rings+1), th=s*2*Math.PI/seg;
    nodes.push([Math.sin(phi)*Math.cos(th),Math.cos(phi),Math.sin(phi)*Math.sin(th)]);
  }
  wireCanvases.push({cv,ctx,nodes,R,cx,cy,tint,a:0,deep:rings*seg});
}
let lastWire=0;let wireVisible=true;try{new IntersectionObserver(es=>wireVisible=es[0].isIntersecting,{threshold:0}).observe(document.getElementById('towers'))}catch(e){}
function wireDraw(now){ if(!wireVisible){requestAnimationFrame(wireDraw);return} if(now&&now-lastWire<33){requestAnimationFrame(wireDraw);return} if(now)lastWire=now;
  wireCanvases.forEach(w=>{
    const {cv,ctx,nodes,R,cx,cy,tint}=w;
    w.a+=0.006;
    ctx.clearRect(0,0,cv.width,cv.height);
    const ca=Math.cos(w.a),sa=Math.sin(w.a);
    const p=nodes.map(([x,y,z])=>[x*ca-z*sa,y,x*sa+z*ca]);
    ctx.strokeStyle=tint;ctx.lineWidth=1;ctx.globalAlpha=.5;
    for(let r=0;r<6;r++)for(let s=0;s<14;s++){
      const i=r*14+s, j=r*14+(s+1)%14;
      const A=p[i],B=p[j];
      if(A[2]+B[2]>-0.2){
        ctx.globalAlpha=.18+0.4*(A[2]+1)/2;
        ctx.beginPath();ctx.moveTo(cx+A[0]*R,cy+A[1]*R);ctx.lineTo(cx+B[0]*R,cy+B[1]*R);ctx.stroke();
      }
      if(r<5){const C=p[(r+1)*14+s];ctx.globalAlpha=.12;ctx.beginPath();ctx.moveTo(cx+A[0]*R,cy+A[1]*R);ctx.lineTo(cx+C[0]*R,cy+C[1]*R);ctx.stroke();}
    }
    ctx.globalAlpha=1;
  });
  requestAnimationFrame(wireDraw);
}
if(wireCanvases.length) wireDraw();
// 70 points
const tempat=[
'Jakarta - Gang rumah & warung kopi','Bandung - Kabut Dago & vinyl','Yogyakarta - Angkringan & pameran','Bali - Sawah Seseh & ombak','Lombok - Bukit Merese & sepi','Labuan Bajo - Kapal & senja','Makassar - Pelabuhan & coto','Medan - Kesawan & durian','Semarang - Kota Lama & lumpia','Surabaya - Pasar Atom & hujan','Malang - Apel & jalan pagi','Solo - Batik & wedangan','Bogor - Kebun Raya & hujan','Singapore - Hawker & transit','Kyoto - Kuil & sepeda','Tokyo - Shibuya & ramen','Seoul - Hongdae & hanok','Bangkok - Chatuchak & khao soi','Hoi An - Lentera & sungai','Istanbul - Grand Bazaar & selat','Paris - Canal & buku bekas','Roma - Trastevere & piazza','Kairo - Khan & Nil','Rio - Lapa & pantai','New York - Subway & deli'
];
const ide=[
'Arsip Hidup - simpan yang ingin diingat','Ritual Pagi - 30 menit tanpa layar','Jalan Pelan - 7.000 langkah tanpa target','Kota 15 Menit - semua dalam jangkau kaki','Meja Kosong - satu permukaan selalu kosong','Surat Masa Depan - tulis untuk diri 1 tahun lagi','Makan Bersama - masak & bagi','Membaca Ulang - satu buku, tiga kali','Foto Satu Rol - 36 jepret per musim','Catatan Tangan - bukan app','Menanam - satu pot, satu musim','Memperbaiki - jahit, amplas, lem','Diam - 10 menit tanpa musik','Puasa Kabar - sehari tanpa berita','Berbagi Alat - pinjam, bukan beli','Peta Tangan - gambar peta dari ingatan','Koleksi Kecil - koin, karcis, daun','Ulang Tahun Ide - rayakan 1 ide setahun','Tidur Cukup - 7,5 jam','Berjalan Tanpa Tujuan - lost walk'
];
const orang=[
'Ibu - kompas pertama','Ayah - diam yang menjaga','Adik - tawa yang jujur','Nenek - cerita yang berulang','Kawan Studio - debat sampai larut','Guru Jalan - yang menegur pelan','Tetangga Warung - sapa tiap pagi','Penjaga Kos - kunci & nasi goreng','Barista - hafal pesanan','Tukang Jahit - presisi & sabar','Sopir Angkot - rute & cerita','Anak Pasar - tawar & canda','Perawat Puskesmas - sigap & lembut','Petani Seseh - padi & hujan','Nelayan Bajo - angin & jaring','Seniman Jogja - cat & debu','Penulis Blok M - kopi & naskah','Fotografer Pasar - klik & tunggu','Koki Hawker - wajan & api','Mahasiswa Rantau - kos & mimpi','Relawan Banjir - perahu & kardus','Kakek Becak - pelan & pasti','Guru TK - lagu & peluk','Teman Sepeda - kayuh & diam','Diri Sendiri 10 Tahun Lalu - surat yang belum dibalas'
];
const pointsEl=document.getElementById('points');
function addPoints(list,cat){
  list.forEach((txt,i)=>{
    const [title,note]=txt.split(' - ');
    const d=document.createElement('div');d.className='point';d.dataset.cat=cat;
    d.innerHTML=`<b>${String(i+1).padStart(2,'0')}</b><p><strong class="pt-anim">${[...title].map((ch,k)=>`<span style="animation-delay:${k*0.05}s">${ch===' '?'&nbsp;':esc(ch)}</span>`).join('')}</strong> - ${esc(note||'')}<em>${esc(cat)} · #${String(i+1).padStart(2,'0')}</em></p>`;
    pointsEl.appendChild(d);
  });
}
addPoints(tempat,'tempat');addPoints(ide,'ide');addPoints(orang,'orang');
// filter
document.querySelectorAll('.filter').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.filter').forEach(b=>b.classList.remove('on'));btn.classList.add('on');
    const f=btn.dataset.f;
    document.querySelectorAll('.point').forEach(p=>{
      p.classList.toggle('hidden', f!=='all' && p.dataset.cat!==f);
    });
  });
});
// constellation 42 nodes
const cv=document.getElementById('atlasCanvas'),ctx=cv.getContext('2d');
let W=0,H=0,DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2),hover=-1,pulses=[],mx=0,my=0,drag=false,offX=0,offY=0;
const N=42;
const cats=['tempat','ide','orang'];
const colors={tempat:'#cf8047',ide:'#6aa7ff',orang:'#4ade80'};
let pts=[];
function initPts(){
  pts=[...Array(N)].map((_,i)=>({
    x:Math.random()*W,y:Math.random()*H,
    vx:(Math.random()-.5)*.4,vy:(Math.random()-.5)*.4,
    r:1.6+Math.random()*1.8,
    cat:cats[i%3],
    label:(i%3===0?tempat[i%tempat.length] : i%3===1?ide[i%ide.length] : orang[i%orang.length]).split(' - ')[0]
  }));
}
function resize(){ DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2);
  const r=cv.getBoundingClientRect();W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);
  if(!pts.length) initPts();
}
addEventListener('resize',resize);resize();
cv.addEventListener('pointermove',e=>{
  const r=cv.getBoundingClientRect();mx=e.clientX-r.left;my=e.clientY-r.top;
  if(drag){pts.forEach(p=>{p.x+=e.movementX;p.y+=e.movementY});return}
  hover=-1;let best=900;
  pts.forEach((p,i)=>{const d=(p.x-mx)**2+(p.y-my)**2;if(d<best){best=d;hover=i}});
  document.getElementById('hoverLabel').textContent=hover>=0?pts[hover].label+' · '+pts[hover].cat:'-';
});
cv.addEventListener('pointerdown',e=>{drag=true;cv.setPointerCapture(e.pointerId)});
addEventListener('pointerup',()=>drag=false);
cv.addEventListener('click',e=>{
  const r=cv.getBoundingClientRect();pulses.push({x:e.clientX-r.left,y:e.clientY-r.top,r:0,max:140});
});
document.getElementById('btnShuffle').onclick=()=>initPts();
document.getElementById('btnFocus').onclick=()=>pts.forEach(p=>{p.vx+=(W/2-p.x)*0.002;p.vy+=(H/2-p.y)*0.002});
var heroVisible=true;
let t=0,lastMain=0;
function draw(now){
  if(!heroVisible){requestAnimationFrame(draw);return}
  if(now&&now-lastMain<33){requestAnimationFrame(draw);return} if(now)lastMain=now;
  t+=0.016;
  ctx.fillStyle='#08080a';ctx.fillRect(0,0,W,H);
  // subtle vignette dots
  ctx.fillStyle='rgba(255,255,255,.015)';for(let i=0;i<3;i++){ctx.beginPath();ctx.arc(W*.5+Math.sin(t*.2+i)*80,H*.45+Math.cos(t*.15+i)*40,220,0,Math.PI*2);ctx.fill()}
  pts.forEach(p=>{
    if(!drag){
      const dx=mx-p.x,dy=my-p.y,d=Math.hypot(dx,dy);
      if(d<150){p.vx+=dx*0.0001;p.vy+=dy*0.0001}
      p.vx+=Math.sin(t+p.x*.008)*0.0007;p.vy+=Math.cos(t+p.y*.008)*0.0007;
      p.vx*=0.992;p.vy*=0.992;
      p.x+=p.vx;p.y+=p.vy;
      if(p.x<6||p.x>W-6) p.vx*=-1;
      if(p.y<6||p.y>H-6) p.vy*=-1;
      p.x=Math.max(6,Math.min(W-6,p.x));p.y=Math.max(6,Math.min(H-6,p.y));
    }
  });
  // lines
  for(let i=0;i<N;i++) for(let j=i+1;j<N;j++){
    const dx=pts[i].x-pts[j].x,dy=pts[i].y-pts[j].y,d=Math.hypot(dx,dy);
    if(d<118){
      const a=(1-d/118)*0.32;
      ctx.strokeStyle= hover===i||hover===j? 'rgba(207,128,71,'+ (a+.4)+')' : 'rgba(255,255,255,'+a+')';
      ctx.lineWidth= hover===i||hover===j?1.1:0.6;
      ctx.beginPath();ctx.moveTo(pts[i].x,pts[i].y);ctx.lineTo(pts[j].x,pts[j].y);ctx.stroke();
    }
  }
  // pulses
  pulses=pulses.filter(pl=>pl.r<pl.max);
  pulses.forEach(pl=>{
    pl.r+=2.4;
    ctx.strokeStyle='rgba(207,128,71,'+(1-pl.r/pl.max)*0.5+')';
    ctx.lineWidth=1;ctx.beginPath();ctx.arc(pl.x,pl.y,pl.r,0,Math.PI*2);ctx.stroke();
  });
  // nodes
  pts.forEach((p,i)=>{
    const isH=i===hover;
    ctx.fillStyle=colors[p.cat];
    ctx.shadowBlur=isH?12:0;ctx.shadowColor=colors[p.cat];
    ctx.beginPath();ctx.arc(p.x,p.y,isH?4.2:p.r,0,Math.PI*2);ctx.fill();
    ctx.shadowBlur=0;
    if(isH){
      ctx.fillStyle='rgba(255,255,255,.9)';ctx.font='600 10px Onest, sans-serif';ctx.fillText(p.label,p.x+10,p.y-8);
      ctx.fillStyle='rgba(255,255,255,.5)';ctx.font='10px Onest, sans-serif';ctx.fillText(p.cat,p.x+10,p.y+4);
    }
  });
  requestAnimationFrame(draw);
}
draw();

/* ─── POLISH · komponen threeui ─── */
const REDUCE=matchMedia('(prefers-reduced-motion: reduce)').matches;
heroVisible=true;
try{new IntersectionObserver(es=>heroVisible=es[0].isIntersecting,{threshold:0}).observe(document.getElementById('atlasCanvas'))}catch(e){}

/* blur-fade - reveal saat masuk viewport */
(function(){
  if(REDUCE||!('IntersectionObserver' in window)){
    document.querySelectorAll('.rv').forEach(e=>e.classList.add('in'));return;
  }
  const io=new IntersectionObserver((es)=>{
    es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}});
  },{rootMargin:'0px 0px -8% 0px',threshold:.12});
  document.querySelectorAll('.rv').forEach(e=>io.observe(e));
})();

/* marquee - magic/marquee-01 */
(function(){
  const towns=tempat.map(s=>s.split(' - ')[0]);
  const cities=['Jakarta','Kyoto','Istanbul','Bali','Paris','Hoi An','Rio','Kairo','Seoul','Roma','Bangkok','New York'];
  function fill(track,arr,times){
    const seq=[];for(let i=0;i<times;i++) seq.push(...arr);
    seq.forEach(t=>{const d=document.createElement('span');d.className='marq-item';d.textContent=t;track.appendChild(d)});
    return track;
  }
  const t1=fill(document.getElementById('marqTowns'),towns,3);
  const t2=fill(document.getElementById('marqCities'),cities,4);
  let x1=0,x2=0,d1=-1,d2=-1;
  const card=document.querySelector('[data-mod="marq"]');
  if(card) card.addEventListener('pointerdown',()=>{d2*=-1});
  let lastMq=0;
  function loopMq(time, deltaMS){
    if(time&&time-lastMq<33) return;
    if(time)lastMq=time;
    var dt = deltaMS ? deltaMS/16.667 : 1; // normalize ke step 60fps
    x1+=d1*.55*dt; x2+=d2*.7*dt;
    const w1=t1.scrollWidth/3, w2=t2.scrollWidth/4;
    if(x1<-w1)x1=0; if(x1>0)x1=-w1;
    if(x2<-w2)x2=0; if(x2>0)x2=-w2;
    t1.style.transform='translateX('+x1+'px)';
    t2.style.transform='translateX('+x2+'px)';
  }
  if(!REDUCE){
    if(window.gsap&&gsap.ticker) gsap.ticker.add(loopMq);
    else { (function loop(now){ if(now&&now-lastMq<33){requestAnimationFrame(loop);return} if(now)lastMq=now; loopMq(now,16.667); requestAnimationFrame(loop); })(); }
  }
})();

/* gauge-01 - radial progress */
(function(){
  function gauge(id,nid,accent,target){
    const cv=document.getElementById(id),nel=document.getElementById(nid);
    if(!cv) return;
    const ctx=cv.getContext('2d');
    let W=0,H=0,cur=0;
    const DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2);
    function rs(){const r=cv.getBoundingClientRect();if(!r.width)return;W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0)}
    addEventListener('resize',rs);rs();
    cv.addEventListener('click',()=>{cur=0});
    let lastG=0;
    function drawG(now){
      if(now&&now-lastG<33){requestAnimationFrame(drawG);return} if(now)lastG=now;
      if(W){
        cur+=(target-cur)*0.06;
        ctx.clearRect(0,0,W,H);
        const cx=W/2,cy=H*.82,r=Math.min(W*.42,H*1.05);
        ctx.lineCap='round';
        ctx.strokeStyle='rgba(17,17,17,.08)';ctx.lineWidth=9;
        ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,Math.PI*2);ctx.stroke();
        const end=Math.PI+(cur/100)*Math.PI;
        ctx.strokeStyle=accent;ctx.lineWidth=9;
        ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,end);ctx.stroke();
        ctx.strokeStyle='rgba(17,17,17,.16)';ctx.lineWidth=1;
        for(let i=0;i<=8;i++){const a=Math.PI+(i/8)*Math.PI;
          ctx.beginPath();ctx.moveTo(cx+Math.cos(a)*(r-7),cy+Math.sin(a)*(r-7));
          ctx.lineTo(cx+Math.cos(a)*(r-13),cy+Math.sin(a)*(r-13));ctx.stroke();}
        const na=Math.PI+(cur/100)*Math.PI;
        ctx.fillStyle='#111';ctx.beginPath();ctx.arc(cx+Math.cos(na)*(r-20),cy+Math.sin(na)*(r-20),4.5,0,Math.PI*2);ctx.fill();
        ctx.fillStyle=accent;ctx.beginPath();ctx.arc(cx,cy,4,0,Math.PI*2);ctx.fill();
        nel.textContent=Math.round(cur)+'%';
      }
      requestAnimationFrame(drawG);
    }
    requestAnimationFrame(drawG);
  }
  const card=document.querySelector('[data-mod="gauge"]');
  let started=false;
  function start(){
    if(started)return;started=true;
    gauge('lv1','lv1n','#cf8047',Math.round(tempat.length/70*100));
    gauge('lv2','lv2n','#6aa7ff',Math.round(ide.length/70*100));
    gauge('lv3','lv3n','#4ade80',Math.round(orang.length/70*100));
  }
  if(card&&'IntersectionObserver' in window){
    const io=new IntersectionObserver(e=>{if(e[0].isIntersecting){start();io.disconnect()}},{threshold:.25});
    io.observe(card);
  } else start();
})();

/* particles-01 - bidang tolak kursor */
(function(){
  const cv=document.getElementById('pmin');if(!cv)return;
  const ctx=cv.getContext('2d');
  let W=0,H=0,pts2=[],mouse={x:-999,y:-999};
  const DPR=Math.min(devicePixelRatio||1,innerWidth<=640?1:2);
  function rs(){
    const r=cv.getBoundingClientRect();if(!r.width)return;
    W=r.width;H=r.height;cv.width=W*DPR;cv.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0);
    pts2=[];for(let i=0;i<30;i++)pts2.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.5,vy:(Math.random()-.5)*.5,r:1+Math.random()*1.5});
  }
  addEventListener('resize',rs);rs();
  cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();mouse.x=e.clientX-r.left;mouse.y=e.clientY-r.top});
  cv.addEventListener('pointerleave',()=>{mouse.x=mouse.y=-999});
  let lastP=0;let pminVisible=true;try{new IntersectionObserver(es=>pminVisible=es[0].isIntersecting,{threshold:0}).observe(document.getElementById('pmin'))}catch(e){}
  function drawP(now){ if(!pminVisible){requestAnimationFrame(drawP);return} if(now&&now-lastP<33){requestAnimationFrame(drawP);return} if(now)lastP=now;
    ctx.clearRect(0,0,W,H);
    pts2.forEach(p=>{
      p.x+=p.vx;p.y+=p.vy;
      if(p.x<0||p.x>W)p.vx*=-1; if(p.y<0||p.y>H)p.vy*=-1;
      const dx=p.x-mouse.x,dy=p.y-mouse.y,d=Math.hypot(dx,dy);
      if(d<70&&d>0){p.x+=dx/d*1.1;p.y+=dy/d*1.1}
      ctx.fillStyle='rgba(207,128,71,.9)';ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill();
    });
    for(let i=0;i<pts2.length;i++)for(let j=i+1;j<pts2.length;j++){
      const dx=pts2[i].x-pts2[j].x,dy=pts2[i].y-pts2[j].y,d=Math.hypot(dx,dy);
      if(d<70){ctx.strokeStyle='rgba(17,17,17,'+(0.16*(1-d/70))+')';ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(pts2[i].x,pts2[i].y);ctx.lineTo(pts2[j].x,pts2[j].y);ctx.stroke()}
    }
    requestAnimationFrame(drawP);
  }
  if(!REDUCE) drawP();
})();

/* orbiting-circles - magic/orbiting-circles-01 */
(function(){
  const r1=document.getElementById('orbitRing1'),r2=document.getElementById('orbitRing2');
  if(!r1||!r2||REDUCE)return;
  function ring(container,radius,count,size,dur,reverse){
    const icons=['◐','⬢','⬣','◆','◎','▣','⬔','✦'];
    for(let i=0;i<count;i++){
      const el=document.createElement('div');el.className='orbit-node';
      el.style.width=size+'px';el.style.height=size+'px';el.style.margin='-'+size/2+'px';
      el.textContent=icons[i%icons.length];
      container.appendChild(el);
      const off=(i/count)*360;
      el.animate([{transform:'rotate('+off+'deg) translateX('+radius+'px) rotate(-'+off+'deg)'},
                  {transform:'rotate('+(off+360)+'deg) translateX('+radius+'px) rotate(-'+(off+360)+'deg)'}],
                 {duration:dur,iterations:Infinity,easing:'linear',direction:reverse?'reverse':'normal'});
    }
  }
  ring(r1,78,6,34,14000,false);
  ring(r2,116,8,28,21000,true);
})();

/* animated-beam - magic/animated-beam-01, di atas SVG alur */
(function(){
  const wrap=document.querySelector('.flow-wrap');if(!wrap)return;
  const NS='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(NS,'svg');
  svg.setAttribute('class','beam-svg');svg.setAttribute('viewBox','0 0 900 360');
  svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');
  const defs=document.createElementNS(NS,'defs');
  defs.innerHTML='<linearGradient id="beamG" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#cf8047" stop-opacity="0"/><stop offset=".5" stop-color="#cf8047"/><stop offset="1" stop-color="#cf8047" stop-opacity="0"/></linearGradient>';
  svg.appendChild(defs);
  function mk(d,stroke,dash){
    const p=document.createElementNS(NS,'path');p.setAttribute('d',d);p.setAttribute('fill','none');
    p.setAttribute('stroke',stroke);p.setAttribute('stroke-width','2');
    if(dash)p.setAttribute('stroke-dasharray',dash);
    p.setAttribute('vector-effect','non-scaling-stroke');svg.appendChild(p);return p;
  }
  const b1=mk('M230 86 C 285 86, 290 86, 365 86','url(#beamG)','10 14');
  const b2=mk('M555 86 C 610 86, 605 86, 670 86','url(#beamG)','10 14');
  wrap.appendChild(svg);
  if(REDUCE)return;
  let off=0, dashVisible=true;
  try{ new IntersectionObserver(function(e){ dashVisible=e[0].isIntersecting; },{threshold:0}).observe(wrap); }catch(e){}
  function animBeam(){ if(!dashVisible) return; off-=1.1; b1.style.strokeDashoffset=off; b2.style.strokeDashoffset=-off; }
  if(window.gsap&&gsap.ticker) gsap.ticker.add(animBeam);
  else { let dashRaf=0; (function anim(){ dashRaf=0; if(!dashVisible){ dashRaf=requestAnimationFrame(anim); return; } off-=1.1;b1.style.strokeDashoffset=off;b2.style.strokeDashoffset=-off;dashRaf=requestAnimationFrame(anim); })(); }
})();

/* word-rotate - magic/word-rotate-01 di footer CTA */
(function(){
  const h2=document.querySelector('.footer-cta h2');if(!h2)return;
  const clips=h2.querySelectorAll('.clip span');
  if(clips.length<2)return;
  const words=['ingat.','pulang.','menyapa.'];
  const span=document.createElement('span');
  span.className='words';span.style.color='#5790e6';span.textContent=words[0];
  clips[1].textContent='';clips[1].appendChild(span);
  if(REDUCE)return;
  let i=0;
  setInterval(()=>{
    span.style.transition='none';span.style.transform='translateY(10px)';span.style.opacity='0';
    setTimeout(()=>{i=(i+1)%words.length;span.textContent=words[i];
      span.style.transition='all .45s cubic-bezier(.16,1,.3,1)';span.style.transform='none';span.style.opacity='1'},60);
  },2200);
})();

// ponytail: 70 points hardcoded - ganti dengan fetch JSON saat jadi CMS; constellation pakai 2D canvas - upgrade ke Three.js points saat butuh depth/zoom. Komponen polish: marquee, gauge, particles, orbiting, animated-beam, blur-fade, wavy-text, word-rotate, wireframe-sphere.


addEventListener("DOMContentLoaded",function(){var s=document.querySelector("a.skip"),m=document.getElementById("main");if(s&&m){s.addEventListener("click",function(e){try{m.focus({preventScroll:true});}catch(_){m.focus();}});}});

console.log('Atlas initialized (wireframe spheres + constellation + 70 points filter)');
}
