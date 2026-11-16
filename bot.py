import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import time

import aiohttp
from aiohttp import web
from twitchio.ext import commands

# تثبيت الـ Event Loop لبيئة Render
asyncio.set_event_loop(asyncio.new_event_loop())

# ============================================================
# الإعدادات (الأسرار تنحط في Environment Variables في Render)
# ============================================================
ACCESS_TOKEN = os.environ.get("TWITCH_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # اختياري: لحفظ البيانات بشكل دائم
GIST_ID = os.environ.get("GIST_ID")  # اختياري: معرف الـ Gist
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")  # كلمة مرور لوحة التحكم

OWNER = "majek113"
IGNORED_USERS = set()  # يوزرات تتجاهل ردودهم التلقائية (فاضية حالياً)
DEFAULT_CHANNELS = ["majek113", "teamiik", "iz0yi", "vul1_", "lyorll"]

DATA_FILE = "bot_data.json"
USER_COOLDOWN = 15  # ثواني بين ردود كل يوزر
COMMAND_COOLDOWN = 5  # ثواني بين استخدام نفس الكوماند في نفس القناة
LIVE_CACHE_SECONDS = 60

# كوماندات البوت الأساسية (ما تنفع كأسماء لكوماندات مخصصة)
BUILTIN = {
    "addcom", "editcom", "delcom", "removecom", "commands",
    "addchannel", "removechannel", "channels",
}

DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وحسن عبادتك",
]

SAUDI_PRAYERS = [
    "اللهم احفظ المملكة العربية السعودية وبارك في أمنها ورخائها وولاة أمرها وشعبها",
    "اللهم أدِم على السعودية أمنها وأمانها واحفظها من كل شر وسوء",
    "اللهم اجعل هذا البلد آمناً مطمئناً وسائر بلاد المسلمين واحفظ وطننا السعودية",
    "اللهم احفظ خادم الحرمين الشريفين وولي عهده الأمين وبارك في جهودهما لخدمة الوطن",
    "اللهم إنا استودعناك السعودية أمنها وأرضها وسمائها وسلامة أهلها",
    "اللهم انصر قواتنا المرابطة واحفظ حدودنا وجد ليالينا بالأمن والأمان يا رب العالمين",
]

user_reply_time = {}


# ============================================================
# التخزين: Gist (دائم) أو ملف محلي (يتصفر مع كل إعادة تشغيل في Render)
# ============================================================
class Store:

  def __init__(self):
    self.data = {"channels": list(DEFAULT_CHANNELS), "commands": {}}

  @property
  def use_gist(self):
    return bool(GITHUB_TOKEN and GIST_ID)

  def _headers(self):
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "twitch-bot",
    }

  async def load(self):
    try:
      if self.use_gist:
        async with aiohttp.ClientSession() as session:
          async with session.get(
              f"https://api.github.com/gists/{GIST_ID}", headers=self._headers()
          ) as resp:
            gist = await resp.json()
        loaded = json.loads(gist["files"][DATA_FILE]["content"])
      elif os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
          loaded = json.load(f)
      else:
        return
      if loaded.get("channels"):
        self.data["channels"] = loaded["channels"]
      self.data["commands"] = loaded.get("commands", {})
    except Exception as e:
      print(f"تعذر تحميل البيانات: {e}")

  async def save(self):
    raw = json.dumps(self.data, ensure_ascii=False, indent=2)
    try:
      if self.use_gist:
        payload = {"files": {DATA_FILE: {"content": raw}}}
        async with aiohttp.ClientSession() as session:
          async with session.patch(
              f"https://api.github.com/gists/{GIST_ID}",
              headers=self._headers(),
              json=payload,
          ) as resp:
            if resp.status >= 300:
              print(f"فشل حفظ الـ Gist: {resp.status}")
      else:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
          f.write(raw)
    except Exception as e:
      print(f"تعذر حفظ البيانات: {e}")


# ============================================================
# لوحة التحكم (واجهة ويب) + خادم Keep-Alive
# ============================================================
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0e0e12">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg">
<title>لوحة تحكم البوت</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0e0e12;--card:#18181f;--line:#2a2a35;--tx:#f1f1f5;--mut:#9a9aab;--acc:#9146ff;--ok:#2ecc71;--bad:#ff5c6c}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--tx);font-family:Tajawal,system-ui,sans-serif;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
.wrap{max-width:720px;margin:0 auto;padding:16px}
header{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-size:22px}
header h1{font-size:18px;margin:0}header small{color:var(--mut);display:block}
header .sp{flex:1}
.tabs{display:flex;gap:6px;background:var(--card);padding:5px;border-radius:14px;margin-bottom:16px}
.tabs button{flex:1;padding:10px;border:0;border-radius:10px;background:none;color:var(--mut);font:inherit;font-weight:500;cursor:pointer}
.tabs button.on{background:var(--acc);color:#fff}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:14px}
h2{font-size:15px;margin:0 0 12px;color:var(--mut);font-weight:500}
input,select,textarea{width:100%;background:#0e0e12;border:1px solid var(--line);color:var(--tx);border-radius:10px;padding:11px 12px;font:inherit;margin-bottom:10px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--acc);border-color:transparent}
textarea{min-height:90px;resize:vertical}
.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:11px 18px;font:inherit;font-weight:700;cursor:pointer;width:100%}
.btn.ghost{background:none;border:1px solid var(--line);color:var(--mut);width:auto;padding:8px 14px}
.row{display:flex;align-items:center;gap:10px;padding:12px 4px;border-bottom:1px solid var(--line)}
.row:last-child{border:0}
.row b{flex:1;text-align:right}
.row small{color:var(--mut)}
.row.col{flex-direction:column;align-items:stretch;gap:6px}
.row .top{display:flex;align-items:center;justify-content:space-between}
.row p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.dot{width:10px;height:10px;border-radius:50%;background:#555}
.dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.ic{background:none;border:0;font-size:18px;cursor:pointer;padding:4px 8px;border-radius:8px}
.ic:hover{background:var(--line)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.chips span{background:var(--line);color:var(--mut);font-size:12px;padding:5px 10px;border-radius:20px;cursor:pointer;direction:ltr}
.empty{color:var(--mut);text-align:center;margin:12px 0}
#toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);background:var(--ok);color:#000;padding:11px 20px;border-radius:12px;font-weight:700;transition:.25s;opacity:0}
#toast.show{transform:translate(-50%,0);opacity:1}#toast.bad{background:var(--bad);color:#fff}
#login{min-height:80vh;display:grid;place-items:center}
#login .card{width:100%;max-width:360px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
<div id="login" hidden>
  <div class="card">
    <div class="logo" style="margin:0 auto 12px">🤖</div>
    <h1 style="font-size:20px;margin:0 0 16px">لوحة تحكم البوت</h1>
    <input id="pw" type="password" placeholder="كلمة المرور" autocomplete="current-password">
    <button class="btn" id="loginBtn">دخول</button>
  </div>
</div>

<div id="app" hidden>
  <header>
    <div class="logo">🤖</div>
    <div><h1>لوحة تحكم البوت</h1><small id="botname"></small></div>
    <div class="sp"></div>
    <button class="btn ghost" id="logout">خروج</button>
  </header>
  <div class="tabs">
    <button class="on" data-t="ch">القنوات</button>
    <button data-t="cmd">الكوماندات</button>
    <button data-t="msg">إرسال رسالة</button>
  </div>

  <section id="t-ch">
    <div class="card">
      <h2>إضافة قناة</h2>
      <input id="newch" dir="ltr" placeholder="اسم القناة مثل: majek113">
      <button class="btn" id="addch">إضافة القناة</button>
    </div>
    <div class="card"><h2>القنوات الحالية</h2><div id="chlist"></div></div>
  </section>

  <section id="t-cmd" hidden>
    <div class="card">
      <h2>إضافة / تعديل كوماند</h2>
      <select id="cmdch"></select>
      <input id="cname" dir="ltr" placeholder="اسم الكوماند بدون !  مثل: discord">
      <textarea id="creply" placeholder="رد البوت"></textarea>
      <div class="chips" id="chips"><span>$(user)</span><span>$(touser)</span><span>$(channel)</span></div>
      <button class="btn" id="savecmd">حفظ الكوماند</button>
    </div>
    <div class="card"><h2>كوماندات القناة</h2><div id="cmdlist"></div></div>
  </section>

  <section id="t-msg" hidden>
    <div class="card">
      <h2>إرسال رسالة كأنك البوت</h2>
      <select id="msgch"></select>
      <textarea id="msgtxt" placeholder="نص الرسالة"></textarea>
      <button class="btn" id="sendmsg">إرسال</button>
    </div>
  </section>
</div>
</div>
<div id="toast"></div>

<script>
const $=s=>document.querySelector(s);
let S={channels:[],commands:{},bot:""};
function toast(m,bad){const t=$("#toast");t.textContent=m;t.className="show"+(bad?" bad":"");setTimeout(()=>t.className="",2200)}
async function api(method,path,body){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  if(r.status===401&&path!=="/api/login"){show(false);throw new Error("auth")}
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.error||"صار خطأ");
  return d;
}
function show(on){$("#login").hidden=on;$("#app").hidden=!on}
async function act(fn,msg){try{await fn();if(msg)toast(msg);await load()}catch(e){if(e.message!=="auth")toast(e.message,1)}}
async function load(){
  try{S=await api("GET","/api/state");show(true);render()}catch(e){if(e.message!=="auth")toast(e.message,1)}
}
function render(){
  $("#botname").textContent=S.bot?"البوت: "+S.bot:"";
  const list=$("#chlist");list.innerHTML="";
  if(!S.channels.length)list.innerHTML='<p class="empty">ما فيه قنوات</p>';
  S.channels.forEach(c=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<span class="dot'+(c.live?" on":"")+'"></span><b dir="ltr"></b><small>'+(c.live?"لايف":"أوفلاين")+'</small><button class="ic">🗑</button>';
    d.querySelector("b").textContent=c.name;
    d.querySelector("button").onclick=()=>{if(confirm("تحذف القناة "+c.name+"؟"))act(()=>api("DELETE","/api/channels/"+encodeURIComponent(c.name)),"تم حذف القناة")};
    list.appendChild(d);
  });
  for(const id of ["#cmdch","#msgch"]){
    const s=$(id),v=s.value;s.innerHTML="";
    S.channels.forEach(c=>s.add(new Option(c.name,c.name)));
    if(S.channels.some(c=>c.name===v))s.value=v;
  }
  renderCmds();
}
function renderCmds(){
  const ch=$("#cmdch").value,box=$("#cmdlist");box.innerHTML="";
  const cmds=S.commands[ch]||{},names=Object.keys(cmds).sort();
  if(!names.length){box.innerHTML='<p class="empty">ما فيه كوماندات في هذي القناة</p>';return}
  names.forEach(n=>{
    const d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b dir="ltr"></b><span><button class="ic ed">✏️</button><button class="ic del">🗑</button></span></div><p></p>';
    d.querySelector("b").textContent="!"+n;
    d.querySelector("p").textContent=cmds[n];
    d.querySelector(".ed").onclick=()=>{$("#cname").value=n;$("#creply").value=cmds[n];window.scrollTo({top:0,behavior:"smooth"})};
    d.querySelector(".del").onclick=()=>{if(confirm("تحذف !"+n+"؟"))act(()=>api("DELETE","/api/commands/"+encodeURIComponent(ch)+"/"+encodeURIComponent(n)),"تم حذف الكوماند")};
    box.appendChild(d);
  });
}
$("#loginBtn").onclick=async()=>{
  try{await api("POST","/api/login",{password:$("#pw").value});$("#pw").value="";await load()}
  catch(e){toast(e.message,1)}
};
$("#pw").onkeydown=e=>{if(e.key==="Enter")$("#loginBtn").click()};
$("#logout").onclick=async()=>{await api("POST","/api/logout");show(false)};
$("#addch").onclick=()=>act(async()=>{await api("POST","/api/channels",{name:$("#newch").value});$("#newch").value=""},"تمت إضافة القناة");
$("#cmdch").onchange=renderCmds;
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST","/api/commands",{channel:$("#cmdch").value,name:$("#cname").value,reply:$("#creply").value});
  $("#cname").value="";$("#creply").value="";
},"تم حفظ الكوماند");
$("#chips").onclick=e=>{if(e.target.tagName==="SPAN"){const t=$("#creply");t.value+=e.target.textContent;t.focus()}};
$("#sendmsg").onclick=()=>act(async()=>{
  await api("POST","/api/send",{channel:$("#msgch").value,text:$("#msgtxt").value});$("#msgtxt").value="";
},"تم الإرسال");
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  for(const t of ["ch","cmd","msg"])$("#t-"+t).hidden=t!==b.dataset.t;
});
setInterval(()=>{if(!$("#app").hidden)load()},60000);
load();
</script>
</body>
</html>
"""

SESSION_TOKEN = (
    hashlib.sha256(("dash:" + DASHBOARD_PASSWORD).encode()).hexdigest()
    if DASHBOARD_PASSWORD else None
)

ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect width="100" height="100" rx="24" fill="#9146ff"/>'
    '<text x="50" y="68" font-size="56" text-anchor="middle">🤖</text></svg>'
)

MANIFEST = {
    "name": "لوحة تحكم البوت", "short_name": "البوت", "start_url": "/",
    "display": "standalone", "background_color": "#0e0e12",
    "theme_color": "#0e0e12", "lang": "ar", "dir": "rtl",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
}


def jerr(msg, status=400):
  return web.json_response({"error": msg}, status=status)


def make_web_app(bot):
  store = bot.store

  def authed(request):
    tok = request.cookies.get("session", "")
    return bool(SESSION_TOKEN) and hmac.compare_digest(tok.encode(), SESSION_TOKEN.encode())

  @web.middleware
  async def auth_mw(request, handler):
    if request.path.startswith("/api/") and request.path != "/api/login" and not authed(request):
      return jerr("unauthorized", 401)
    return await handler(request)

  async def index(request):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")

  async def ping(request):
    return web.Response(text="Bot is alive!")

  async def manifest(request):
    return web.json_response(MANIFEST)

  async def icon(request):
    return web.Response(text=ICON_SVG, content_type="image/svg+xml")

  async def login(request):
    if not SESSION_TOKEN:
      return jerr("لوحة التحكم مقفلة: ضيف DASHBOARD_PASSWORD في Render", 503)
    body = await request.json()
    await asyncio.sleep(1)
    if not hmac.compare_digest(str(body.get("password", "")).encode(), DASHBOARD_PASSWORD.encode()):
      return jerr("كلمة المرور غلط", 401)
    resp = web.json_response({"ok": True})
    resp.set_cookie("session", SESSION_TOKEN, max_age=60 * 60 * 24 * 30, httponly=True,
                    samesite="Lax", secure=request.headers.get("X-Forwarded-Proto") == "https")
    return resp

  async def logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie("session")
    return resp

  async def state(request):
    names = list(store.data["channels"])
    lives = await asyncio.gather(*[bot.is_channel_live(c) for c in names])
    return web.json_response({
        "bot": bot.nick,
        "channels": [{"name": n, "live": l} for n, l in zip(names, lives)],
        "commands": store.data["commands"],
    })

  async def add_channel(request):
    name = str((await request.json()).get("name", "")).strip().lstrip("@#").lower()
    if not valid_channel(name):
      return jerr("اسم القناة غير صحيح")
    if name in store.data["channels"]:
      return jerr("القناة مضافة من قبل")
    store.data["channels"].append(name)
    await store.save()
    await bot.join_channels([name])
    return web.json_response({"ok": True})

  async def del_channel(request):
    name = request.match_info["name"].lower()
    if name not in store.data["channels"]:
      return jerr("القناة مو موجودة", 404)
    store.data["channels"].remove(name)
    await store.save()
    await bot.part_channels([name])
    return web.json_response({"ok": True})

  async def save_command(request):
    b = await request.json()
    ch = str(b.get("channel", "")).lower()
    name = str(b.get("name", "")).strip().lstrip("!").lower()
    reply = str(b.get("reply", "")).strip()
    if ch not in store.data["channels"]:
      return jerr("اختر قناة صحيحة")
    if not name or len(name) > 30 or " " in name or name in BUILTIN:
      return jerr("اسم الكوماند ما ينفع")
    if not reply:
      return jerr("اكتب رد الكوماند")
    store.data["commands"].setdefault(ch, {})[name] = reply[:450]
    await store.save()
    return web.json_response({"ok": True})

  async def del_command(request):
    ch = request.match_info["channel"].lower()
    name = request.match_info["name"].lower()
    cmds = store.data["commands"].get(ch, {})
    if name not in cmds:
      return jerr("الكوماند مو موجود", 404)
    del cmds[name]
    await store.save()
    return web.json_response({"ok": True})

  async def send_msg(request):
    b = await request.json()
    channel = bot.get_channel(str(b.get("channel", "")).lower())
    text = str(b.get("text", "")).strip()[:490]
    if not channel or not text:
      return jerr("اختر قناة واكتب الرسالة")
    await channel.send(text)
    return web.json_response({"ok": True})

  app = web.Application(middlewares=[auth_mw])
  app.router.add_get("/", index)
  app.router.add_get("/ping", ping)
  app.router.add_get("/manifest.json", manifest)
  app.router.add_get("/icon.svg", icon)
  app.router.add_post("/api/login", login)
  app.router.add_post("/api/logout", logout)
  app.router.add_get("/api/state", state)
  app.router.add_post("/api/channels", add_channel)
  app.router.add_delete("/api/channels/{name}", del_channel)
  app.router.add_post("/api/commands", save_command)
  app.router.add_delete("/api/commands/{channel}/{name}", del_command)
  app.router.add_post("/api/send", send_msg)
  return app


async def start_web_server(bot):
  runner = web.AppRunner(make_web_app(bot))
  await runner.setup()
  port = int(os.environ.get("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


def format_response(text, user, channel, target):
  """المتغيرات المدعومة: $(user) $(touser) $(channel)"""
  return (
      text.replace("$(user)", user)
      .replace("$(touser)", target or user)
      .replace("$(channel)", channel)
  )


def valid_channel(name):
  return re.fullmatch(r"[a-z0-9_]{3,25}", name) is not None


class Bot(commands.Bot):

  def __init__(self):
    super().__init__(token=ACCESS_TOKEN, prefix="!", initial_channels=[OWNER])
    self.store = Store()
    self.last_dhikr = None
    self.last_saudi_prayer = None
    self.live_cache = {}
    self.cmd_cooldown = {}
    self._started = False

  async def event_ready(self):
    print(f"تم الاتصال بنجاح! ({self.nick}) يعمل كـ Bot للردود والتذكيرات.")
    if self._started:
      return
    self._started = True
    await self.store.load()
    to_join = [c for c in self.store.data["channels"] if c != OWNER]
    if to_join:
      await self.join_channels(to_join)
    asyncio.create_task(start_web_server(self))
    asyncio.create_task(self.periodic_reminders())

  async def event_command_error(self, ctx, error):
    pass

  async def is_channel_live(self, channel_name):
    now = time.time()
    cached = self.live_cache.get(channel_name)
    if cached and now - cached[0] < LIVE_CACHE_SECONDS:
      return cached[1]
    try:
      streams = await self.fetch_streams(user_logins=[channel_name])
      live = len(streams) > 0
    except Exception:
      live = False
    self.live_cache[channel_name] = (now, live)
    return live

  def get_random_dhikr(self):
    available = [d for d in DHIKR_LIST if d != self.last_dhikr]
    selected = random.choice(available)
    self.last_dhikr = selected
    return selected

  def get_random_saudi_prayer(self):
    available = [p for p in SAUDI_PRAYERS if p != self.last_saudi_prayer]
    selected = random.choice(available)
    self.last_saudi_prayer = selected
    return selected

  async def periodic_reminders(self):
    step = 0
    while True:
      await asyncio.sleep(1800)
      if step == 0:
        message_text = f"اللهم صلِّ وسلم على نبينا محمد، {self.get_random_saudi_prayer()}"
      elif step == 1:
        message_text = self.get_random_dhikr()
      else:
        message_text = "اشربوا ماااااااي"

      for channel_name in list(self.store.data["channels"]):
        if await self.is_channel_live(channel_name):
          channel = self.get_channel(channel_name)
          if channel:
            try:
              await channel.send(message_text)
            except Exception as e:
              print(f"تعذر إرسال التذكير في {channel_name}: {e}")

      step = (step + 1) % 3

  # ----------------------------------------------------------
  # الكوماندات (إدارة + مخصصة)
  # ----------------------------------------------------------
  async def handle_command(self, message, content, username, channel_name,
                           is_owner, is_mod):
    parts = content.split(maxsplit=2)
    cmd = parts[0][1:].lower()
    if not cmd:
      return False

    send = message.channel.send
    mention = f"@{message.author.name}"
    channel_cmds = self.store.data["commands"].setdefault(channel_name, {})

    # ---------- كوماندات المودرز ----------
    if cmd in ("addcom", "editcom", "delcom", "removecom", "commands"):
      if cmd == "commands":
        if not channel_cmds:
          await send(f"{mention} ما فيه كوماندات مضافة للحين")
        else:
          names = " ".join(f"!{n}" for n in sorted(channel_cmds))
          await send(f"{mention} الكوماندات: {names}"[:480])
        return True

      if not is_mod:
        return True

      if cmd in ("delcom", "removecom"):
        if len(parts) < 2:
          await send(f"{mention} الصيغة: !delcom !اسم_الكوماند")
          return True
        name = parts[1].lstrip("!").lower()
        if name in channel_cmds:
          del channel_cmds[name]
          await self.store.save()
          await send(f"{mention} تم حذف الكوماند !{name} ✅")
        else:
          await send(f"{mention} ما لقيت كوماند باسم !{name}")
        return True

      # addcom / editcom
      if len(parts) < 3:
        await send(f"{mention} الصيغة: !{cmd} !اسم_الكوماند الرد")
        return True
      name = parts[1].lstrip("!").lower()
      reply = parts[2].strip()
      if not name or len(name) > 30 or name in BUILTIN:
        await send(f"{mention} هذا الاسم ما ينفع للكوماند")
        return True

      if cmd == "addcom":
        if name in channel_cmds:
          await send(f"{mention} الكوماند !{name} موجود، استخدم !editcom للتعديل")
          return True
        channel_cmds[name] = reply
        await self.store.save()
        await send(f"{mention} تمت إضافة الكوماند !{name} ✅")
      else:
        if name not in channel_cmds:
          await send(f"{mention} ما لقيت !{name}، استخدم !addcom للإضافة")
          return True
        channel_cmds[name] = reply
        await self.store.save()
        await send(f"{mention} تم تعديل الكوماند !{name} ✅")
      return True

    # ---------- كوماندات الأونر (إدارة القنوات) ----------
    if cmd in ("addchannel", "removechannel", "channels"):
      if not is_owner:
        return True

      if cmd == "channels":
        await send(f"{mention} القنوات: " + ", ".join(self.store.data["channels"]))
        return True

      if len(parts) < 2:
        await send(f"{mention} الصيغة: !{cmd} اسم_القناة")
        return True
      target = parts[1].lstrip("@#").lower()
      if not valid_channel(target):
        await send(f"{mention} اسم القناة غير صحيح")
        return True

      if cmd == "addchannel":
        if target in self.store.data["channels"]:
          await send(f"{mention} القناة {target} مضافة من قبل")
          return True
        self.store.data["channels"].append(target)
        await self.store.save()
        await self.join_channels([target])
        await send(f"{mention} تمت إضافة القناة {target} ✅")
      else:
        if target not in self.store.data["channels"]:
          await send(f"{mention} القناة {target} مو موجودة بالقائمة")
          return True
        self.store.data["channels"].remove(target)
        await self.store.save()
        await self.part_channels([target])
        await send(f"{mention} تم حذف القناة {target} ✅")
      return True

    # ---------- كوماند مخصص ----------
    reply = channel_cmds.get(cmd)
    if reply is None:
      return False

    # الكوماندات المخصصة ما ترد إلا إذا القناة لايف
    if not await self.is_channel_live(channel_name):
      return True

    key = (channel_name, cmd)
    now = time.time()
    if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
      return True
    self.cmd_cooldown[key] = now

    target = parts[1].lstrip("@") if len(parts) > 1 else ""
    await send(format_response(reply, message.author.name, channel_name, target)[:490])
    return True

  # ----------------------------------------------------------
  # الرسائل
  # ----------------------------------------------------------
  async def event_message(self, message):
    if message.echo or message.author is None:
      return

    username = message.author.name.lower()
    channel_name = message.channel.name.lower()
    content = message.content.strip()
    is_owner = username == OWNER
    is_mod = is_owner or message.author.is_mod or message.author.is_broadcaster

    # الكوماندات تشتغل حتى للأونر
    if content.startswith("!"):
      if await self.handle_command(
          message, content, username, channel_name, is_owner, is_mod
      ):
        return

    # الردود التلقائية: تجاهل الأونر والمستخدمين المتجاهلين
    if is_owner or username in IGNORED_USERS:
      return

    await self.auto_replies(message, content, username, channel_name)

  async def auto_replies(self, message, content, username, channel_name):
    current_time = time.time()

    if username in user_reply_time and current_time - user_reply_time[username] < USER_COOLDOWN:
      return

    if not await self.is_channel_live(channel_name):
      return

    content = content.lower()
    author_mention = f"@{message.author.name}"
    clean_content = re.sub(r"[^\w\s]", "", content)
    words = clean_content.split()

    if not words:
      return

    has_evening = "مساء الخير" in content
    has_full_greeting = "السلام عليكم" in content or "سلام عليكم" in content
    has_single_greeting = words[0] in ["السلام", "سلام"]
    has_greeting = has_full_greeting or has_single_greeting

    replied = False

    if has_greeting and has_evening:
      await message.channel.send(
          f"{author_mention} وعليكم السلام ورحمة الله وبركاته، ومساء النور"
          " نورت البث"
      )
      replied = True
    elif has_evening:
      await message.channel.send(f"{author_mention} مساء النور")
      replied = True
    elif words[0] == "باك":
      await message.channel.send(f"{author_mention} ولكم باك")
      replied = True
    elif words[0] in ["brb", "برب"]:
      await message.channel.send(f"{author_mention} خذ راحتك بس لا تطول علينا")
      replied = True
    elif has_greeting:
      await message.channel.send(
          f"{author_mention} وعليكم السلام ورحمة الله وبركاته، نورت البث"
      )
      replied = True

    if replied:
      user_reply_time[username] = current_time


if __name__ == "__main__":
  bot = Bot()
  bot.run()
