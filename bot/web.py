"""Telefondan kullanılan web panel. Giriş kodu: WEB_CODE ortam değişkeni."""
import hashlib
import hmac
import os
import time
from datetime import timedelta

from flask import Flask, Response, jsonify, redirect, request, session

MAX_FAILS_PER_IP = 5        # bu kadar hatalı denemeden sonra IP 15 dk kilitlenir
MAX_FAILS_GLOBAL = 30       # 15 dk içinde toplam hatalı deneme sınırı
LOCK_SECONDS = 15 * 60


def create_app(agent, code: str, secret: str, cron_secret: str = "") -> Flask:
    app = Flask(__name__)
    app.secret_key = secret
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=bool(os.getenv("VERCEL")),
                      PERMANENT_SESSION_LIFETIME=timedelta(days=7))
    code_tag = hashlib.sha256((code or "").encode()).hexdigest()[:16]   # kod değişince oturumlar düşer
    store = agent.store

    def client_ip():
        # Vercel gerçek istemci IP'sini x-real-ip / x-forwarded-for olarak iletir
        if os.getenv("VERCEL"):
            ip = request.headers.get("X-Real-Ip") or request.headers.get("X-Forwarded-For", "")
            return ip.split(",")[0].strip() or "?"
        return request.remote_addr or "?"

    def authed():
        return bool(code) and session.get("ok") == code_tag

    def login_page(err="", status=200):
        if not code:
            err = "WEB_CODE ayarlanmamış. Vercel → Settings → Environment Variables bölümünden ekleyin."
        return Response(LOGIN_HTML.replace("{{ERR}}", err), mimetype="text/html", status=status)

    @app.after_request
    def headers(r):
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["Cache-Control"] = "no-store"
        return r

    @app.get("/")
    def index():
        return Response(DASH_HTML, mimetype="text/html") if authed() else login_page()

    @app.post("/login")
    def login():
        if not code:
            return login_page(status=503)
        ip = client_ip()
        if (store.get(f"fail:{ip}") or 0) >= MAX_FAILS_PER_IP or (store.get("fail:all") or 0) >= MAX_FAILS_GLOBAL:
            return login_page("Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.", 429)
        if hmac.compare_digest(request.form.get("code", "").strip().encode(), code.encode()):
            store.delete(f"fail:{ip}")
            session.permanent = True
            session["ok"] = code_tag
            agent.event("info", f"Web panele giriş yapıldı ({ip})")
            return redirect("/")
        store.incr(f"fail:{ip}", LOCK_SECONDS)
        store.incr("fail:all", LOCK_SECONDS)
        agent.event("error", f"Hatalı giriş denemesi ({ip})")
        time.sleep(1)
        return login_page("Kod yanlış.", 401)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/")

    def guard():
        if not authed():
            return jsonify(error="Giriş gerekli"), 401
        if request.method == "POST" and request.headers.get("X-Requested-With") != "panel":
            return jsonify(error="Geçersiz istek"), 400
        return None

    # Zamanlayıcının çağırdığı adres. Yetki: Authorization: Bearer CRON_SECRET  (veya ?key=CRON_SECRET)
    @app.route("/api/tick", methods=["GET", "POST"])
    def api_tick():
        auth = request.headers.get("Authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else request.args.get("key", "")
        by_cron = bool(cron_secret) and hmac.compare_digest(given.encode(), cron_secret.encode())
        if not by_cron and not authed():
            return jsonify(error="Yetkisiz"), 401
        return jsonify(agent.tick())

    @app.get("/api/status")
    def api_status():
        return guard() or jsonify(agent.status())

    @app.post("/api/pause")
    def api_pause():
        if (g := guard()):
            return g
        try:
            agent.set_paused(bool((request.json or {}).get("paused")))
        except Exception as e:
            return jsonify(error=str(e)), 409
        return jsonify(ok=True)

    @app.post("/api/close")
    def api_close():
        if (g := guard()):
            return g
        try:
            agent.close(str((request.json or {}).get("asset", "")))
        except Exception as e:
            return jsonify(error=str(e)), 500
        return jsonify(ok=True)

    @app.post("/api/test")
    def api_test():
        if (g := guard()):
            return g
        text = str((request.json or {}).get("text", "")).strip()[:2000]
        if not text:
            return jsonify(error="Metin boş"), 400
        try:
            return jsonify(agent.test(text))
        except Exception as e:
            return jsonify(error=str(e)), 500

    return app


HEAD = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0d1117"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Haber Trade Ajanı</title><style>
:root{--bg:#0d1117;--card:#161b22;--line:#262d36;--tx:#e6edf3;--mute:#8b949e;--g:#2ea043;--r:#e5534b;--y:#d29922;--b:#4493f8}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:max(14px,env(safe-area-inset-top)) 14px 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:12px 0}
h1{font-size:18px;margin:0}h2{font-size:13px;margin:0 0 10px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
button,input,textarea{font:inherit}button{border:0;border-radius:10px;padding:11px 14px;font-weight:600;color:#fff;background:var(--b);cursor:pointer}
button.r{background:var(--r)}button.g{background:var(--g)}button.ghost{background:transparent;border:1px solid var(--line);color:var(--mute)}
button:disabled{opacity:.5}.mute{color:var(--mute)}.pos{color:var(--g)}.neg{color:var(--r)}small{font-size:12px}
</style></head><body><div class="wrap">"""

LOGIN_HTML = HEAD + """
<div style="min-height:80vh;display:flex;align-items:center"><form class="card" method="post" action="/login" style="width:100%">
<h1 style="margin-bottom:4px">Haber Trade Ajanı</h1><p class="mute" style="margin:0 0 16px">Devam etmek için giriş kodunu girin.</p>
<input name="code" type="password" autocomplete="current-password" placeholder="Giriş kodu" autofocus required
 style="width:100%;padding:13px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--tx);margin-bottom:12px">
<button style="width:100%">Giriş yap</button><p class="neg" style="margin:12px 0 0">{{ERR}}</p></form></div></div></body></html>"""

DASH_HTML = HEAD + """
<style>
.top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.badge{display:inline-block;padding:3px 9px;border-radius:99px;font-size:12px;font-weight:700;letter-spacing:.03em}
.b-dry{background:#1f6feb33;color:#79b8ff}.b-test{background:#d2992233;color:#e3b341}.b-live{background:#e5534b33;color:#ff7b72}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.stat{background:var(--bg);border-radius:10px;padding:10px}
.stat b{display:block;font-size:18px;font-variant-numeric:tabular-nums}.stat span{font-size:12px;color:var(--mute)}
.row{display:flex;gap:8px}.row>*{flex:1}
.pos-card{border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:8px}
.pos-head{display:flex;justify-content:space-between;align-items:center}.side{font-weight:800;font-size:12px;padding:2px 7px;border-radius:6px}
.side.long{background:#2ea04333;color:#56d364}.side.short{background:#e5534b33;color:#ff7b72}
.grid4{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;margin:8px 0;font-size:13px;font-variant-numeric:tabular-nums}
.ev{border-top:1px solid var(--line);padding:9px 0;white-space:pre-wrap;word-break:break-word;font-size:13px}.ev:first-child{border-top:0}
.ev .k{font-size:11px;font-weight:700;margin-right:6px}.k-trade{color:var(--b)}.k-signal{color:var(--y)}.k-error{color:var(--r)}.k-news,.k-skip,.k-info{color:var(--mute)}
textarea{width:100%;min-height:80px;padding:11px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--tx);resize:vertical}
.tabs{display:flex;gap:6px;margin-bottom:8px}.tabs button{flex:1;padding:8px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}td{padding:7px 4px;border-top:1px solid var(--line)}
#err{display:none;background:#e5534b22;border:1px solid #e5534b66;color:#ffb3ad}
</style>
<div class="top"><div><h1>Haber Trade Ajanı</h1><small class="mute" id="sub">yükleniyor…</small></div>
<form method="post" action="/logout"><button class="ghost">Çıkış</button></form></div>

<div class="card" id="err"></div>

<div class="card"><div class="top" style="margin-bottom:12px"><span id="mode" class="badge"></span><span id="state" class="badge"></span></div>
<div class="stats">
<div class="stat"><b id="upnl">–</b><span>Açık K/Z (USDT)</span></div>
<div class="stat"><b id="rpnl">–</b><span>Gerçekleşen K/Z</span></div>
<div class="stat"><b id="today">–</b><span>Bugün işlem</span></div></div>
<div class="row" style="margin-top:12px"><button id="pauseBtn" onclick="togglePause()">…</button>
<button class="r" onclick="closePos('ALL')">Tümünü kapat</button></div>
<button class="ghost" id="tickBtn" style="width:100%;margin-top:8px" onclick="tick(true)">Haberleri şimdi kontrol et</button></div>

<div class="card"><h2>Açık pozisyonlar</h2><div id="positions" class="mute">–</div></div>

<div class="card"><h2>Haber testi</h2>
<textarea id="testText" placeholder="Örn: BREAKING: SEC approves spot Solana ETF"></textarea>
<button style="width:100%;margin-top:8px" id="testBtn" onclick="runTest()">Analiz et (işlem açmaz)</button>
<div id="testOut" style="margin-top:10px;font-size:13px;white-space:pre-wrap"></div></div>

<div class="card"><div class="tabs"><button id="t1" onclick="tab(1)">Akış</button><button id="t2" class="ghost" onclick="tab(2)">İşlemler</button><button id="t3" class="ghost" onclick="tab(3)">Ayarlar</button></div>
<div id="p1"></div><div id="p2" style="display:none"></div><div id="p3" style="display:none"></div></div>

<script>
let S=null;const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>v==null||v===''?'–':(+v).toLocaleString('tr-TR',{maximumFractionDigits:d});
const pnl=v=>v==null?'–':`<span class="${v>=0?'pos':'neg'}">${v>=0?'+':''}${num(v)}</span>`;
const t=iso=>iso?new Date(iso).toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'}):'–';
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'panel'},body:JSON.stringify(body)}:{});
 if(r.status===401){location.reload();throw 0}const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function showErr(m){const e=$('err');e.style.display=m?'block':'none';e.textContent=m||''}
async function load(){try{S=await api('/api/status');render();showErr(S.last_error?'Son döngü hatası: '+S.last_error:'')}catch(e){if(e)showErr('Bağlantı hatası: '+e.message)}}
function render(){
 const m={dry_run:['KÂĞIT İŞLEM','b-dry'],testnet:['TESTNET','b-test'],live:['GERÇEK PARA','b-live']}[S.mode]||[S.mode,'b-dry'];
 $('mode').textContent=m[0];$('mode').className='badge '+m[1];
 $('state').textContent=S.paused?'DURAKLATILDI':'ÇALIŞIYOR';$('state').className='badge '+(S.paused?'b-test':'b-dry');
 $('pauseBtn').textContent=S.paused?'Devam et':'Duraklat';$('pauseBtn').className=S.paused?'g':'';
 const age=S.last_poll?Math.round((Date.now()-new Date(S.last_poll))/1000):null;
 $('sub').innerHTML=`Son kontrol ${t(S.last_poll)}${age!=null&&age>180?' <span class="neg">(zamanlayıcı çalışmıyor olabilir)</span>':''} · ${S.accounts.length} hesap`;
 $('upnl').innerHTML=pnl(S.unrealized_pnl);$('rpnl').innerHTML=pnl(S.realized_pnl);$('today').textContent=`${S.trades_today}/${S.max_trades_per_day}`;
 $('positions').innerHTML=S.positions.length?S.positions.map(p=>`<div class="pos-card"><div class="pos-head">
  <div><span class="side ${p.side}">${p.side.toUpperCase()}</span> <b>${esc(p.asset)}</b> <small class="mute">${p.minutes} dk · @${esc(p.source)}</small></div><b>${pnl(p.pnl)}</b></div>
  <div class="grid4"><span class="mute">Giriş</span><span>${num(p.entry,6)}</span><span class="mute">Şimdi</span><span>${num(p.price,6)}</span>
  <span class="mute">Stop</span><span class="neg">${num(p.sl,6)}</span><span class="mute">Hedef</span><span class="pos">${num(p.tp,6)}</span></div>
  <button class="r" style="width:100%" onclick="closePos('${esc(p.asset)}')">${esc(p.asset)} kapat</button></div>`).join(''):'<span class="mute">Açık pozisyon yok.</span>';
 $('p1').innerHTML=S.events.length?S.events.map(e=>`<div class="ev"><span class="k k-${e.kind}">${t(e.t)} ${e.kind.toUpperCase()}</span>${esc(e.text)}</div>`).join(''):'<span class="mute">Henüz olay yok.</span>';
 $('p2').innerHTML=S.trades.length?'<table>'+S.trades.map(r=>`<tr><td>${t(r.time)}</td><td>${r.event==='OPEN'?'Açılış':'Kapanış'}</td><td><b>${esc(r.asset)}</b> ${esc(r.side)}</td><td>${num(r.price,6)}</td><td>${r.pnl?pnl(+r.pnl):''}</td></tr>`).join('')+'</table>':'<span class="mute">Henüz işlem yok.</span>';
 const k=S.risk;$('p3').innerHTML=`<div class="grid4"><span class="mute">İşlem başı teminat</span><span>${k.usdt_per_trade} USDT</span><span class="mute">Kaldıraç</span><span>${k.leverage}x</span>
 <span class="mute">Stop-loss</span><span>%${k.stop_loss_pct}</span><span class="mute">Take-profit</span><span>%${k.take_profit_pct}</span><span class="mute">Maks. süre</span><span>${k.max_hold_minutes} dk</span>
 <span class="mute">Maks. açık pozisyon</span><span>${k.max_open_positions}</span><span class="mute">Takip edilen</span><span>${S.accounts.map(a=>'@'+esc(a)).join(', ')}</span></div>
 <small class="mute">Ayarları değiştirmek için sunucudaki config.yaml dosyasını düzenleyip ajanı yeniden başlatın.</small>`}
function tab(n){[1,2,3].forEach(i=>{$('p'+i).style.display=i===n?'':'none';$('t'+i).className=i===n?'':'ghost'})}
async function togglePause(){if(!S.paused&&!confirm('Yeni işlem açma durdurulsun mu? Açık pozisyonlar yönetilmeye devam eder.'))return;try{await api('/api/pause',{paused:!S.paused})}catch(e){alert(e.message)}load()}
let ticking=false;async function tick(manual){if(ticking)return;ticking=true;const b=$('tickBtn');b.disabled=true;b.textContent='Kontrol ediliyor…';
 try{const r=await api('/api/tick',{});if(manual&&r.error)alert(r.error);else if(manual&&r.skipped)alert(r.skipped)}catch(e){if(manual&&e)alert(e.message)}
 ticking=false;b.disabled=false;b.textContent='Haberleri şimdi kontrol et';load()}
// Panel açıkken zamanlayıcı gecikirse turu panel tetikler
setInterval(()=>{if(S&&(!S.last_poll||Date.now()-new Date(S.last_poll)>90000))tick(false)},30000);
async function closePos(a){if(a==='ALL'&&!S.positions.length)return alert('Açık pozisyon yok.');
 if(!confirm(a==='ALL'?'TÜM pozisyonlar piyasa fiyatından kapatılsın mı?':a+' pozisyonu piyasa fiyatından kapatılsın mı?'))return;
 try{await api('/api/close',{asset:a})}catch(e){alert(e.message)}load()}
async function runTest(){const b=$('testBtn'),o=$('testOut'),txt=$('testText').value.trim();if(!txt)return;b.disabled=true;o.textContent='Analiz ediliyor…';
 try{const r=await api('/api/test',{text:txt}),a=r.analysis,d=r.decision;
  o.innerHTML=`<b>Karar: <span class="${d.action==='long'?'pos':d.action==='short'?'neg':'mute'}">${d.action.toUpperCase()} ${esc(d.asset||'')}</span></b> <span class="mute">(${esc(d.reason)})</span>
Skor ${a.score>=0?'+':''}${num(a.score)} · Güven ${num(a.confidence)} · Coin: ${esc(a.assets.join(', ')||'–')}${a.market_wide?' · genel piyasa':''}
${esc(a.reason)}`}catch(e){o.innerHTML='<span class="neg">'+esc(e.message)+'</span>'}b.disabled=false}
load();setInterval(load,5000);
</script></div></body></html>"""
