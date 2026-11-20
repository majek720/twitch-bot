# -*- coding: utf-8 -*-
"""
extras.py: تحسينات لـ bot.py بدون ما تعدّل الملف الأساسي.

الاستخدام: ضع هذا الملف بجانب bot.py، وأضف في آخر bot.py (قبل سطر if __name__ == "__main__":)
الأسطر التالية:

try:
  import extras
  extras.apply(sys.modules[__name__])
except Exception as e:
  print(f"extras: {e}")

كل تحسين معزول: لو فشل واحد منها يطبع تحذير ويكمل البوت عادي.
"""
import asyncio
import json
import os
import time


# ============================================================
# 1) حماية البيانات: تحميل بإعادة محاولة + حفظ منسّق
# ============================================================
def patch_store(m):
  Store = m.Store

  def _apply_loaded(self, loaded):
    d = self.data
    if loaded.get("channels"):
      d["channels"] = loaded["channels"]
    cmds = loaded.get("commands", {})
    d["commands"] = {ch: {n: m.norm_cmd(v) for n, v in c.items()} for ch, c in cmds.items()}
    for k, v in loaded.items():
      if k not in ("channels", "commands", "reminders"):
        d[k] = v
    if "reminders" in loaded:
      d["reminders"] = loaded["reminders"]
    else:
      d["reminders"] = {c: True for c in d["channels"]}
    d["channels"] = [c for c in d["channels"] if c not in d.get("banned", [])]

  async def _write(self, raw):
    for _ in range(2):
      try:
        if self.use_gist:
          async with m.aiohttp.ClientSession() as s:
            async with s.patch(
                f"https://api.github.com/gists/{m.GIST_ID}", headers=self._headers(),
                json={"files": {m.DATA_FILE: {"content": raw}}}) as r:
              if r.status < 300:
                return True
              print(f"فشل حفظ الـ Gist: {r.status}")
        else:
          with open(m.DATA_FILE, "w", encoding="utf-8") as f:
            f.write(raw)
          return True
      except Exception as e:
        print(f"تعذر حفظ البيانات: {e}")
      await asyncio.sleep(1.5)
    return False

  async def load(self, _retry=False):
    loaded = None
    try:
      if self.use_gist:
        for i in range(6):
          try:
            async with m.aiohttp.ClientSession() as s:
              async with s.get(f"https://api.github.com/gists/{m.GIST_ID}",
                               headers=self._headers()) as r:
                if r.status != 200:
                  raise RuntimeError(f"GitHub {r.status}")
                gist = await r.json()
            f = (gist.get("files") or {}).get(m.DATA_FILE)
            loaded = json.loads(f["content"]) if f else None
            break
          except Exception as e:
            print(f"تحميل البيانات: المحاولة {i + 1} فشلت ({e})")
            await asyncio.sleep(3 * (i + 1))
        else:
          raise RuntimeError("تعذر الوصول للـ Gist")
      elif os.path.exists(m.DATA_FILE):
        with open(m.DATA_FILE, "r", encoding="utf-8") as f:
          loaded = json.load(f)
    except Exception as e:
      self._loaded = False
      print(f"⚠️ ما قدرت أحمّل بياناتك ({e}). أوقفت الحفظ عشان ما تنمسح، وبحاول مرة ثانية كل دقيقة.")
      if not _retry and not getattr(self, "_retrying", False):
        asyncio.create_task(self._retry_load())
      return
    self._loaded = True
    if loaded:
      self._apply_loaded(loaded)
    if _retry:
      print("✅ رجعت البيانات، أجدد اشتراكات الشات")
      bot = getattr(self, "_bot", None)
      if bot:
        asyncio.create_task(bot.resub_all())

  async def _retry_load(self):
    self._retrying = True
    try:
      while not getattr(self, "_loaded", False):
        await asyncio.sleep(60)
        await self.load(_retry=True)
    finally:
      self._retrying = False

  async def save(self):
    if not getattr(self, "_loaded", True):
      return  # البيانات ما انحمّلت: لا نكتب فوق الأصل أبداً
    self._ver = getattr(self, "_ver", 0) + 1
    mine = self._ver
    lock = self.__dict__.setdefault("_lock", asyncio.Lock())
    async with lock:
      if getattr(self, "_saved", 0) >= mine:
        return  # حفظ سابق شمل تغييرنا (دمج الحفظات المتزامنة)
      snap = self._ver
      raw = json.dumps(self.data, ensure_ascii=False, indent=2)
      if await self._write(raw):
        self._saved = snap

  Store._apply_loaded = _apply_loaded
  Store._write = _write
  Store.load = load
  Store._retry_load = _retry_load
  Store.save = save


# ============================================================
# 2) تنظيف الذاكرة دورياً (قواميس الكول داون تكبر مع الوقت)
# ============================================================
def prune_dicts(m, bot, now=None):
  now = now or time.time()

  def drop(d, ttl, getter=lambda v: v):
    if not isinstance(d, dict):
      return
    for k in [k for k, v in d.items() if now - getter(v) > ttl]:
      del d[k]

  drop(bot.cmd_cooldown, 3600)
  drop(bot.warned, 3600)
  drop(bot.ai_user, 3600)
  drop(bot.sent_texts, 300)
  drop(bot.live_cache, 600, lambda v: v[0])
  drop(bot.ai_ctx, 3600, lambda v: v[0])
  drop(bot.ai_notice, 3600)
  drop(m.user_reply_time, 3600)
  if isinstance(bot.permits, dict):
    for k in [k for k, v in bot.permits.items() if v < now]:
      del bot.permits[k]


def patch_bot(m):
  Bot = m.Bot
  orig_start = Bot.start
  orig_builtin = Bot.run_builtin

  async def prune_loop(self):
    while True:
      await asyncio.sleep(600)
      try:
        prune_dicts(m, self)
      except Exception as e:
        print(f"extras: خطأ في التنظيف: {e}")

  async def start(self):
    self.store._bot = self
    asyncio.create_task(prune_loop(self))
    await orig_start(self)

  # ---------- 3) كوماند !so (ترحيب بستريمر ثاني) ----------
  m.MSG["so"] = (
      "تابعوا {n} على https://twitch.tv/{u} {g}",
      "Go follow {n} at https://twitch.tv/{u} {g}")
  m.MSG["so_usage"] = ("الصيغة: !so اسم_الستريمر", "Usage: !so streamer_name")
  m.NEW_CMDS.update({"so", "shoutout"})

  async def run_builtin(self, message, cmd, content, ch, level):
    if cmd not in ("so", "shoutout"):
      return await orig_builtin(self, message, cmd, content, ch, level)
    if level < m.PERMS["mod"]:
      return True
    now = time.time()
    if now - self.cmd_cooldown.get((ch, "!so"), 0) < 5:
      return True
    self.cmd_cooldown[(ch, "!so")] = now
    toks = content.split(None, 1)
    target = toks[1].split()[0].lstrip("@").lower() if len(toks) > 1 else ""
    if not m.valid_channel(target):
      await self.say(message, ch, "so_usage")
      return True
    info = await self.twitch.user_info(target)
    if not info:
      await self.say(message, ch, "no_user", u=target)
      return True
    game, _ = await self.twitch.channel_info(info["login"])
    en = self.lang_of(ch) == "en"
    g = ((("Last played: " if en else "آخر لعبة: ") + game) if game else "")
    await self.say(message, ch, "so", n=info.get("display_name") or info["login"],
                   u=info["login"], g=g)
    return True

  Bot.start = start
  Bot.run_builtin = run_builtin


# ============================================================
# 4) حماية الموقع: منع تخمين كلمة المرور + هيدرز أمان + نسخة احتياطية
# ============================================================
class LoginThrottle:
  """5 محاولات غلط من نفس الـ IP = حظر 10 دقايق."""

  def __init__(self, limit=5, window=600):
    self.limit, self.window, self.fails = limit, window, {}

  def blocked(self, ip, now=None):
    now = now or time.time()
    rec = self.fails.get(ip)
    return bool(rec and rec[1] > now and rec[0] >= self.limit)

  def fail(self, ip, now=None):
    now = now or time.time()
    for k in [k for k, v in self.fails.items() if v[1] < now]:
      del self.fails[k]
    cnt, exp = self.fails.get(ip, (0, 0))
    if exp < now:
      cnt = 0
    self.fails[ip] = (cnt + 1, now + self.window)

  def ok(self, ip):
    self.fails.pop(ip, None)


def client_ip(request):
  return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.remote or "")


def add_security_headers(resp):
  h = resp.headers
  h.setdefault("X-Content-Type-Options", "nosniff")
  h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
  h.setdefault("X-Frame-Options", "SAMEORIGIN")


def sanitized_backup(data):
  """نسخة من البيانات بدون أي توكنات أو مفاتيح ربط."""
  d = json.loads(json.dumps(data))
  for k in ("tokens", "bot_auth"):
    d.pop(k, None)
  for acct in (d.get("botacct") or {}).values():
    if isinstance(acct, dict):
      acct.pop("refresh", None)
  return d


def patch_web(m):
  orig_make = m.make_web_app
  throttle = LoginThrottle()

  @m.web.middleware
  async def extras_mw(request, handler):
    is_login = request.method == "POST" and request.path == "/api/login"
    ip = client_ip(request)
    if is_login and throttle.blocked(ip):
      return m.jerr("محاولات كثيرة، جرّب بعد شوي", 429)
    try:
      resp = await handler(request)
    except m.web.HTTPException as e:
      add_security_headers(e)
      raise
    if is_login:
      if resp.status == 200:
        throttle.ok(ip)
      elif resp.status == 401:
        throttle.fail(ip)
    add_security_headers(resp)
    return resp

  def make_web_app(bot):
    app = orig_make(bot)

    async def backup(request):
      body = json.dumps(sanitized_backup(bot.store.data), ensure_ascii=False, indent=2)
      return m.web.Response(
          text=body, content_type="application/json",
          headers={"Content-Disposition":
                   f'attachment; filename="majek-bot-backup-{time.strftime("%Y%m%d")}.json"'})

    app.middlewares.insert(0, extras_mw)
    app.router.add_get("/api/backup", backup)
    return app

  m.make_web_app = make_web_app


# ============================================================
# 5) تحسينات الواجهة
# ============================================================
BNAV_CSS = r""".qgrid b{font-size:22px}
button,a{-webkit-tap-highlight-color:transparent}
.bnav{display:none}
@media(max-width:860px){
 .bnav{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:35;background:rgba(15,8,40,.96);backdrop-filter:blur(10px);border-top:1px solid #2d1f57;padding:6px 6px calc(6px + env(safe-area-inset-bottom));gap:4px}
 .bnav button{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;gap:2px;background:none;border:0;color:var(--mut);font:inherit;font-size:11px;padding:6px 2px;border-radius:12px;cursor:pointer}
 .bnav button b{font-size:19px;font-weight:400;line-height:1}
 .bnav button.on{color:#fff;background:color-mix(in srgb,var(--pc) 28%,transparent)}
 .content{padding-bottom:96px}
 #repbtn{bottom:84px!important}
 #toast{bottom:92px!important}
}"""

BNAV_HTML = r"""<nav class="bnav" id="bnav" hidden>
    <button data-p="ov" class="on"><b>🏠</b><span>الرئيسية</span></button>
    <button data-p="cmd"><b>⌨️</b><span>الكوماندات</span></button>
    <button data-p="songs" class="own"><b>🎵</b><span>الأغاني</span></button>
    <button data-p="spam" class="own"><b>🛡️</b><span>الحماية</span></button>
    <button data-p="more"><b>☰</b><span>المزيد</span></button>
  </nav>
  <div id="bd" hidden></div>"""


def patch_html(m):
  def sub(name, old, new):
    s = getattr(m, name, "")
    if s.count(old) != 1:
      print(f"extras: تخطيت تعديل في {name} (المكان ما انلقى أو متكرر): {old[:50]!r}")
      return
    setattr(m, name, s.replace(old, new, 1))

  S = "STREAMER_HTML"
  sub(S, ".qgrid b{font-size:22px}", BNAV_CSS)
  sub(S, '<div id="bd" hidden></div>', BNAV_HTML)
  sub(S, '$("#login").hidden=true;$("#app").hidden=false;',
      '$("#login").hidden=true;$("#app").hidden=false;$("#bnav").hidden=true;')
  sub(S, 'const c=CH,own=c.role==="owner",names=Object.keys(c.commands);',
      'const c=CH,own=c.role==="owner",names=Object.keys(c.commands);$("#bnav").hidden=false;')
  sub(S, '$("#ptitle").textContent=t(TITLES[p]);',
      '$("#ptitle").textContent=t(TITLES[p]);'
      'document.querySelectorAll("#bnav button[data-p]").forEach(x=>x.classList.toggle("on",x.dataset.p===p));')
  sub(S, 'document.querySelectorAll("[data-go]").forEach(b=>b.onclick=()=>go(b.dataset.go));',
      'document.querySelectorAll("[data-go]").forEach(b=>b.onclick=()=>go(b.dataset.go));\n'
      'document.querySelectorAll("#bnav button").forEach(b=>b.onclick=()=>{'
      'if(b.dataset.p==="more"){$("#side").classList.add("open");$("#bd").hidden=false}else go(b.dataset.p)});')
  sub(S, '"تحميل التطبيق":"Install app",',
      '"تحميل التطبيق":"Install app","الأغاني":"Songs","الحماية":"Protection","المزيد":"More",')
  sub(S, '["!permit اسم","يسمح لشخص بروابط دقيقة (مود)","Lets a viewer post links for a minute (mod)"]',
      '["!so اسم","ترحيب بستريمر ثاني مع رابط قناته (مود)","Shoutout another streamer with their link (mod)"],\n '
      '["!permit اسم","يسمح لشخص بروابط دقيقة (مود)","Lets a viewer post links for a minute (mod)"]')

  O = "OWNER_HTML"
  sub(O, '<a href="/s" target="_blank" class="ext" style="--c:#22c55e"><i>🎮</i><span>موقع الستريمر</span></a>',
      '<a href="/api/backup" download class="ext" style="--c:#fbbf24"><i>💾</i><span>نسخة احتياطية</span></a>\n'
      '      <a href="/s" target="_blank" class="ext" style="--c:#22c55e"><i>🎮</i><span>موقع الستريمر</span></a>')
  sub(O, '"الحظر":"Bans","دليل الكوماندات":"Commands guide"});',
      '"الحظر":"Bans","دليل الكوماندات":"Commands guide","نسخة احتياطية":"Backup"});')


def apply(m):
  for name, fn in (("حماية البيانات", patch_store), ("البوت", patch_bot),
                   ("الموقع", patch_web), ("الواجهة", patch_html)):
    try:
      fn(m)
      print(f"extras: {name} ✅")
    except Exception as e:
      print(f"extras: تخطيت {name} بسبب خطأ: {e}")
