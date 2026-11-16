// 錦江町防災ナビ：オフラインでも開けるようにするための仕組み（錦江町森林ナビの sw.js を元にしている）
// 更新のたびに VER を上げる（index.html の APP_VER と必ず同じにする）
const VER='v1';
const BASE=new URL(self.registration.scope).pathname; // 例：/kinko-bousai/
const PFX='bousai';                                    // 同じサイトにある森林ナビの保存分と分けるための名前の頭
const SHELL=PFX+'-shell-'+VER;
const STATIC=PFX+'-static-v1';  // 地図の部品（Leaflet）：版番号つきのフォルダなので、アプリを更新しても消さない
const TILES=PFX+'-tiles-v1';    // 一度見た背景の地図画像
const HZ=PFX+'-hz-v1';          // 一度見た重ねるハザードマップの画像（配信元が更新したら、ここの番号を上げて取り直す）
const SAVED='gsi-saved-v1';     // 森林ナビの「地図を端末に保存」で保存した画像（読むだけ。ここでは消さない）
const SHELL_FILES=['./','./index.html','./manifest.webmanifest','./icon-192.png','./icon-512.png'];
const STATIC_FILES=['./lib/leaflet-1.9.4/leaflet.css','./lib/leaflet-1.9.4/leaflet.js'];
const TILE_MAX=3000;            // 背景の地図画像を覚えておく枚数の上限
const HZ_MAX=3000;              // ハザードの地図画像を覚えておく枚数の上限（区域の無い所の「無し」の返事も含む）

self.addEventListener('install',e=>{
  e.waitUntil(Promise.all([
    caches.open(SHELL).then(c=>Promise.all(SHELL_FILES.map(u=>c.add(new Request(u,{cache:'reload'})).catch(()=>{})))),
    caches.open(STATIC).then(c=>Promise.all(STATIC_FILES.map(async u=>{if(!(await c.match(u)))await c.add(u).catch(()=>{})})))
  ]).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k.startsWith(PFX+'-')&&![SHELL,STATIC,TILES,HZ].includes(k)).map(k=>caches.delete(k))))
    .then(()=>self.clients.claim()));
});

// 本体：毎回最新を確認し、圏外のときは保存分を出す
async function networkFirst(req){
  const c=await caches.open(SHELL);
  try{const r=await fetch(req.url,{cache:'no-cache',credentials:'same-origin'});if(r&&r.ok)c.put(req,r.clone()).catch(()=>{});return r}
  catch(e){const m=(await c.match(req,{ignoreSearch:true}))||(req.mode==='navigate'?await c.match('./index.html'):null);if(m)return m;throw e}
}
// 地図画像：保存分を先に使う。中身の見えない形（opaque）は保存しない（Chromeは1件を約7MBとして数え、容量不足の原因になる）
async function cacheFirst(req,cacheName,max,keep404){
  const c=await caches.open(cacheName);
  let m=await c.match(req);
  if(!m&&cacheName===TILES){try{if(await caches.has(SAVED))m=await (await caches.open(SAVED)).match(req.url)}catch(_){}} // 無いときに空の保存場所を作らない
  if(m&&m.type==='opaque'){c.delete(req).catch(()=>{});m=null}
  if(m)return m;
  const r=await fetch(req);
  // keep404：区域の無い所は配信元が「無し（404）」を返す。これも覚えて、同じ所を何度も問い合わせない
  if(r&&r.type!=='opaque'&&(r.ok||(keep404&&r.status===404))){c.put(req,r.clone()).then(()=>{if(max)trimCache(c,max)}).catch(()=>{})}
  return r;
}
let trimming=false;
async function trimCache(c,max){
  if(trimming)return;trimming=true;
  try{const keys=await c.keys();if(keys.length>max){for(const k of keys.slice(0,keys.length-max))await c.delete(k)}}finally{trimming=false}
}

self.addEventListener('fetch',e=>{
  const req=e.request;if(req.method!=='GET')return;
  const u=new URL(req.url);
  if(u.origin===location.origin){
    if(req.mode==='navigate'||u.pathname===BASE||u.pathname===BASE+'index.html'||u.pathname===BASE+'manifest.webmanifest'){e.respondWith(networkFirst(req));return}
    if(u.pathname.startsWith(BASE+'lib/')){e.respondWith(cacheFirst(req,STATIC));return}
    if(u.pathname.startsWith(BASE)){e.respondWith(networkFirst(req));return}
    return;
  }
  if(u.hostname==='cyberjapandata.gsi.go.jp'&&req.mode==='cors'){e.respondWith(cacheFirst(req,TILES,TILE_MAX));return}
  if(u.hostname==='disaportaldata.gsi.go.jp'&&req.mode==='cors'){e.respondWith(cacheFirst(req,HZ,HZ_MAX,true));return}
  // それ以外（中身の見えない形で読むときなど）は、そのまま通す
});
