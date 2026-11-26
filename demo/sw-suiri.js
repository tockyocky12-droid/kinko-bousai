// 錦江町消防水利マップ（仮）：ホーム画面から開けて、電波が弱くても開けるようにする仕組み（きんこう防災ナビの sw.js を元にしている）
// 更新のたびに VER を上げる（suiri.html の APP_VER と必ず同じにする）
const VER='s1';
const PFX='suiri';                 // 防災ナビ（bousai-）・森林ナビの保存分と分けるための名前の頭
const SHELL=PFX+'-shell-'+VER;
const STATIC=PFX+'-static-v1';     // Leaflet（版番号つきのフォルダなので、更新しても消さない）
const TILES=PFX+'-tiles-v1';       // 一度見た背景の地図・写真
const ROADS=PFX+'-roads-v1';       // 一度読んだ道路のデータ（距離の計算用）
const SHELL_FILES=['./suiri.html','./suiri.webmanifest','./suiri-icon-192.png','./suiri-icon-512.png'];
const STATIC_FILES=['../lib/leaflet-1.9.4/leaflet.css','../lib/leaflet-1.9.4/leaflet.js'];
const TILE_MAX=1500;               // 背景の地図画像を覚えておく枚数の上限
const ROAD_MAX=400;                // 道路のデータを覚えておく枚数の上限

self.addEventListener('install',e=>{
  e.waitUntil(Promise.all([
    caches.open(SHELL).then(c=>Promise.all(SHELL_FILES.map(u=>c.add(new Request(u,{cache:'reload'})).catch(()=>{})))),
    caches.open(STATIC).then(c=>Promise.all(STATIC_FILES.map(async u=>{if(!(await c.match(u)))await c.add(u).catch(()=>{})})))
  ]).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k.startsWith(PFX+'-')&&![SHELL,STATIC,TILES,ROADS].includes(k)).map(k=>caches.delete(k))))
    .then(()=>self.clients.claim()));
});
// 画面本体：毎回最新を確認し、圏外のときは保存分を出す
async function networkFirst(req){
  const c=await caches.open(SHELL);
  try{const r=await fetch(req.url,{cache:'no-cache',credentials:'same-origin'});if(r&&r.ok)c.put(req.url.split('?')[0],r.clone()).catch(()=>{});return r}
  catch(e){const m=(await c.match(req,{ignoreSearch:true}))||(req.mode==='navigate'?await c.match('./suiri.html'):null);if(m)return m;throw e}
}
// 地図画像・道路データ：保存分を先に使う。中身の見えない形（opaque）は保存しない（Chromeは1件を約7MBとして数えるため）
async function cacheFirst(req,name,max){
  const c=await caches.open(name);
  let m=await c.match(req);
  if(m&&m.type==='opaque'){c.delete(req).catch(()=>{});m=null}
  if(m)return m;
  const r=await fetch(req);
  if(r&&r.ok&&r.type!=='opaque')c.put(req,r.clone()).then(()=>trimCache(c,max)).catch(()=>{});
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
    if(u.pathname.includes('/lib/')){e.respondWith(cacheFirst(req,STATIC,9999));return}
    e.respondWith(networkFirst(req));return;
  }
  if(u.hostname==='cyberjapandata.gsi.go.jp'&&req.mode==='cors'){
    e.respondWith(cacheFirst(req,u.pathname.includes('experimental_rdcl')?ROADS:TILES,u.pathname.includes('experimental_rdcl')?ROAD_MAX:TILE_MAX));return}
});
