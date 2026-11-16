"""錦江町防災ナビの動作確認（Playwright）。

使い方（リポジトリの1つ上のフォルダで）:
  python3 -m http.server 8765 &   # /kinko-bousai/ として配信される
  python3 kinko-bousai/tools/test_app.py

地理院タイル・重ねるハザードマップの画像は、仮の画像で代わりに返す（作業環境から外へは出ない）。
"""
import base64, os, re, sys, zlib, struct
from playwright.sync_api import sync_playwright

URL = os.environ.get('APP_URL', 'http://localhost:8765/kinko-bousai/')
CHROME = '/usr/bin/google-chrome'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def png(rgba):
    w = h = 256
    raw = b''.join(b'\x00' + bytes(rgba) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')

BASE_PNG = png((225, 230, 220, 255))
HZ_PNG = png((245, 211, 63, 160))
fails = []
def check(cond, msg):
    print(('OK  ' if cond else 'NG  ') + msg)
    if not cond:
        fails.append(msg)

# 版の一致（index.html の APP_VER と sw.js の VER）
html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
sw = open(os.path.join(ROOT, 'sw.js'), encoding='utf-8').read()
av = re.search(r"const APP_VER='([^']+)'", html).group(1)
sv = re.search(r"const VER='([^']+)'", sw).group(1)
check(av == sv, f'版が一致（index {av} / sw {sv}）')


def setup_routes(ctx, log, hz_cors=True):
    def gsi(route):
        log.append(route.request.url)
        route.fulfill(status=200, body=BASE_PNG, headers={'Content-Type': 'image/png', 'Access-Control-Allow-Origin': '*'})
    def hz(route):
        u = route.request.url
        log.append(u)
        h = {'Content-Type': 'image/png'}
        if hz_cors:
            h['Access-Control-Allow-Origin'] = '*'
        # 土石流の画像だけ「区域あり」、ほかは「区域なし（404）」
        if '05_dosekiryukeikaikuiki' in u:
            route.fulfill(status=200, body=HZ_PNG, headers=h)
        else:
            route.fulfill(status=404, body=b'', headers=h)
    ctx.route(re.compile(r'https://cyberjapandata\.gsi\.go\.jp/.*'), gsi)
    ctx.route(re.compile(r'https://disaportaldata\.gsi\.go\.jp/.*'), hz)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])

    # ---- 1. 画面の表示と操作（スマホの大きさ） ----
    ctx = br.new_context(viewport={'width': 390, 'height': 780}, device_scale_factor=2, is_mobile=True, has_touch=True)
    log = []; errs = []
    setup_routes(ctx, log)
    pg = ctx.new_page()
    # 区域の無い所は配信元が404を返す（正常）。ブラウザが記録する「404」は数えない
    pg.on('console', lambda m: m.type == 'error' and 'status of 404' not in m.text and errs.append(m.text))
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(1500)
    check(pg.is_visible('#first'), '初回の確認が出る')
    check('公式の防災情報ではありません' in pg.inner_text('#first'), '初回の確認に「公式ではない」と書いてある')
    pg.screenshot(path='/tmp/kb_first.png')
    pg.click('#first-ok')
    check(not pg.is_visible('#first'), '「わかりました」で閉じる')
    check('公式の防災情報ではありません' in pg.inner_text('#warn') and pg.is_visible('#warn'), '画面上部に断り書きが常に出ている')
    check(pg.inner_text('#vtag') == '試作 ' + av, '見出しに版が出ている')
    check(any('/xyz/pale/' in u for u in log), '最初は淡色地図を読む')
    for d in ['05_dosekiryukeikaikuiki', '05_kyukeishakeikaikuiki', '05_jisuberikeikaikuiki']:
        check(any(d in u for u in log), f'土砂災害の画像を読む（{d}）')
    check(not any('01_flood' in u for u in log), '洪水は最初は読まない')
    check(pg.is_visible('#legend') and '特別警戒' in pg.inner_text('#legend'), '凡例が出ている')
    pg.screenshot(path='/tmp/kb_map.png')

    pg.click('#bm-photo'); pg.wait_for_timeout(800)
    check(any('/xyz/seamlessphoto/' in u for u in log), '写真に切り替わる')
    check(pg.get_attribute('#bm-photo', 'aria-pressed') == 'true', '写真のボタンが押された表示になる')
    pg.click('#bm-pale'); pg.wait_for_timeout(300)

    pg.click('#layerbtn'); pg.wait_for_timeout(300)
    check(pg.is_visible('#sh-layers'), '「重ねる」の画面が開く')
    pg.screenshot(path='/tmp/kb_layers.png')
    n0 = len(log)
    pg.check('input[data-id="flood"]'); pg.wait_for_timeout(800)
    check(any('01_flood_l2_shinsuishin_data' in u for u in log[n0:]), '洪水を選ぶと読む')
    pg.uncheck('input[data-id="flood"]')
    pg.click('#sh-layers [data-close]')

    # 広く見ているときはハザードの画像を読まない（通信量を抑える）
    pg.evaluate('map.setZoom(9)'); pg.wait_for_timeout(800)
    n1 = len(log)
    pg.evaluate('map.panBy([300,0])'); pg.wait_for_timeout(800)
    check(not any('disaportaldata' in u for u in log[n1:]), '拡大率9ではハザードの画像を読まない')
    pg.evaluate('map.setZoom(12)'); pg.wait_for_timeout(500)

    pg.click('#infobtn'); pg.wait_for_timeout(300)
    info = pg.inner_text('#sh-info')
    check(pg.is_visible('#sh-info') and '出典と更新日' in info and '版 ' + av in info, '情報と出典の画面に出典・版が出る')
    pg.screenshot(path='/tmp/kb_info.png')

    pg.reload(); pg.wait_for_timeout(1200)
    check(not pg.is_visible('#first'), '2回目は初回の確認が出ない')
    check(not errs, 'エラーが出ていない ' + ' / '.join(errs[:3]))
    ctx.close()

    # ---- 2. オフライン対応（サービスワーカー） ----
    ctx = br.new_context(viewport={'width': 390, 'height': 780})
    log = []; errs = []
    setup_routes(ctx, log)
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.evaluate('navigator.serviceWorker.ready.then(()=>1)')
    pg.reload(); pg.wait_for_timeout(2500)  # サービスワーカーが働いた状態で地図を読む
    info = pg.evaluate('''async()=>{const out={};for(const k of await caches.keys()){const c=await caches.open(k);const ks=await c.keys();
        let op=0,nf=0;for(const r of ks){const m=await c.match(r);if(m.type==='opaque')op++;if(m.status===404)nf++}out[k]={n:ks.length,opaque:op,nf}}return out}''')
    print('   保存の状態:', info)
    check(f'bousai-shell-{av}' in info and info[f'bousai-shell-{av}']['n'] >= 3, '本体を保存している')
    check('bousai-static-v1' in info and info['bousai-static-v1']['n'] == 2, 'Leafletを保存している')
    check(info.get('bousai-tiles-v1', {}).get('n', 0) > 0, '背景の地図画像を保存している')
    check(info.get('bousai-hz-v1', {}).get('n', 0) > 0 and info['bousai-hz-v1']['nf'] > 0, 'ハザードの画像（区域なしの返事も）を保存している')
    check(all(v['opaque'] == 0 for v in info.values()), '中身の見えない形（opaque）で保存していない')
    ctx.set_offline(True)
    pg.reload(); pg.wait_for_timeout(1500)
    check(pg.is_visible('#map .leaflet-tile-loaded') and pg.is_visible('#warn'), '圏外でも開いて地図が出る')
    pg.screenshot(path='/tmp/kb_offline.png')
    ctx.set_offline(False)
    if pg.is_visible('#first'): pg.click('#first-ok')
    pg.click('#infobtn'); pg.click('#clr'); pg.wait_for_timeout(500)
    ks = pg.evaluate('caches.keys()')
    check('bousai-tiles-v1' not in ks and 'bousai-hz-v1' not in ks, '「保存した地図の画像を消す」で消える')
    check(not errs, 'エラーが出ていない ' + ' / '.join(errs[:3]))
    ctx.close()

    # ---- 3. 配信元が中身の見える形（CORS）に対応していないとき ----
    # Playwright の仮応答は CORS の確認を素通りするため、CORSヘッダーを付けない別のサーバーを立てて確かめる
    import threading, http.server
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if '05_dosekiryukeikaikuiki' in self.path:
                self.send_response(200); self.send_header('Content-Type', 'image/png'); self.end_headers(); self.wfile.write(HZ_PNG)
            else:
                self.send_response(404); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8766), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # 配信元だけを差し替えた本体を、一時フォルダ（リポジトリの外）に置いて開く
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix='kbtest-', dir=os.path.dirname(ROOT))
    open(os.path.join(tmp, 'index.html'), 'w', encoding='utf-8').write(
        html.replace("https://disaportaldata.gsi.go.jp/raster/", "http://127.0.0.1:8766/raster/"))
    shutil.copytree(os.path.join(ROOT, 'lib'), os.path.join(tmp, 'lib'))
    url3 = URL.rstrip('/').rsplit('/', 1)[0] + '/' + os.path.basename(tmp) + '/'
    ctx = br.new_context(viewport={'width': 390, 'height': 780}, service_workers='block')
    log = []
    setup_routes(ctx, log)
    pg = ctx.new_page()
    pg.goto(url3); pg.wait_for_timeout(2500)
    check(pg.evaluate('HZ_HOST').startswith('http://127.0.0.1:8766'), '（確認用の配信元に差し替えた）')
    check(pg.evaluate('hzCors') is False, '対応していないと判断する')
    check(pg.locator('.leaflet-pane.leaflet-hz-pane img.leaflet-tile-loaded').count() > 0, 'それでも土砂災害の画像が表示される')
    check(pg.locator('.leaflet-pane.leaflet-hz-pane img[crossorigin]').count() == 0, '読み直した画像は crossOrigin なし')
    ctx.close(); srv.shutdown(); shutil.rmtree(tmp)
    br.close()

print('\n結果:', 'すべてOK' if not fails else f'{len(fails)}件NG')
sys.exit(1 if fails else 0)
