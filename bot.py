import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import time
from urllib.parse import urlencode

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
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")  # لوحة الأونر

# موقع الستريمرز (تسجيل دخول بتويتش + تغيير اللعبة)
CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
SITE_URL = (os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
SELF_JOIN = os.environ.get("SELF_JOIN", "1") != "0"  # الستريمر يفعّل البوت بنفسه (ضع 0 لإيقافه)
SECRET = (os.environ.get("SESSION_SECRET") or CLIENT_SECRET or "").encode()

OWNER = "majek113"
IGNORED_USERS = set()
DEFAULT_CHANNELS = ["majek113", "teamiik", "iz0yi", "vul1_", "lyorll"]

DATA_FILE = "bot_data.json"
USER_COOLDOWN = 15
COMMAND_COOLDOWN = 5
LIVE_CACHE_SECONDS = 60

AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix/"
GAME_SCOPE = "channel:manage:broadcast"

# مستويات الصلاحيات: كل مستوى يشمل اللي فوقه
PERMS = {"everyone": 0, "sub": 1, "vip": 2, "mod": 3, "broadcaster": 4}

# كوماندات البوت الأساسية (ما تنفع كأسماء لكوماندات مخصصة)
BUILTIN = {
    "addcmd", "editcmd", "delcmd", "removecmd", "cmds", "addgame",
    "addchannel", "removechannel", "channels", "commands",
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
# أدوات مساعدة
# ============================================================
def valid_channel(name):
  return re.fullmatch(r"[a-z0-9_]{3,25}", name) is not None


def norm_cmd(v):
  """يحوّل الكوماند القديم (نص) للشكل الجديد."""
  if isinstance(v, str):
    return {"type": "text", "reply": v, "game": "", "perm": "everyone", "bang": True}
  v = dict(v)
  v.setdefault("type", "text")
  v.setdefault("reply", "")
  v.setdefault("game", "")
  v.setdefault("bang", True)
  if v.get("perm") not in PERMS:
    v["perm"] = "everyone"
  return v


def build_command(b):
  """يتحقق من بيانات كوماند جاية من الواجهة ويرجع (الاسم، الكوماند)."""
  name = str(b.get("name", "")).strip().lstrip("!").lower()
  if not name or len(name) > 30 or re.search(r"\s", name) or name in BUILTIN:
    raise ValueError("اسم الكوماند ما ينفع")
  bang = b.get("bang") is not False
  if not bang and not re.fullmatch(r"\w+", name):
    raise ValueError("الكوماند بدون ! لازم يكون حروف وأرقام بس")
  perm = b.get("perm") if b.get("perm") in PERMS else "everyone"
  reply = str(b.get("reply", "")).strip()[:450]
  if b.get("type") == "game":
    game = str(b.get("game", "")).strip()[:100]
    if not game:
      raise ValueError("اكتب اسم اللعبة")
    return name, {
        "type": "game", "game": game, "perm": perm, "bang": bang,
        "reply": reply or "تم تغيير اللعبة إلى $(game) 🎮",
    }
  if not reply:
    raise ValueError("اكتب رد الكوماند")
  return name, {"type": "text", "game": "", "perm": perm, "reply": reply, "bang": bang}


def disp_cmd(name, c):
  return ("!" if c.get("bang", True) else "") + name


def user_level(author, is_owner):
  if is_owner or author.is_broadcaster:
    return 4
  if author.is_mod:
    return 3
  badges = getattr(author, "badges", None) or {}
  if getattr(author, "is_vip", False) or "vip" in badges:
    return 2
  if getattr(author, "is_subscriber", False) or "subscriber" in badges or "founder" in badges:
    return 1
  return 0


def format_response(text, user, channel, target, game=""):
  """المتغيرات المدعومة: $(user) $(touser) $(channel) $(game)"""
  return (
      text.replace("$(user)", user)
      .replace("$(touser)", target or user)
      .replace("$(channel)", channel)
      .replace("$(game)", game)
  )


def sign(s):
  return hmac.new(b"streamer:" + SECRET, s.encode(), hashlib.sha256).hexdigest()


def make_session(login):
  p = f"{login}.{int(time.time()) + 60 * 60 * 24 * 30}"
  return f"{p}.{sign(p)}"


def read_session(tok):
  if not SECRET or not tok:
    return None
  parts = tok.split(".")
  if len(parts) != 3:
    return None
  login, exp, sig = parts
  if not hmac.compare_digest(sig.encode(), sign(f"{login}.{exp}").encode()):
    return None
  try:
    if int(exp) < time.time():
      return None
  except ValueError:
    return None
  return login


# ============================================================
# التخزين: Gist (دائم) أو ملف محلي (يتصفر مع كل إعادة تشغيل في Render)
# ============================================================
class Store:

  def __init__(self):
    self.data = {
        "channels": list(DEFAULT_CHANNELS),
        "commands": {},
        "editors": {},  # قناة -> قائمة مودات مصرّح لهم يعدلون الكوماندات
        "tokens": {},  # قناة -> ربط تويتش لتغيير اللعبة
        "banned": [],  # قنوات محظورة من استخدام البوت
    }

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
      cmds = loaded.get("commands", {})
      self.data["commands"] = {
          ch: {n: norm_cmd(v) for n, v in c.items()} for ch, c in cmds.items()
      }
      self.data["editors"] = loaded.get("editors", {})
      self.data["tokens"] = loaded.get("tokens", {})
      self.data["banned"] = loaded.get("banned", [])
      self.data["channels"] = [c for c in self.data["channels"] if c not in self.data["banned"]]
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
# Twitch API (تغيير اللعبة + تسجيل دخول الستريمرز)
# ============================================================
class TwitchAPI:

  def __init__(self, store):
    self.store = store
    self.app_token = None
    self.app_exp = 0
    self.user_access = {}  # قناة -> (access_token, وقت الانتهاء)
    self.user_ids = {}
    self.lock = asyncio.Lock()

  @property
  def enabled(self):
    return bool(CLIENT_ID and CLIENT_SECRET and SITE_URL)

  async def form(self, url, data):
    try:
      async with aiohttp.ClientSession() as s:
        async with s.post(url, data=data) as r:
          try:
            body = await r.json()
          except Exception:
            body = {}
          return r.status, body
    except Exception as e:
      print(f"خطأ اتصال بتويتش: {e}")
      return 0, {}

  async def call(self, method, path, token, params=None, body=None):
    if not token:
      return 0, {}
    headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {token}"}
    try:
      async with aiohttp.ClientSession() as s:
        async with s.request(method, HELIX + path, headers=headers,
                             params=params, json=body) as r:
          text = await r.text()
          try:
            data = json.loads(text) if text else {}
          except Exception:
            data = {}
          return r.status, data
    except Exception as e:
      print(f"خطأ Helix: {e}")
      return 0, {}

  async def get_app_token(self):
    if self.app_token and time.time() < self.app_exp - 60:
      return self.app_token
    st, d = await self.form(TOKEN_URL, {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
    })
    if st != 200 or "access_token" not in d:
      return None
    self.app_token = d["access_token"]
    self.app_exp = time.time() + d.get("expires_in", 3600)
    return self.app_token

  async def user_token(self, channel):
    cached = self.user_access.get(channel)
    if cached and time.time() < cached[1] - 60:
      return cached[0]
    info = self.store.data["tokens"].get(channel)
    if not info:
      return None
    async with self.lock:
      cached = self.user_access.get(channel)
      if cached and time.time() < cached[1] - 60:
        return cached[0]
      st, d = await self.form(TOKEN_URL, {
          "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
          "grant_type": "refresh_token", "refresh_token": info["refresh"],
      })
      if st != 200 or "access_token" not in d:
        return None
      self.user_access[channel] = (d["access_token"], time.time() + d.get("expires_in", 3600))
      if d.get("refresh_token") and d["refresh_token"] != info["refresh"]:
        info["refresh"] = d["refresh_token"]
        await self.store.save()
      return d["access_token"]

  async def user_id(self, login):
    if login in self.user_ids:
      return self.user_ids[login]
    st, d = await self.call("GET", "users", await self.get_app_token(), params={"login": login})
    if st == 200 and d.get("data"):
      self.user_ids[login] = d["data"][0]["id"]
      return self.user_ids[login]
    return None

  async def current_game(self, login):
    uid = await self.user_id(login)
    if not uid:
      return None
    st, d = await self.call("GET", "channels", await self.get_app_token(),
                            params={"broadcaster_id": uid})
    if st == 200 and d.get("data"):
      return d["data"][0].get("game_name") or None
    return None

  async def find_game(self, name):
    st, d = await self.call("GET", "search/categories", await self.get_app_token(),
                            params={"query": name, "first": 10})
    items = d.get("data", []) if st == 200 else []
    if not items:
      return None
    for g in items:
      if g["name"].lower() == name.lower():
        return g
    return items[0]

  async def set_game(self, channel, game_name):
    """يرجع (نجح؟، اسم اللعبة أو رسالة الخطأ)."""
    if not self.enabled:
      return False, "تغيير اللعبة غير مفعّل"
    info = self.store.data["tokens"].get(channel)
    if not info:
      return False, "الستريمر ما ربط تويتش من موقع الستريمر"
    token = await self.user_token(channel)
    if not token:
      return False, "انتهى الربط مع تويتش، الستريمر يعيد الربط من الموقع"
    game = await self.find_game(game_name)
    if not game:
      return False, f"ما لقيت لعبة باسم {game_name}"
    st, _ = await self.call("PATCH", "channels", token,
                            params={"broadcaster_id": info["user_id"]},
                            body={"game_id": game["id"]})
    if st == 204:
      return True, game["name"]
    return False, "تويتش رفض تغيير اللعبة، حاول مرة ثانية"


# ============================================================
# الواجهات (HTML)
# ============================================================
COMMON_CSS = r"""
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
label{display:block;font-size:13px;color:var(--mut);margin:2px 0 6px}
input,select,textarea{width:100%;background:#0e0e12;border:1px solid var(--line);color:var(--tx);border-radius:10px;padding:11px 12px;font:inherit;margin-bottom:10px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--acc);border-color:transparent}
textarea{min-height:90px;resize:vertical}
.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:11px 18px;font:inherit;font-weight:700;cursor:pointer;width:100%}
a.btn{display:block;text-align:center;text-decoration:none}
.btn.ghost{background:none;border:1px solid var(--line);color:var(--mut);width:auto;padding:8px 14px}
.btn.red{background:var(--bad)}
.btn.mt{margin-top:8px}
.row{display:flex;align-items:center;gap:10px;padding:12px 4px;border-bottom:1px solid var(--line)}
.row:last-child{border:0}
.row b{flex:1;text-align:start}
.row small{color:var(--mut)}
.row.col{flex-direction:column;align-items:stretch;gap:6px}
.row .top{display:flex;align-items:center;justify-content:space-between}
.row p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.meta{font-size:12px;color:var(--acc)}
.mut{color:var(--mut);font-size:14px}
.hint{font-size:12px;color:var(--mut);margin:-4px 0 10px}
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
"""

COMMON_JS = r"""
const $=s=>document.querySelector(s);
const PERMS={everyone:"الكل",sub:"المشتركين وفوق",vip:"VIP وفوق",mod:"المودات فقط",broadcaster:"الستريمر فقط"};
const EN={
"لوحة تحكم البوت":"Bot Control Panel","موقع الستريمر":"Streamer Site",
"كلمة المرور":"Password","دخول":"Log in","خروج":"Log out",
"القنوات":"Channels","الكوماندات":"Commands","إرسال رسالة":"Send message",
"إضافة قناة":"Add a channel","اسم القناة مثل: majek113":"Channel name, e.g. majek113",
"إضافة القناة":"Add channel","القنوات الحالية":"Current channels",
"إضافة / تعديل كوماند":"Add / edit command","نوع الكوماند":"Command type",
"💬 رد عادي":"💬 Text reply","🎮 اختصار لعبة (يغيّر لعبة البث)":"🎮 Game shortcut (changes the stream's game)",
"اسم الكوماند بدون ! مثل: fortnite":"Command name without !, e.g. fortnite",
"اسم اللعبة مثل: Fortnite":"Game name, e.g. Fortnite",
"لازم الستريمر يربط تويتش من تبويب الإعدادات في موقع الستريمر عشان تغيير اللعبة يشتغل.":"The streamer must link Twitch from the Settings tab on the streamer site for game changing to work.",
"رد البوت":"Bot reply","رد البوت بعد تغيير اللعبة (اختياري)":"Bot reply after changing the game (optional)",
"مين يقدر يستخدم الكوماند؟":"Who can use this command?",
"الكل":"Everyone","المشتركين وفوق":"Subscribers and above","VIP وفوق":"VIPs and above","المودات فقط":"Mods only","الستريمر فقط":"Streamer only",
"حفظ الكوماند":"Save command","كوماندات القناة":"Channel commands",
"إرسال رسالة كأنك البوت":"Send a message as the bot","نص الرسالة":"Message text","إرسال":"Send",
"ضغطة وحدة وتتفعّل الأمور: البوت يدخل قناتك ويرتبط تغيير اللعبة":"One click does it all: the bot joins your channel and game changing gets linked",
"أنا ستريمر: تفعيل البوت في قناتي":"I'm a streamer: activate the bot on my channel",
"أنا مود: دخول فقط":"I'm a mod: log in only",
"الموقع غير مفعّل بعد من المطوّر.":"The site hasn't been enabled by the developer yet.",
"ما عندك قنوات هنا. إذا أنت ستريمر اضغط \"أنا ستريمر\" عشان تفعّل البوت في قناتك، وإذا أنت مود خلّ الستريمر يضيفك.":"You have no channels here. If you're a streamer, press \"I'm a streamer\" to activate the bot on your channel. If you're a mod, ask the streamer to add you.",
"الإعدادات":"Settings","ربط تويتش (لكوماندات تغيير اللعبة)":"Twitch link (for game-changing commands)",
"ربط تويتش":"Link Twitch","إعادة الربط":"Relink","إلغاء الربط":"Unlink",
"المودات المصرّح لهم يعدلون الكوماندات":"Mods allowed to edit commands",
"يوزر المود في تويتش":"Mod's Twitch username","إضافة مود":"Add mod",
"المود يدخل بحسابه من نفس الموقع ويعدل الكوماندات فقط. ما يقدر يشيل البوت أو يغيّر الإعدادات.":"Mods log in with their own account on this site and can only edit commands. They can't remove the bot or change settings.",
"إزالة البوت":"Remove the bot",
"يطلع البوت من قناتك وتتوقف كل الكوماندات والردود. الربط مع تويتش ينحذف.":"The bot leaves your channel and all commands and replies stop. The Twitch link is deleted.",
"إزالة البوت من قناتي":"Remove the bot from my channel",
"البوت:":"Bot:","ما فيه قنوات":"No channels","لايف":"Live","أوفلاين":"Offline",
"ما فيه كوماندات":"No commands","🎮 يغيّر اللعبة إلى:":"🎮 Changes the game to:",
"🎮 اللعبة الحالية:":"🎮 Current game:","(مود)":"(mod)",
"الربط غير مفعّل من المطوّر.":"Linking isn't enabled by the developer.",
"✅ مربوط: كوماندات اختصار اللعبة تقدر تغيّر لعبة بثك.":"✅ Linked: game shortcut commands can change your stream's game.",
"غير مربوط: اربط تويتش عشان كوماندات تغيير اللعبة تشتغل.":"Not linked: link Twitch so game-changing commands work.",
"ما أضفت أحد للحين":"You haven't added anyone yet",
"تم حذف القناة":"Channel deleted","تمت إضافة القناة":"Channel added","تم حذف الكوماند":"Command deleted",
"تم حفظ الكوماند":"Command saved","تم الإرسال":"Sent","تم إلغاء الربط":"Unlinked",
"تم إزالة البوت":"Bot removed","تمت الإزالة":"Removed","تمت إضافة المود":"Mod added",
"تم تفعيل البوت وربط تويتش ✅":"Bot activated and Twitch linked ✅",
"تم إلغاء الدخول":"Login cancelled","فشل الدخول مع تويتش، حاول مرة ثانية":"Twitch login failed, try again",
"التفعيل الذاتي مقفل، كلم المطوّر":"Self-activation is disabled, contact the developer",
"ما وافقت على الصلاحية المطلوبة":"You didn't grant the required permission","صار خطأ":"Something went wrong",
"لوحة التحكم مقفلة: ضيف DASHBOARD_PASSWORD في Render":"The panel is locked: add DASHBOARD_PASSWORD in Render",
"كلمة المرور غلط":"Wrong password","اسم القناة غير صحيح":"Invalid channel name",
"القناة مضافة من قبل":"Channel already added","القناة مو موجودة":"Channel not found",
"اختر قناة صحيحة":"Pick a valid channel","اسم الكوماند ما ينفع":"Invalid command name",
"اكتب اسم اللعبة":"Enter the game name","اكتب رد الكوماند":"Enter the command reply",
"الكوماند مو موجود":"Command not found","اختر قناة واكتب الرسالة":"Pick a channel and write a message",
"ما عندك صلاحية":"You don't have permission","اليوزر غير صحيح":"Invalid username",
"هذا حسابك أنت":"That's your own account","المود مضاف من قبل":"Mod already added",
"حظر قناة":"Ban a channel","اسم القناة اللي تبي تحظرها":"Channel to ban","حظر القناة":"Ban channel",
"القنوات المحظورة":"Banned channels","ما فيه قنوات محظورة":"No banned channels","رفع الحظر":"Unban",
"تم حظر القناة":"Channel banned","تم رفع الحظر":"Ban lifted",
"تحظر القناة {n} من استخدام البوت؟":"Ban channel {n} from using the bot?",
"القناة محظورة من قبل":"Channel already banned","ما تقدر تحظر قناتك":"You can't ban your own channel",
"القناة محظورة، ارفع الحظر أولاً":"Channel is banned, lift the ban first",
"🚫 قناتك محظورة":"🚫 Your channel is banned",
"تم حظر قناتك من استخدام البوت. إذا تعتقد أن هذا خطأ تواصل مع المطوّر.":"Your channel has been banned from using the bot. If you think this is a mistake, contact the developer.",
"كوماندات البوت":"Bot commands","القناة غير موجودة أو البوت غير مفعّل فيها":"Channel not found or the bot isn't active there",
"أنت الستريمر أو مود؟ ادخل لوحة التحكم":"Are you the streamer or a mod? Open the control panel",
"القناة غير موجودة":"Channel doesn't exist",
"طريقة التفعيل":"How it's triggered","يبدأ بـ ! (مثل: !discord)":"Starts with ! (e.g. !discord)",
"بدون ! أو معها (مثل: discord)":"With or without ! (e.g. discord)",
"الكوماند بدون ! لازم يكون حروف وأرقام بس":"A command without ! can only use letters and numbers",
"تحذف القناة {n}؟":"Delete channel {n}?","تحذف !{n}؟":"Delete !{n}?",
"تلغي الربط مع تويتش؟":"Unlink Twitch?","متأكد تبي تشيل البوت من قناتك؟":"Are you sure you want to remove the bot from your channel?"
};
const AR={};for(const k in EN)AR[EN[k]]=k;
let LANG="ar";
try{if(localStorage.getItem("lang")==="en")LANG="en"}catch(e){}
const nz=s=>s.replace(/\s+/g," ").trim();
const t=s=>LANG==="en"&&EN[s]?EN[s]:s;
const ask=(s,v)=>confirm(t(s).replace("{n}",v));
let onAuth=()=>{},onLang=()=>{};
function walk(n){
  const map=LANG==="en"?EN:AR;
  if(n.nodeType===3){
    const raw=n.nodeValue,k=nz(raw),m=k&&map[k];
    if(m)n.nodeValue=raw.replace(raw.trim(),()=>m);
    return;
  }
  if(n.nodeType!==1||n.tagName==="SCRIPT"||n.tagName==="STYLE"||n.hasAttribute("data-nt"))return;
  for(const a of ["placeholder","title"]){
    if(n.hasAttribute(a)){const m=map[nz(n.getAttribute(a))];if(m)n.setAttribute(a,m)}
  }
  n.childNodes.forEach(walk);
}
function applyLang(){
  document.documentElement.lang=LANG;
  document.documentElement.dir=LANG==="en"?"ltr":"rtl";
  const m=(LANG==="en"?EN:AR)[nz(document.title)];if(m)document.title=m;
  walk(document.body);
  document.querySelectorAll(".langbtn").forEach(b=>b.textContent=LANG==="en"?"عربي":"EN");
  onLang();
}
function initLang(){
  document.querySelectorAll(".langbtn").forEach(b=>b.onclick=()=>{
    LANG=LANG==="en"?"ar":"en";
    try{localStorage.setItem("lang",LANG)}catch(e){}
    applyLang();
  });
  applyLang();
}
function toast(m,bad){m=t(m);const x=$("#toast");x.textContent=m;x.className="show"+(bad?" bad":"");setTimeout(()=>x.className="",2400)}
async function api(method,path,body){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  const d=await r.json().catch(()=>({}));
  if(r.status===401&&!path.endsWith("/login")){onAuth(d);throw new Error("auth")}
  if(!r.ok)throw new Error(d.error||"صار خطأ");
  return d;
}
function cmdFormSync(){
  const g=$("#ctype").value==="game";
  $("#cgame").hidden=!g;$("#gamehint").hidden=!g;
  $("#creply").placeholder=t(g?"رد البوت بعد تغيير اللعبة (اختياري)":"رد البوت");
}
function cmdFormInit(){
  $("#ctype").onchange=()=>{
    if($("#ctype").value==="game"&&$("#cperm").value==="everyone")$("#cperm").value="mod";
    cmdFormSync();
  };
  $("#chips").onclick=e=>{if(e.target.tagName==="SPAN"){const ta=$("#creply");ta.value+=e.target.textContent;ta.focus()}};
  cmdFormSync();
}
function cmdFormGet(){return{type:$("#ctype").value,bang:$("#cbang").value!=="no",name:$("#cname").value,game:$("#cgame").value,reply:$("#creply").value,perm:$("#cperm").value}}
function cmdFormClear(){
  $("#ctype").value="text";$("#cperm").value="everyone";$("#cbang").value="yes";
  $("#cname").value="";$("#cgame").value="";$("#creply").value="";cmdFormSync();
}
function cmdFormFill(n,c){
  $("#ctype").value=c.type||"text";$("#cperm").value=c.perm||"everyone";$("#cbang").value=c.bang===false?"no":"yes";
  $("#cname").value=n;$("#cgame").value=c.game||"";$("#creply").value=c.reply||"";
  cmdFormSync();window.scrollTo({top:0,behavior:"smooth"});
}
function renderCmdList(box,cmds,onDel){
  box.innerHTML="";const names=Object.keys(cmds).sort();
  if(!names.length){box.innerHTML='<p class="empty">'+t("ما فيه كوماندات")+'</p>';return}
  names.forEach(n=>{
    const c=cmds[n],d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b dir="ltr" data-nt></b><span><button class="ic ed">✏️</button><button class="ic del">🗑</button></span></div><div class="meta" data-nt></div><p data-nt></p>';
    d.querySelector("b").textContent=(c.bang===false?"":"!")+n;
    d.querySelector(".meta").textContent=(c.type==="game"?t("🎮 يغيّر اللعبة إلى:")+" "+c.game:t("💬 رد عادي"))+" • "+t(PERMS[c.perm]||"الكل");
    d.querySelector("p").textContent=c.reply||"";
    d.querySelector(".ed").onclick=()=>cmdFormFill(n,c);
    d.querySelector(".del").onclick=()=>{if(ask("تحذف !{n}؟",n))onDel(n)};
    box.appendChild(d);
  });
}
"""

CMD_FORM = r"""
<div class="card">
  <h2>إضافة / تعديل كوماند</h2>
  {{TOP}}
  <label>نوع الكوماند</label>
  <select id="ctype">
    <option value="text">💬 رد عادي</option>
    <option value="game">🎮 اختصار لعبة (يغيّر لعبة البث)</option>
  </select>
  <input id="cname" dir="ltr" placeholder="اسم الكوماند بدون ! مثل: fortnite">
  <label>طريقة التفعيل</label>
  <select id="cbang">
    <option value="yes">يبدأ بـ ! (مثل: !discord)</option>
    <option value="no">بدون ! أو معها (مثل: discord)</option>
  </select>
  <input id="cgame" dir="ltr" placeholder="اسم اللعبة مثل: Fortnite" hidden>
  <p class="hint" id="gamehint" hidden>لازم الستريمر يربط تويتش من تبويب الإعدادات في موقع الستريمر عشان تغيير اللعبة يشتغل.</p>
  <textarea id="creply" placeholder="رد البوت"></textarea>
  <div class="chips" id="chips"><span>$(user)</span><span>$(touser)</span><span>$(channel)</span><span>$(game)</span></div>
  <label>مين يقدر يستخدم الكوماند؟</label>
  <select id="cperm">
    <option value="everyone">الكل</option>
    <option value="sub">المشتركين وفوق</option>
    <option value="vip">VIP وفوق</option>
    <option value="mod">المودات فقط</option>
    <option value="broadcaster">الستريمر فقط</option>
  </select>
  <button class="btn" id="savecmd">حفظ الكوماند</button>
</div>
"""

HEAD = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0e0e12">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg">
<script>try{if(localStorage.getItem("lang")==="en"){document.documentElement.dir="ltr";document.documentElement.lang="en"}}catch(e){}</script>
<title>{{TITLE}}</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
<style>/*COMMON_CSS*/</style>
</head>
<body>
"""

# ---------------- لوحة الأونر ----------------
OWNER_HTML = HEAD.replace("{{TITLE}}", "لوحة تحكم البوت") + r"""
<div class="wrap">
<div id="login" hidden>
  <div class="card">
    <div class="logo" style="margin:0 auto 12px">🤖</div>
    <h1 style="font-size:20px;margin:0 0 16px">لوحة تحكم البوت</h1>
    <input id="pw" type="password" placeholder="كلمة المرور" autocomplete="current-password">
    <button class="btn" id="loginBtn">دخول</button>
    <button class="btn ghost langbtn" style="margin-top:10px">EN</button>
  </div>
</div>

<div id="app" hidden>
  <header>
    <div class="logo">🤖</div>
    <div><h1>لوحة تحكم البوت</h1><small id="botname"></small></div>
    <div class="sp"></div>
    <button class="btn ghost langbtn">EN</button>
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
    <div class="card">
      <h2>حظر قناة</h2>
      <input id="banch" dir="ltr" placeholder="اسم القناة اللي تبي تحظرها">
      <button class="btn red" id="banbtn">حظر القناة</button>
    </div>
    <div class="card"><h2>القنوات المحظورة</h2><div id="banlist"></div></div>
  </section>

  <section id="t-cmd" hidden>
    {{FORM}}
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
//COMMON_JS
let S={channels:[],commands:{},bot:"",banned:[]};
onAuth=()=>show(false);
onLang=()=>{if(!$("#app").hidden)render()};
function show(on){$("#login").hidden=on;$("#app").hidden=!on}
async function act(fn,msg){try{await fn();if(msg)toast(msg);await load()}catch(e){if(e.message!=="auth")toast(e.message,1)}}
async function load(){
  try{S=await api("GET","/api/state");show(true);render()}catch(e){if(e.message!=="auth")toast(e.message,1)}
}
function render(){
  $("#botname").textContent=S.bot?t("البوت:")+" "+S.bot:"";
  const list=$("#chlist");list.innerHTML="";
  if(!S.channels.length)list.innerHTML='<p class="empty">'+t("ما فيه قنوات")+'</p>';
  S.channels.forEach(c=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<span class="dot'+(c.live?" on":"")+'"></span><b dir="ltr" data-nt></b><small>'+t(c.live?"لايف":"أوفلاين")+'</small><button class="ic ban">🚫</button><button class="ic del">🗑</button>';
    d.querySelector("b").textContent=c.name;
    d.querySelector(".ban").onclick=()=>{if(ask("تحظر القناة {n} من استخدام البوت؟",c.name))act(()=>api("POST","/api/ban",{name:c.name}),"تم حظر القناة")};
    d.querySelector(".del").onclick=()=>{if(ask("تحذف القناة {n}؟",c.name))act(()=>api("DELETE","/api/channels/"+encodeURIComponent(c.name)),"تم حذف القناة")};
    list.appendChild(d);
  });
  const bl=$("#banlist");bl.innerHTML="";
  if(!S.banned.length)bl.innerHTML='<p class="empty">'+t("ما فيه قنوات محظورة")+'</p>';
  S.banned.forEach(n=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<b dir="ltr" data-nt></b><button class="btn ghost">'+t("رفع الحظر")+'</button>';
    d.querySelector("b").textContent=n;
    d.querySelector("button").onclick=()=>act(()=>api("DELETE","/api/ban/"+encodeURIComponent(n)),"تم رفع الحظر");
    bl.appendChild(d);
  });
  for(const id of ["#cmdch","#msgch"]){
    const s=$(id),v=s.value;s.innerHTML="";
    S.channels.forEach(c=>s.add(new Option(c.name,c.name)));
    if(S.channels.some(c=>c.name===v))s.value=v;
  }
  renderCmds();
}
function renderCmds(){
  const ch=$("#cmdch").value;
  renderCmdList($("#cmdlist"),S.commands[ch]||{},n=>act(()=>api("DELETE","/api/commands/"+encodeURIComponent(ch)+"/"+encodeURIComponent(n)),"تم حذف الكوماند"));
}
cmdFormInit();
$("#loginBtn").onclick=async()=>{
  try{await api("POST","/api/login",{password:$("#pw").value});$("#pw").value="";await load()}
  catch(e){toast(e.message,1)}
};
$("#pw").onkeydown=e=>{if(e.key==="Enter")$("#loginBtn").click()};
$("#logout").onclick=async()=>{await api("POST","/api/logout");show(false)};
$("#addch").onclick=()=>act(async()=>{await api("POST","/api/channels",{name:$("#newch").value});$("#newch").value=""},"تمت إضافة القناة");
$("#banbtn").onclick=()=>act(async()=>{await api("POST","/api/ban",{name:$("#banch").value});$("#banch").value=""},"تم حظر القناة");
$("#cmdch").onchange=renderCmds;
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST","/api/commands",Object.assign({channel:$("#cmdch").value},cmdFormGet()));
  cmdFormClear();
},"تم حفظ الكوماند");
$("#sendmsg").onclick=()=>act(async()=>{
  await api("POST","/api/send",{channel:$("#msgch").value,text:$("#msgtxt").value});$("#msgtxt").value="";
},"تم الإرسال");
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  for(const t of ["ch","cmd","msg"])$("#t-"+t).hidden=t!==b.dataset.t;
});
setInterval(()=>{if(!$("#app").hidden)load()},60000);
initLang();
load();
</script>
</body>
</html>
"""

# ---------------- موقع الستريمر ----------------
STREAMER_HTML = HEAD.replace("{{TITLE}}", "موقع الستريمر") + r"""
<div class="wrap">
<div id="login" hidden>
  <div class="card">
    <div class="logo" style="margin:0 auto 12px">🎮</div>
    <h1 style="font-size:20px;margin:0 0 8px">موقع الستريمر</h1>
    <p class="mut">ضغطة وحدة وتتفعّل الأمور: البوت يدخل قناتك ويرتبط تغيير اللعبة</p>
    <div id="loginbtns">
      <a class="btn" href="/auth/streamer">أنا ستريمر: تفعيل البوت في قناتي</a>
      <a class="btn ghost mt" style="display:block;width:100%;text-align:center" href="/auth/login">أنا مود: دخول فقط</a>
    </div>
    <p class="mut" id="nolink" hidden>الموقع غير مفعّل بعد من المطوّر.</p>
    <button class="btn ghost langbtn" style="margin-top:10px">EN</button>
  </div>
</div>

<div id="app" hidden>
  <header>
    <div class="logo">🎮</div>
    <div><h1>موقع الستريمر</h1><small id="who" dir="ltr"></small></div>
    <div class="sp"></div>
    <button class="btn ghost langbtn">EN</button>
    <button class="btn ghost" id="logout">خروج</button>
  </header>
  <select id="chsel" hidden></select>
  <div class="card" id="nochan" hidden>
    <p class="mut" style="margin:0">ما عندك قنوات هنا. إذا أنت ستريمر اضغط "أنا ستريمر" عشان تفعّل البوت في قناتك، وإذا أنت مود خلّ الستريمر يضيفك.</p>
  </div>

  <div class="card" id="banned" hidden>
    <h2>🚫 قناتك محظورة</h2>
    <p class="mut" style="margin:0">تم حظر قناتك من استخدام البوت. إذا تعتقد أن هذا خطأ تواصل مع المطوّر.</p>
  </div>
  <div id="main" hidden>
    <div class="card">
      <div class="row" style="padding:0;border:0">
        <span class="dot" id="dot"></span><b id="chname" dir="ltr"></b><small id="live"></small>
      </div>
      <div class="mut" id="curgame" style="margin-top:8px"></div>
    </div>

    <div class="tabs">
      <button class="on" data-t="cmd">الكوماندات</button>
      <button data-t="set" id="tabset">الإعدادات</button>
    </div>

    <section id="t-cmd">
      {{FORM}}
      <div class="card"><h2>كوماندات القناة</h2><div id="cmdlist"></div></div>
    </section>

    <section id="t-set" hidden>
      <div class="card">
        <h2>ربط تويتش (لكوماندات تغيير اللعبة)</h2>
        <p class="mut" id="linkstate"></p>
        <a class="btn" id="connect" href="/auth/connect">ربط تويتش</a>
        <button class="btn ghost mt" id="unlink" hidden>إلغاء الربط</button>
      </div>
      <div class="card">
        <h2>المودات المصرّح لهم يعدلون الكوماندات</h2>
        <input id="newed" dir="ltr" placeholder="يوزر المود في تويتش">
        <button class="btn" id="added">إضافة مود</button>
        <div id="edlist" style="margin-top:8px"></div>
        <p class="hint">المود يدخل بحسابه من نفس الموقع ويعدل الكوماندات فقط. ما يقدر يشيل البوت أو يغيّر الإعدادات.</p>
      </div>
      <div class="card">
        <h2>إزالة البوت</h2>
        <p class="mut">يطلع البوت من قناتك وتتوقف كل الكوماندات والردود. الربط مع تويتش ينحذف.</p>
        <button class="btn red" id="leave">إزالة البوت من قناتي</button>
      </div>
    </section>
  </div>
</div>
</div>
<div id="toast"></div>

<script>
//COMMON_JS
let ME=null,CH=null;
onAuth=d=>{
  $("#app").hidden=true;$("#login").hidden=false;
  if(d&&d.enabled===false){$("#loginbtns").hidden=true;$("#nolink").hidden=false}
};
function fillSel(){
  const sel=$("#chsel"),prev=sel.value;sel.innerHTML="";
  ME.channels.forEach(c=>sel.add(new Option(c.name+(c.role==="editor"?" "+t("(مود)"):""),c.name)));
  if(ME.channels.some(c=>c.name===prev))sel.value=prev;
}
onLang=()=>{if(ME)fillSel();if(CH)render();cmdFormSync()};
const base=()=>"/s/api/channel/"+encodeURIComponent(CH.name);
function tab(t){
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x.dataset.t===t));
  for(const k of ["cmd","set"])$("#t-"+k).hidden=k!==t;
}
async function act(fn,msg,reinit){
  try{await fn();if(msg)toast(msg);reinit?await init():await loadCh()}
  catch(e){if(e.message!=="auth")toast(e.message,1)}
}
async function init(){
  try{ME=await api("GET","/s/api/me")}catch(e){if(e.message!=="auth")toast(e.message,1);return}
  $("#login").hidden=true;$("#app").hidden=false;
  $("#who").textContent=ME.login;
  $("#banned").hidden=!ME.banned;
  if(ME.banned){$("#nochan").hidden=true;$("#main").hidden=true;$("#chsel").hidden=true;return}
  fillSel();
  $("#chsel").hidden=ME.channels.length<2;
  $("#nochan").hidden=ME.channels.length>0;
  $("#main").hidden=!ME.channels.length;
  if(ME.channels.length)await loadCh();
}
async function loadCh(){
  try{CH=await api("GET",base2())}catch(e){if(e.message!=="auth")toast(e.message,1);return}
  render();
}
const base2=()=>"/s/api/channel/"+encodeURIComponent($("#chsel").value);
function render(){
  const c=CH,own=c.role==="owner";
  $("#chname").textContent=c.name;
  $("#dot").className="dot"+(c.live?" on":"");
  $("#live").textContent=t(c.live?"لايف":"أوفلاين");
  $("#curgame").textContent=c.game?t("🎮 اللعبة الحالية:")+" "+c.game:"";
  $("#tabset").hidden=!own;
  if(!own&&!$("#t-set").hidden)tab("cmd");
  renderCmdList($("#cmdlist"),c.commands,n=>act(()=>api("DELETE",base()+"/commands/"+encodeURIComponent(n)),"تم حذف الكوماند"));
  if(!own)return;
  $("#linkstate").textContent=t(!c.twitch?"الربط غير مفعّل من المطوّر.":c.linked?"✅ مربوط: كوماندات اختصار اللعبة تقدر تغيّر لعبة بثك.":"غير مربوط: اربط تويتش عشان كوماندات تغيير اللعبة تشتغل.");
  $("#connect").hidden=!c.twitch;
  $("#connect").textContent=t(c.linked?"إعادة الربط":"ربط تويتش");
  $("#unlink").hidden=!c.linked;
  const box=$("#edlist");box.innerHTML="";
  if(!c.editors.length)box.innerHTML='<p class="empty">'+t("ما أضفت أحد للحين")+'</p>';
  c.editors.forEach(n=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<b dir="ltr" data-nt></b><button class="ic">🗑</button>';
    d.querySelector("b").textContent=n;
    d.querySelector("button").onclick=()=>act(()=>api("DELETE",base()+"/editors/"+encodeURIComponent(n)),"تمت الإزالة");
    box.appendChild(d);
  });
}
cmdFormInit();
$("#chsel").onchange=loadCh;
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST",base()+"/commands",cmdFormGet());cmdFormClear();
},"تم حفظ الكوماند");
$("#added").onclick=()=>act(async()=>{
  await api("POST",base()+"/editors",{name:$("#newed").value});$("#newed").value="";
},"تمت إضافة المود");
$("#unlink").onclick=()=>{if(ask("تلغي الربط مع تويتش؟"))act(()=>api("POST",base()+"/unlink"),"تم إلغاء الربط")};
$("#leave").onclick=()=>{
  if(ask("متأكد تبي تشيل البوت من قناتك؟"))act(()=>api("POST",base()+"/leave"),"تم إزالة البوت",true);
};
$("#logout").onclick=async()=>{await api("POST","/s/api/logout");onAuth({enabled:true})};
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>tab(b.dataset.t));
const qp=new URLSearchParams(location.search);
if(qp.get("msg")==="ready")toast("تم تفعيل البوت وربط تويتش ✅");
const ERR={cancel:"تم إلغاء الدخول",fail:"فشل الدخول مع تويتش، حاول مرة ثانية",not_joined:"التفعيل الذاتي مقفل، كلم المطوّر",scope:"ما وافقت على الصلاحية المطلوبة"};
if(qp.get("err"))toast(ERR[qp.get("err")]||"صار خطأ",1);
if(location.search)history.replaceState(null,"","/s");
initLang();
init();
</script>
</body>
</html>
"""

PUBLIC_HTML = HEAD.replace("{{TITLE}}", "كوماندات القناة") + r"""
<div class="wrap">
  <header>
    <div class="logo">🤖</div>
    <div><h1 id="chname" dir="ltr" data-nt></h1><small>كوماندات البوت</small></div>
    <div class="sp"></div>
    <button class="btn ghost langbtn">EN</button>
  </header>
  <div class="card" id="nf" hidden><p class="mut" style="margin:0">القناة غير موجودة أو البوت غير مفعّل فيها</p></div>
  <div class="card" id="box"><h2>كوماندات القناة</h2><div id="list"></div></div>
  <p class="hint" style="text-align:center"><a href="/s" style="color:var(--acc)">أنت الستريمر أو مود؟ ادخل لوحة التحكم</a></p>
</div>
<div id="toast"></div>
<script>
//COMMON_JS
const CHN=decodeURIComponent(location.pathname.split("/").pop()).toLowerCase();
let D=null,BAD=false;
function render(){
  $("#chname").textContent=CHN;
  $("#nf").hidden=!BAD;$("#box").hidden=BAD;
  if(!D)return;
  const box=$("#list");box.innerHTML="";
  const names=Object.keys(D.commands).sort();
  if(!names.length){box.innerHTML='<p class="empty">'+t("ما فيه كوماندات")+'</p>';return}
  names.forEach(n=>{
    const c=D.commands[n],d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b dir="ltr" data-nt></b></div><div class="meta" data-nt></div><p data-nt></p>';
    d.querySelector("b").textContent=(c.bang===false?"":"!")+n;
    d.querySelector(".meta").textContent=(c.type==="game"?t("🎮 يغيّر اللعبة إلى:")+" "+c.game:t("💬 رد عادي"))+" • "+t(PERMS[c.perm]||"الكل");
    d.querySelector("p").textContent=c.type==="game"?"":(c.reply||"");
    box.appendChild(d);
  });
}
onLang=render;
initLang();
fetch("/pub/"+encodeURIComponent(CHN)).then(r=>r.ok?r.json():Promise.reject()).then(d=>{D=d;render()}).catch(()=>{BAD=true;render()});
</script>
</body>
</html>
"""

OWNER_HTML = (OWNER_HTML.replace("{{FORM}}", CMD_FORM.replace("{{TOP}}", '<select id="cmdch"></select>'))
              .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))
STREAMER_HTML = (STREAMER_HTML.replace("{{FORM}}", CMD_FORM.replace("{{TOP}}", ""))
                 .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))
PUBLIC_HTML = PUBLIC_HTML.replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS)

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


async def jbody(request):
  try:
    data = await request.json()
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}


def is_https(request):
  return request.headers.get("X-Forwarded-Proto") == "https"


def make_web_app(bot):
  store = bot.store
  twitch = bot.twitch
  redirect_uri = SITE_URL + "/auth/callback"

  # ---------------- لوحة الأونر ----------------
  def authed(request):
    tok = request.cookies.get("session", "")
    return bool(SESSION_TOKEN) and hmac.compare_digest(tok.encode(), SESSION_TOKEN.encode())

  @web.middleware
  async def auth_mw(request, handler):
    if request.path.startswith("/api/") and request.path != "/api/login" and not authed(request):
      return jerr("unauthorized", 401)
    return await handler(request)

  async def index(request):
    return web.Response(text=OWNER_HTML, content_type="text/html")

  async def ping(request):
    return web.Response(text="Bot is alive!")

  async def manifest(request):
    return web.json_response(MANIFEST)

  async def icon(request):
    return web.Response(text=ICON_SVG, content_type="image/svg+xml")

  async def login(request):
    if not SESSION_TOKEN:
      return jerr("لوحة التحكم مقفلة: ضيف DASHBOARD_PASSWORD في Render", 503)
    body = await jbody(request)
    await asyncio.sleep(1)
    if not hmac.compare_digest(str(body.get("password", "")).encode(), DASHBOARD_PASSWORD.encode()):
      return jerr("كلمة المرور غلط", 401)
    resp = web.json_response({"ok": True})
    resp.set_cookie("session", SESSION_TOKEN, max_age=60 * 60 * 24 * 30, httponly=True,
                    samesite="Lax", secure=is_https(request))
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
        "banned": store.data["banned"],
    })

  async def add_channel(request):
    name = str((await jbody(request)).get("name", "")).strip().lstrip("@#").lower()
    if not valid_channel(name):
      return jerr("اسم القناة غير صحيح")
    if name in store.data["banned"]:
      return jerr("القناة محظورة، ارفع الحظر أولاً")
    if name in store.data["channels"]:
      return jerr("القناة مضافة من قبل")
    store.data["channels"].append(name)
    await store.save()
    await bot.join_channels([name])
    return web.json_response({"ok": True})

  async def ban_channel(request):
    name = str((await jbody(request)).get("name", "")).strip().lstrip("@#").lower()
    if not valid_channel(name):
      return jerr("اسم القناة غير صحيح")
    if name == OWNER:
      return jerr("ما تقدر تحظر قناتك")
    if name in store.data["banned"]:
      return jerr("القناة محظورة من قبل")
    store.data["banned"].append(name)
    if name in store.data["channels"]:
      store.data["channels"].remove(name)
    store.data["tokens"].pop(name, None)
    twitch.user_access.pop(name, None)
    await store.save()
    try:
      await bot.part_channels([name])
    except Exception as e:
      print(f"تعذر الخروج من {name}: {e}")
    return web.json_response({"ok": True})

  async def unban_channel(request):
    name = request.match_info["name"].lower()
    if name in store.data["banned"]:
      store.data["banned"].remove(name)
      await store.save()
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
    b = await jbody(request)
    ch = str(b.get("channel", "")).lower()
    if ch not in store.data["channels"]:
      return jerr("اختر قناة صحيحة")
    try:
      name, entry = build_command(b)
    except ValueError as e:
      return jerr(str(e))
    store.data["commands"].setdefault(ch, {})[name] = entry
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
    b = await jbody(request)
    channel = bot.get_channel(str(b.get("channel", "")).lower())
    text = str(b.get("text", "")).strip()[:490]
    if not channel or not text:
      return jerr("اختر قناة واكتب الرسالة")
    await channel.send(text)
    return web.json_response({"ok": True})

  # ---------------- موقع الستريمر ----------------
  def role_of(login, ch):
    if ch not in store.data["channels"]:
      return None
    if login == ch:
      return "owner"
    if login in store.data["editors"].get(ch, []):
      return "editor"
    return None

  def channels_for(login):
    out = []
    for ch in store.data["channels"]:
      r = role_of(login, ch)
      if r:
        out.append({"name": ch, "role": r})
    return out

  def access(request, owner_only=False):
    login = read_session(request.cookies.get("ssess", ""))
    if not login:
      return None, web.json_response({"error": "unauthorized", "enabled": twitch.enabled}, status=401)
    ch = request.match_info["channel"].lower()
    r = role_of(login, ch)
    if not r or (owner_only and r != "owner"):
      return None, jerr("ما عندك صلاحية", 403)
    return (login, ch, r), None

  async def s_index(request):
    return web.Response(text=STREAMER_HTML, content_type="text/html")

  async def auth_start(mode):
    if not twitch.enabled:
      raise web.HTTPFound("/s")
    state_val = mode + secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urlencode({
        "client_id": CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "state": state_val,
        "scope": GAME_SCOPE if mode in ("c", "s") else "",
    })
    return state_val, url

  async def auth_login(request):
    state_val, url = await auth_start("l")
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def auth_streamer(request):
    state_val, url = await auth_start("s")
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def auth_connect(request):
    state_val, url = await auth_start("c")
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def auth_callback(request):
    q = request.query
    state_val = q.get("state", "")
    cookie = request.cookies.get("ostate", "")
    if not state_val or not hmac.compare_digest(state_val.encode(), cookie.encode()):
      return web.Response(text="انتهت جلسة الدخول، ارجع للموقع وحاول مرة ثانية", status=400)
    if q.get("error") or not q.get("code"):
      raise web.HTTPFound("/s?err=cancel")
    st, tok = await twitch.form(TOKEN_URL, {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": q["code"],
        "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    })
    if st != 200 or "access_token" not in tok:
      raise web.HTTPFound("/s?err=fail")
    st, data = await twitch.call("GET", "users", tok["access_token"])
    if st != 200 or not data.get("data"):
      raise web.HTTPFound("/s?err=fail")
    user = data["data"][0]
    login_name = user["login"].lower()
    dest = "/s"
    if state_val[0] in ("c", "s") and login_name not in store.data["banned"]:
      if login_name not in store.data["channels"] and SELF_JOIN and valid_channel(login_name):
        store.data["channels"].append(login_name)
        await store.save()
        try:
          await bot.join_channels([login_name])
        except Exception as e:
          print(f"تعذر الدخول لقناة {login_name}: {e}")
      if login_name not in store.data["channels"]:
        dest = "/s?err=not_joined"
      elif GAME_SCOPE not in (tok.get("scope") or []) or not tok.get("refresh_token"):
        dest = "/s?err=scope"
      else:
        store.data["tokens"][login_name] = {"refresh": tok["refresh_token"], "user_id": user["id"]}
        twitch.user_access[login_name] = (tok["access_token"], time.time() + tok.get("expires_in", 3600))
        await store.save()
        dest = "/s?msg=ready"
    resp = web.HTTPFound(dest)
    resp.set_cookie("ssess", make_session(login_name), max_age=60 * 60 * 24 * 30,
                    httponly=True, samesite="Lax", secure=is_https(request))
    resp.del_cookie("ostate")
    raise resp

  async def c_page(request):
    login_name = read_session(request.cookies.get("ssess", ""))
    ch = request.match_info["channel"].lower()
    if login_name and role_of(login_name, ch):
      raise web.HTTPFound("/s")  # الستريمر والمودات يروحون للوحة التحكم
    return web.Response(text=PUBLIC_HTML, content_type="text/html")

  async def pub(request):
    ch = request.match_info["channel"].lower()
    if ch not in store.data["channels"]:
      return jerr("القناة غير موجودة", 404)
    return web.json_response({"name": ch, "commands": store.data["commands"].get(ch, {})})

  async def s_logout(request):
    resp = web.json_response({"ok": True})
    resp.del_cookie("ssess")
    return resp

  async def s_me(request):
    login_name = read_session(request.cookies.get("ssess", ""))
    if not login_name:
      return web.json_response({"error": "unauthorized", "enabled": twitch.enabled}, status=401)
    if login_name in store.data["banned"]:
      return web.json_response({"login": login_name, "banned": True, "channels": []})
    return web.json_response({"login": login_name, "channels": channels_for(login_name)})

  async def s_channel(request):
    a, err = access(request)
    if err:
      return err
    _, ch, role = a
    game = None
    if twitch.enabled:
      try:
        game = await twitch.current_game(ch)
      except Exception:
        game = None
    return web.json_response({
        "name": ch, "role": role,
        "live": await bot.is_channel_live(ch),
        "game": game,
        "twitch": twitch.enabled,
        "linked": ch in store.data["tokens"],
        "commands": store.data["commands"].get(ch, {}),
        "editors": store.data["editors"].get(ch, []) if role == "owner" else [],
    })

  async def s_save_cmd(request):
    a, err = access(request)
    if err:
      return err
    _, ch, _ = a
    try:
      name, entry = build_command(await jbody(request))
    except ValueError as e:
      return jerr(str(e))
    store.data["commands"].setdefault(ch, {})[name] = entry
    await store.save()
    return web.json_response({"ok": True})

  async def s_del_cmd(request):
    a, err = access(request)
    if err:
      return err
    _, ch, _ = a
    name = request.match_info["name"].lower()
    cmds = store.data["commands"].get(ch, {})
    if name not in cmds:
      return jerr("الكوماند مو موجود", 404)
    del cmds[name]
    await store.save()
    return web.json_response({"ok": True})

  async def s_add_editor(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    name = str((await jbody(request)).get("name", "")).strip().lstrip("@").lower()
    if not valid_channel(name):
      return jerr("اليوزر غير صحيح")
    if name == ch:
      return jerr("هذا حسابك أنت")
    eds = store.data["editors"].setdefault(ch, [])
    if name in eds:
      return jerr("المود مضاف من قبل")
    eds.append(name)
    await store.save()
    return web.json_response({"ok": True})

  async def s_del_editor(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    name = request.match_info["name"].lower()
    eds = store.data["editors"].get(ch, [])
    if name in eds:
      eds.remove(name)
      await store.save()
    return web.json_response({"ok": True})

  async def s_unlink(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    store.data["tokens"].pop(ch, None)
    twitch.user_access.pop(ch, None)
    await store.save()
    return web.json_response({"ok": True})

  async def s_leave(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    if ch in store.data["channels"]:
      store.data["channels"].remove(ch)
    store.data["tokens"].pop(ch, None)
    twitch.user_access.pop(ch, None)
    await store.save()
    try:
      await bot.part_channels([ch])
    except Exception as e:
      print(f"تعذر الخروج من {ch}: {e}")
    return web.json_response({"ok": True})

  app = web.Application(middlewares=[auth_mw])
  r = app.router
  r.add_get("/", index)
  r.add_get("/ping", ping)
  r.add_get("/manifest.json", manifest)
  r.add_get("/icon.svg", icon)
  r.add_post("/api/login", login)
  r.add_post("/api/logout", logout)
  r.add_get("/api/state", state)
  r.add_post("/api/channels", add_channel)
  r.add_delete("/api/channels/{name}", del_channel)
  r.add_post("/api/ban", ban_channel)
  r.add_delete("/api/ban/{name}", unban_channel)
  r.add_post("/api/commands", save_command)
  r.add_delete("/api/commands/{channel}/{name}", del_command)
  r.add_post("/api/send", send_msg)
  # موقع الستريمر
  r.add_get("/s", s_index)
  r.add_get("/auth/login", auth_login)
  r.add_get("/c/{channel}", c_page)
  r.add_get("/pub/{channel}", pub)
  r.add_get("/auth/streamer", auth_streamer)
  r.add_get("/auth/connect", auth_connect)
  r.add_get("/auth/callback", auth_callback)
  r.add_post("/s/api/logout", s_logout)
  r.add_get("/s/api/me", s_me)
  r.add_get("/s/api/channel/{channel}", s_channel)
  r.add_post("/s/api/channel/{channel}/commands", s_save_cmd)
  r.add_delete("/s/api/channel/{channel}/commands/{name}", s_del_cmd)
  r.add_post("/s/api/channel/{channel}/editors", s_add_editor)
  r.add_delete("/s/api/channel/{channel}/editors/{name}", s_del_editor)
  r.add_post("/s/api/channel/{channel}/unlink", s_unlink)
  r.add_post("/s/api/channel/{channel}/leave", s_leave)
  return app


async def start_web_server(bot):
  runner = web.AppRunner(make_web_app(bot))
  await runner.setup()
  port = int(os.environ.get("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


# ============================================================
# البوت
# ============================================================
class Bot(commands.Bot):

  def __init__(self):
    super().__init__(token=ACCESS_TOKEN, prefix="!", initial_channels=[OWNER])
    self.store = Store()
    self.twitch = TwitchAPI(self.store)
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
    to_join = [c for c in self.store.data["channels"] if c != OWNER and c not in self.store.data["banned"]]
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
                           is_owner, level):
    parts = content.split(maxsplit=2)
    cmd = parts[0][1:].lower()
    if not cmd:
      return False

    is_mod = level >= PERMS["mod"]
    send = message.channel.send
    mention = f"@{message.author.name}"
    channel_cmds = self.store.data["commands"].setdefault(channel_name, {})

    # ---------- !commands: رابط صفحة الكوماندات للجميع ----------
    if cmd == "commands":
      ckey = (channel_name, "!commands")
      now = time.time()
      if now - self.cmd_cooldown.get(ckey, 0) < 10:
        return True
      self.cmd_cooldown[ckey] = now
      if SITE_URL:
        await send(f"{mention} كل كوماندات القناة هنا: {SITE_URL}/c/{channel_name}")
      else:
        usable = [n for n, c in channel_cmds.items() if level >= PERMS[c["perm"]]]
        names = " ".join(disp_cmd(n, channel_cmds[n]) for n in sorted(usable)) or "ما فيه كوماندات مضافة للحين"
        await send(f"{mention} الكوماندات: {names}"[:480])
      return True

    # ---------- كوماندات المودرز ----------
    if cmd in ("addcmd", "editcmd", "delcmd", "removecmd", "cmds"):
      if cmd == "cmds":
        usable = [n for n, c in channel_cmds.items() if level >= PERMS[c["perm"]]]
        if not usable:
          await send(f"{mention} ما فيه كوماندات مضافة للحين")
        else:
          names = " ".join(disp_cmd(n, channel_cmds[n]) for n in sorted(usable))
          await send(f"{mention} الكوماندات: {names}"[:480])
        return True

      if not is_mod:
        return True

      if cmd in ("delcmd", "removecmd"):
        if len(parts) < 2:
          await send(f"{mention} الصيغة: !delcmd !اسم_الكوماند")
          return True
        name = parts[1].lstrip("!").lower()
        if name in channel_cmds:
          shown = disp_cmd(name, channel_cmds[name])
          del channel_cmds[name]
          await self.store.save()
          await send(f"{mention} تم حذف الكوماند {shown} ✅")
        else:
          await send(f"{mention} ما لقيت كوماند باسم {parts[1]}")
        return True

      # addcmd / editcmd
      if len(parts) < 3:
        await send(f"{mention} الصيغة: !{cmd} اسم_الكوماند الرد (حط ! قبل الاسم إذا تبيه يشتغل بـ !)")
        return True
      bang = parts[1].startswith("!")
      name = parts[1].lstrip("!").lower()
      reply = parts[2].strip()[:450]
      if not name or len(name) > 30 or name in BUILTIN:
        await send(f"{mention} هذا الاسم ما ينفع للكوماند")
        return True
      if not bang and not re.fullmatch(r"\w+", name):
        await send(f"{mention} الكوماند بدون ! لازم يكون حروف وأرقام بس")
        return True

      if cmd == "addcmd":
        if name in channel_cmds:
          await send(f"{mention} الكوماند {disp_cmd(name, channel_cmds[name])} موجود، استخدم !editcmd للتعديل")
          return True
        channel_cmds[name] = norm_cmd(reply)
        channel_cmds[name]["bang"] = bang
        await self.store.save()
        await send(f"{mention} تمت إضافة الكوماند {disp_cmd(name, channel_cmds[name])} ✅")
      else:
        if name not in channel_cmds:
          await send(f"{mention} ما لقيت {parts[1]}، استخدم !addcmd للإضافة")
          return True
        channel_cmds[name]["reply"] = reply
        await self.store.save()
        await send(f"{mention} تم تعديل الكوماند {disp_cmd(name, channel_cmds[name])} ✅")
      return True

    # ---------- !addgame: اختصار يغيّر كاتيقوري البث ----------
    # مثال: !addgame !f fortnite  ← بعدها !f يغيّر الكاتيقوري إلى Fortnite
    # أي لعبة أو كاتيقوري موجود في تويتش تنفع (Just Chatting, Valorant, ...)
    if cmd == "addgame":
      if not is_mod:
        return True
      if len(parts) < 3:
        await send(f"{mention} الصيغة: !addgame !اسم_الكوماند اسم_اللعبة  مثال: !addgame !f fortnite")
        return True
      if not self.twitch.enabled:
        await send(f"{mention} تغيير اللعبة غير مفعّل من المطوّر")
        return True
      raw_name = parts[1]
      bang = raw_name.startswith("!")
      key_name = raw_name.lstrip("!").lower()
      existing = channel_cmds.get(key_name)
      if existing and existing.get("type") != "game":
        await send(f"{mention} {disp_cmd(key_name, existing)} كوماند عادي موجود، احذفه أول بـ !delcmd")
        return True
      query = parts[2].strip()
      game = await self.twitch.find_game(query)
      if not game:
        await send(f"{mention} ما لقيت لعبة أو كاتيقوري باسم {query} في تويتش")
        return True
      try:
        name, entry = build_command({
            "type": "game", "name": raw_name, "bang": bang,
            "game": game["name"], "perm": "mod",
        })
      except ValueError as e:
        await send(f"{mention} {e}")
        return True
      updated = existing is not None
      if updated:
        entry["perm"] = existing.get("perm", "mod")
        entry["reply"] = existing.get("reply") or entry["reply"]
      channel_cmds[name] = entry
      await self.store.save()
      verb = "تم تعديل" if updated else "تمت إضافة"
      text = f"{mention} {verb} الكوماند {disp_cmd(name, entry)} ← {game['name']} 🎮"
      if channel_name not in self.store.data["tokens"]:
        text += " ⚠️ الستريمر لازم يربط تويتش من الموقع عشان يشتغل"
      await send(text[:490])
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
        if target in self.store.data["banned"]:
          await send(f"{mention} القناة {target} محظورة، ارفع الحظر من اللوحة")
          return True
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
    entry = channel_cmds.get(cmd)
    if entry is None:
      return False
    return await self.run_custom(message, cmd, entry, parts, channel_name, level)

  async def handle_plain(self, message, content, channel_name, level):
    """كوماندات بدون !: أول كلمة في الرسالة تطابق اسم الكوماند."""
    parts = content.split(maxsplit=2)
    if not parts:
      return False
    word = re.sub(r"^\W+|\W+$", "", parts[0].lower())
    if not word:
      return False
    entry = self.store.data["commands"].get(channel_name, {}).get(word)
    if entry is None or entry.get("bang", True):
      return False
    parts[0] = word
    return await self.run_custom(message, word, entry, parts, channel_name, level)

  async def run_custom(self, message, cmd, entry, parts, channel_name, level):
    send = message.channel.send
    mention = f"@{message.author.name}"

    # الصلاحية: اللي ما يملكها ما يرد عليه البوت
    if level < PERMS[entry["perm"]]:
      return True

    key = (channel_name, cmd)
    now = time.time()

    target = parts[1].lstrip("@") if len(parts) > 1 else ""

    # اختصار لعبة: يشتغل حتى لو القناة أوفلاين
    if entry["type"] == "game":
      if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
        return True
      self.cmd_cooldown[key] = now
      ok, result = await self.twitch.set_game(channel_name, entry["game"])
      if ok:
        text = format_response(entry["reply"], message.author.name, channel_name, target, result)
        await send(text[:490])
      else:
        await send(f"{mention} {result}"[:490])
      return True

    # الكوماندات العادية ما ترد إلا إذا القناة لايف
    if not await self.is_channel_live(channel_name):
      return True

    if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
      return True
    self.cmd_cooldown[key] = now

    await send(format_response(entry["reply"], message.author.name, channel_name, target)[:490])
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
    if channel_name in self.store.data["banned"]:
      return
    is_owner = username == OWNER
    level = user_level(message.author, is_owner)

    # الكوماندات تشتغل حتى للأونر
    if content.startswith("!"):
      if await self.handle_command(
          message, content, username, channel_name, is_owner, level
      ):
        return
    elif await self.handle_plain(message, content, channel_name, level):
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
