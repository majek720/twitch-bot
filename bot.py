import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sys
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

# يخلي اللوقز تطلع فوراً في Render (بدون ما تنحبس في الذاكرة)
try:
  sys.stdout.reconfigure(line_buffering=True)
except Exception:
  pass

# تثبيت الـ Event Loop لبيئة Render
asyncio.set_event_loop(asyncio.new_event_loop())

# ============================================================
# الإعدادات (الأسرار تنحط في Environment Variables في Render)
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # اختياري: لحفظ البيانات بشكل دائم
GIST_ID = os.environ.get("GIST_ID")  # اختياري: معرف الـ Gist
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")  # لوحة الأونر

CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
SITE_URL = (os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
SELF_JOIN = os.environ.get("SELF_JOIN", "1") != "0"
SECRET = (os.environ.get("SESSION_SECRET") or CLIENT_SECRET or "").encode()

OWNER = "majek113"
IGNORED_USERS = set()
DEFAULT_CHANNELS = ["majek113", "teamiik", "iz0yi", "vul1_", "lyorll"]

KNOWN_BOTS = {
    "nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "wizebot",
    "soundalerts", "pretzelrocks", "commanderroot", "anotherttvviewer",
    "blerp", "botrix", "sery_bot", "coebot", "deepbot", "ankhbot", "stay_hydrated_bot",
}

DATA_FILE = "bot_data.json"
USER_COOLDOWN = 15
COMMAND_COOLDOWN = 5
LIVE_CACHE_SECONDS = 60

SEND_MIN_GAP = 1.2
SEND_WINDOW = 30
SEND_MAX_PER_WINDOW = 15
SEND_QUEUE_MAX = 15
SEND_STALE = 45

IRC_TOKEN = (os.environ.get("TWITCH_TOKEN") or "").strip()
IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697
IRC_SSL = True

AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix/"
GAME_SCOPE = "channel:manage:broadcast"

BOT_LOGIN = (os.environ.get("BOT_LOGIN") or "majek_bot").strip().lower()
MOD_SCOPE = "channel:manage:moderators"
CHANNEL_BOT_SCOPE = "channel:bot"
EVENTSUB_SECRET = hashlib.sha256(b"eventsub:" + SECRET).hexdigest()

SCOPES = {
    "s": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE}",
    "c": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE}",
    "b": "user:bot user:read:chat user:write:chat",
    "cb": "user:bot user:read:chat user:write:chat",  # حساب بوت مخصص للستريمر
}

PERMS = {"everyone": 0, "sub": 1, "vip": 2, "mod": 3, "broadcaster": 4}

BUILTIN = {
    "addcmd", "editcmd", "delcmd", "removecmd", "cmds", "addgame", "settitle",
    "addchannel", "removechannel", "channels", "commands", "reminders",
}

DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وححسن عبادتك",
]

SAUDI_PRAYERS = [
    "اللهم احفظ المملكة العربية السعودية وبارك في أمنها ورخائها وولاة أمرها وشعبها",
    "اللهم أدِم على السعودية أمنها وأمانها واحفظها من كل شر وسوء",
    "اللهم اجعل هذا البلد آمناً مطمئناً وسائر بلاد المسلمين واحفظ وطننا السعودية",
    "اللهم احفظ خادم الحرمين الشريفين وولي عهده الأمين وبارك في جهودهما لخدمة الوطن",
    "اللهم إنا استودعناك السعودية أمنها وأرضها وسمائها وسلامة أهلها",
    "اللهم انصر قواتنا المرابطة واحفظ حدودنا وجد ليالينا بالأمن والأمان يا رب العالمين",
]

DEFAULT_AUTO_REPLIES = {
    "salam_evening": {
        "enabled": True,
        "text": "$(user) وعليكم السلام ورحمة الله وبركاته، ومساء النور نورت البث",
    },
    "salam": {
        "enabled": True,
        "text": "$(user) وعليكم السلام ورحمة الله وبركاته، نورت البث",
    },
    "evening": {
        "enabled": True,
        "text": "$(user) مساء النور",
    },
    "back": {
        "enabled": True,
        "text": "$(user) ولكم باك",
    },
    "brb": {
        "enabled": True,
        "text": "$(user) خذ راحتك بس لا تطول علينا",
    },
}

DEFAULT_REMINDER_CFG = {
    "interval": 30,
    "saudi": True,
    "dhikr": True,
    "water": True,
    "water_text": "اشربوا ماااااااي",
}

user_reply_time = {}

MSG = {
    "no_cmds": ("ما فيه كوماندات مضافة للحين", "No commands have been added yet"),
    "cmds_list": ("الكوماندات: {n}", "Commands: {n}"),
    "cmds_link": ("كل كوماندات القناة هنا: {u}", "All channel commands are here: {u}"),
    "usage_del": ("الصيغة: !delcmd !اسم_الكوماند", "Usage: !delcmd !command_name"),
    "deleted": ("تم حذف الكوماند {c} بنجاح ✅", "The command {c} has been deleted successfully"),
    "del_nf": ("ما لقيت كوماند باسم {c}", "I couldn't find a command named {c}"),
    "usage_add": (
        "الصيغة: !{cmd} اسم_الكوماند الرد (حط ! قبل الاسم إذا تبيه يشتغل بـ !)",
        "Usage: !{cmd} command_name reply (put ! before the name to trigger it with !)"),
    "bad_name": ("هذا الاسم ما ينفع للكوماند", "That command name isn't allowed"),
    "bad_plain": ("الكوماند بدون ! لازم يكون حروف وأرقام بس",
                  "A command without ! can only use letters and numbers"),
    "exists": ("الكوماند {c} موجود، استخدم !editcmd للتعديل",
               "The command {c} already exists, use !editcmd to edit it"),
    "added": ("تمت إضافة الكوماند {c} بنجاح ✅", "The command {c} has been added successfully"),
    "edited": ("تم تعديل الكوماند {c} بنجاح ✅", "The command {c} has been edited successfully"),
    "edit_nf": ("ما لقيت {c}، استخدم !addcmd للإضافة", "I couldn't find {c}, use !addcmd to add it"),
    "usage_game": ("الصيغة: !addgame !اسم_الكوماند اسم_اللعبة  مثال: !addgame !f fortnite",
                   "Usage: !addgame !command_name game_name (e.g. !addgame !f fortnite)"),
    "game_off": ("تغيير اللعبة غير مفعّل من المطوّر", "Game changing isn't enabled by the developer"),
    "game_is_text": ("{c} كوماند عادي موجود، احذفه أول بـ !delcmd",
                     "{c} is an existing text command, delete it first with !delcmd"),
    "game_nf": ("ما لقيت لعبة أو كاتيقوري باسم {q} في تويتش",
                "I couldn't find a game or category named {q} on Twitch"),
    "g_added": ("تمت إضافة اختصار اللعبة {c} ({g}) بنجاح 🎮",
                "The game command {c} has been added successfully ({g}) 🎮"),
    "g_edited": ("تم تعديل اختصار اللعبة {c} ({g}) بنجاح 🎮",
                 "The game command {c} has been edited successfully ({g}) 🎮"),
    "link_warn": (" ⚠️ الستريمر لازم يربط تويتش من الموقع عشان يشتغل",
                  " ⚠️ The streamer must link Twitch from the site for this to work"),
    "title_usage": ("الصيغة: !settitle العنوان الجديد", "Usage: !settitle new title"),
    "title_ok": ("تم تغيير عنوان البث إلى: {t} ✅", "The stream title has been changed to: {t}"),
    "e_disabled": ("تغيير اللعبة والعنوان غير مفعّل من المطوّر",
                   "Changing the game and title isn't enabled by the developer"),
    "e_not_linked": ("الستريمر ما ربط تويتش من موقع الستريمر",
                     "The streamer hasn't linked Twitch on the streamer site"),
    "e_expired": ("انتهى الربط مع تويتش، الستريمر يعيد الربط من الموقع",
                  "The Twitch link expired, the streamer needs to relink on the site"),
    "e_not_found": ("ما لقيت لعبة باسم {q}", "I couldn't find a game named {q}"),
    "e_refused": ("تويتش رفض التغيير، حاول مرة ثانية", "Twitch refused the change, try again"),
    "bot_info": ("ماجيك بوت: كوماندات مخصصة وتغيير اللعبة والعنوان من الشات. فعّله لقناتك: {u}",
                 "Majek Bot: custom commands and game/title changes from chat. Add it to your channel: {u}"),
    "rem_usage": ("الصيغة: !reminders on أو !reminders off",
                  "Usage: !reminders on or !reminders off"),
    "rem_on": ("تم تفعيل الرسائل الدورية ✅", "Periodic messages are now on"),
    "rem_off": ("تم إيقاف الرسائل الدورية ✅", "Periodic messages are now off"),
}


# ============================================================
# أدوات مساعدة
# ============================================================
def valid_channel(name):
  return re.fullmatch(r"[a-z0-9_]{3,25}", name) is not None


def norm_cmd(v):
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
# التخزين
# ============================================================
class Store:

  def __init__(self):
    self.data = {
        "channels": list(DEFAULT_CHANNELS),
        "commands": {},
        "editors": {},
        "tokens": {},
        "custom_bots": {},      # قناة -> {"login": str, "user_id": str}
        "banned": [],
        "lang": {},
        "reminders": {c: True for c in DEFAULT_CHANNELS},
        "reminder_cfg": {},
        "custom_timers": {},
        "auto_replies": {},
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

  def get_auto_replies(self, ch):
    saved = self.data.setdefault("auto_replies", {}).get(ch, {})
    out = {}
    for k, default_val in DEFAULT_AUTO_REPLIES.items():
      item = saved.get(k)
      if isinstance(item, dict):
        out[k] = {
            "enabled": bool(item.get("enabled", default_val["enabled"])),
            "text": str(item.get("text") or default_val["text"])[:450],
        }
      else:
        out[k] = dict(default_val)
    return out

  def get_reminder_cfg(self, ch):
    saved = self.data.setdefault("reminder_cfg", {}).get(ch, {})
    cfg = dict(DEFAULT_REMINDER_CFG)
    if isinstance(saved, dict):
      try:
        iv = int(saved.get("interval", 30))
        cfg["interval"] = max(1, min(180, iv))
      except Exception:
        pass
      cfg["saudi"] = bool(saved.get("saudi", True))
      cfg["dhikr"] = bool(saved.get("dhikr", True))
      cfg["water"] = bool(saved.get("water", True))
      wt = str(saved.get("water_text", "")).strip()
      if wt:
        cfg["water_text"] = wt[:450]
    return cfg

  def get_custom_timers(self, ch):
    timers = self.data.setdefault("custom_timers", {}).get(ch, [])
    return timers if isinstance(timers, list) else []

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
      self.data["custom_bots"] = loaded.get("custom_bots", {})
      self.data["banned"] = loaded.get("banned", [])
      self.data["lang"] = loaded.get("lang", {})
      self.data["reminder_cfg"] = loaded.get("reminder_cfg", {})
      self.data["custom_timers"] = loaded.get("custom_timers", {})
      self.data["auto_replies"] = loaded.get("auto_replies", {})
      if "reminders" in loaded:
        self.data["reminders"] = loaded["reminders"]
      else:
        self.data["reminders"] = {c: True for c in self.data["channels"]}
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
# Twitch API
# ============================================================
class TwitchAPI:

  def __init__(self, store):
    self.store = store
    self.app_token = None
    self.app_exp = 0
    self.user_access = {}
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

  async def channel_info(self, login):
    uid = await self.user_id(login)
    if not uid:
      return None, None
    st, d = await self.call("GET", "channels", await self.get_app_token(),
                            params={"broadcaster_id": uid})
    if st == 200 and d.get("data"):
      x = d["data"][0]
      return (x.get("game_name") or None), (x.get("title") or None)
    return None, None

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

  async def _patch_channel(self, channel, body):
    if not self.enabled:
      return False, "disabled"
    info = self.store.data["tokens"].get(channel)
    if not info:
      return False, "not_linked"
    token = await self.user_token(channel)
    if not token:
      return False, "expired"
    st, _ = await self.call("PATCH", "channels", token,
                            params={"broadcaster_id": info["user_id"]}, body=body)
    if st == 204:
      return True, ""
    if st in (401, 403):
      return False, "expired"
    return False, "refused"

  async def set_game(self, channel, game_name):
    if not self.enabled:
      return False, "disabled"
    if channel not in self.store.data["tokens"]:
      return False, "not_linked"
    game = await self.find_game(game_name)
    if not game:
      return False, "not_found"
    ok, err = await self._patch_channel(channel, {"game_id": game["id"]})
    return (True, game["name"]) if ok else (False, err)

  async def set_title(self, channel, title):
    title = title.strip()[:140]
    ok, err = await self._patch_channel(channel, {"title": title})
    return (True, title) if ok else (False, err)

  async def is_live(self, login):
    if not self.enabled:
      return False
    st, d = await self.call("GET", "streams", await self.get_app_token(),
                            params={"user_login": login})
    return st == 200 and bool(d.get("data"))

  def bot_for(self, channel):
    """يرجع (bot_login, bot_user_id) الخاص بالقناة (المخصص إن وجد أو الافتراضي)."""
    cb = self.store.data.get("custom_bots", {}).get(channel)
    if isinstance(cb, dict) and cb.get("login") and cb.get("user_id"):
      return cb["login"].lower(), str(cb["user_id"])
    return BOT_LOGIN, None

  async def chat_send(self, channel, text):
    if not self.enabled:
      return False, "disabled"
    token = await self.get_app_token()
    bid = await self.user_id(channel)
    bot_login, sid = self.bot_for(channel)
    if not sid:
      sid = await self.user_id(bot_login)
    if not (token and bid and sid):
      return False, "ids"
    st, d = await self.call("POST", "chat/messages", token, body={
        "broadcaster_id": bid, "sender_id": sid, "message": text[:490]})
    if st == 401:
      self.app_token = None
    if st == 200 and d.get("data") and d["data"][0].get("is_sent"):
      return True, ""
    drop = ""
    if st == 200 and d.get("data"):
      drop = str((d["data"][0].get("drop_reason") or {}).get("message", ""))
    return False, f"{st} {d.get('message') or drop or d.get('data')}"

  async def subscribe_chat(self, channel):
    if not self.enabled:
      return False, "disabled"
    token = await self.get_app_token()
    bid = await self.user_id(channel)
    bot_login, sid = self.bot_for(channel)
    if not sid:
      sid = await self.user_id(bot_login)
    if not (token and bid and sid):
      return False, "ids"
    st, d = await self.call("POST", "eventsub/subscriptions", token, body={
        "type": "channel.chat.message", "version": "1",
        "condition": {"broadcaster_user_id": bid, "user_id": sid},
        "transport": {"method": "webhook", "callback": SITE_URL + "/eventsub",
                      "secret": EVENTSUB_SECRET},
    })
    if st == 401:
      self.app_token = None
    if st in (202, 409):
      return True, ""
    return False, f"{st} {d.get('message', '')}"

  async def list_subs(self):
    token = await self.get_app_token()
    out, cursor = [], None
    while token:
      params = {"type": "channel.chat.message"}
      if cursor:
        params["after"] = cursor
      st, d = await self.call("GET", "eventsub/subscriptions", token, params=params)
      if st != 200:
        break
      out += d.get("data", [])
      cursor = (d.get("pagination") or {}).get("cursor")
      if not cursor:
        break
    return out

  async def drop_sub(self, sub_id):
    await self.call("DELETE", "eventsub/subscriptions",
                    await self.get_app_token(), params={"id": sub_id})

  async def unsubscribe_chat(self, channel):
    bid = await self.user_id(channel)
    for s in await self.list_subs():
      if (s.get("condition") or {}).get("broadcaster_user_id") == bid:
        await self.drop_sub(s["id"])

  async def make_bot_mod(self, channel, bot_login):
    if channel == bot_login:
      return True
    info = self.store.data["tokens"].get(channel)
    if not info:
      return False
    token = await self.user_token(channel)
    bot_id = await self.user_id(bot_login)
    if not token or not bot_id:
      return False
    st, _ = await self.call(
        "POST", "moderation/moderators", token,
        params={"broadcaster_id": info["user_id"], "user_id": bot_id})
    return st in (204, 400)


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
.bd{font-size:11px;padding:3px 10px;border-radius:20px;background:#1c2438;color:var(--mut);white-space:nowrap}
.bc{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:11px 0;border-bottom:1px solid var(--line)}
.bc:last-child{border:0}
.bc code{color:#c4a1ff;background:#1a1530;padding:5px 10px;border-radius:8px;font-size:13px;direction:ltr;unicode-bidi:plaintext;word-break:break-word;max-width:100%}
.bc .d{flex:1;color:var(--mut);font-size:13px;min-width:140px}
#toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);background:var(--ok);color:#000;padding:11px 20px;border-radius:12px;font-weight:700;transition:.25s;opacity:0;z-index:99}
#toast.show{transform:translate(-50%,0);opacity:1}#toast.bad{background:var(--bad);color:#fff}
#login{min-height:80vh;display:grid;place-items:center}
#login .card{width:100%;max-width:360px;text-align:center}
"""

COMMON_JS = r"""
const $=s=>document.querySelector(s);
const PERMS={everyone:"الكل",sub:"المشتركين وفوق",vip:"VIP وفوق",mod:"المودات فقط",broadcaster:"الستريمر فقط"};
const BASIC=[
 {c:"السلام عليكم / سلام",ce:"Salam / Hello",ar:"رد تلقائي عند كتابة السلام",en:"Auto reply when typing salam",p:"everyone"},
 {c:"مساء الخير",ce:"Good evening",ar:"رد تلقائي عند قول مساء الخير",en:"Auto reply for evening greeting",p:"everyone"},
 {c:"باك",ce:"Back",ar:"رد تلقائي عند العودة (باك)",en:"Auto reply when returning",p:"everyone"},
 {c:"برب / brb",ce:"BRB",ar:"رد تلقائي عند الذهاب مؤقتاً",en:"Auto reply when going away",p:"everyone"},
 {c:"!reminders on/off",ce:"!reminders on/off",ar:"تشغيل أو إيقاف الأذكار والأدعية والماء",en:"Toggle automatic reminders",p:"mod"},
 {c:"!addcmd !hi أهلاً $(user)",ce:"!addcmd !hi Hello $(user)",ar:"إضافة كوماند رد",en:"Add a text command",p:"mod"},
 {c:"!editcmd !hi مرحباً $(user)",ce:"!editcmd !hi Welcome $(user)",ar:"تعديل رد كوماند موجود",en:"Edit an existing command's reply",p:"mod"},
 {c:"!delcmd !hi",ce:"!delcmd !hi",ar:"حذف كوماند",en:"Delete a command",p:"mod"},
 {c:"!addgame !f fortnite",ce:"!addgame !f fortnite",ar:"إنشاء اختصار يغيّر لعبة البث",en:"Create a shortcut that changes the stream's game",p:"mod"},
 {c:"!settitle عنوان البث الجديد",ce:"!settitle New stream title",ar:"تغيير عنوان البث",en:"Change the stream title",p:"mod"},
 {c:"!commands",ce:"!commands",ar:"رابط صفحة كل الكوماندات",en:"Link to the page with all commands",p:"everyone"}
];
function copyText(s){
  try{navigator.clipboard.writeText(s).then(()=>toast("تم النسخ"),()=>{})}catch(e){}
}
function renderBasic(box){
  if(!box)return;
  box.innerHTML="";
  BASIC.forEach(b=>{
    const en=LANG==="en",txt=en?b.ce:b.c,d=document.createElement("div");d.className="bc";
    d.innerHTML='<code data-nt></code><span class="d" data-nt></span><span class="bd" data-nt></span><button class="ic" data-nt>📋</button>';
    d.querySelector("code").textContent=txt;
    d.querySelector(".d").textContent=en?b.en:b.ar;
    d.querySelector(".bd").textContent=t(PERMS[b.p]);
    const btn=d.querySelector("button");btn.title=t("نسخ");btn.onclick=()=>copyText(txt);
    box.appendChild(d);
  });
}
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
"الإعدادات":"Settings","ربط تويتش (لتغيير اللعبة والعنوان)":"Twitch link (to change the game and title)",
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
"تحظر القناة {n} استخدام البوت؟":"Ban channel {n} from using the bot?",
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
"تلغي الربط مع تويتش؟":"Unlink Twitch?","متأكد تبي تشيل البوت من قناتك؟":"Are you sure you want to remove the bot from your channel?",
"تم النسخ":"Copied","نسخ":"Copy","اضغط للنسخ":"Click to copy","كوماند":"commands",
"الأساسية":"Basics","كوماندات البوت الأساسية":"Core bot commands","كوماندات الشات الأساسية":"Core chat commands",
"للستريمر والمودات. اضغط 📋 للنسخ":"For the streamer and mods. Press 📋 to copy",
"كل الأنواع":"All types","ردود":"Replies","ألعاب":"Games","بحث في الكوماندات":"Search commands",
"ما فيه كوماندات تطابق بحثك":"No commands match your search",
"عنوان البث":"Stream title","العنوان الجديد":"New title","تغيير العنوان":"Change title",
"📝 العنوان الحالي:":"📝 Current title:","تم تغيير عنوان البث":"Stream title changed","اكتب العنوان":"Enter the title",
"يحتاج ربط تويتش من الإعدادات عشان يشتغل":"Needs a Twitch link from Settings to work",
"لغة ردود البوت":"Bot reply language","تم تغيير لغة ردود البوت":"Bot reply language changed",
"تتحكم في لغة رسائل الكوماندات الأساسية (إضافة، تعديل، حذف، اللعبة، العنوان)":"Controls the language of the core command messages (add, edit, delete, game, title)",
"تغيير اللعبة والعنوان غير مفعّل من المطوّر":"Changing the game and title isn't enabled by the developer",
"الستريمر ما ربط تويتش من موقع الستريمر":"The streamer hasn't linked Twitch on the streamer site",
"انتهى الربط مع تويتش، الستريمر يعيد الربط من الموقع":"The Twitch link expired, the streamer needs to relink on the site",
"تويتش رفض التغيير، حاول مرة ثانية":"Twitch refused the change, try again"
};
const AR={};for(const k in EN)AR[EN[k]]=k;
let LANG="ar";
try{if(localStorage.getItem("lang")==="en")LANG="en"}catch(e){}
const nz=s=>s.replace(/\s+/g," ").trim();
const t=s=>LANG==="en"&&EN[s]?EN[s]:s;
const ask=(s,v)=>confirm(t(s).replace("{n}",v));
let onAuth=() => {},onLang=() => {};
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
    <button data-t="basic">الأساسية</button>
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

  <section id="t-basic" hidden>
    <div class="card">
      <h2>كوماندات البوت الأساسية</h2>
      <p class="hint">للستريمر والمودات. اضغط 📋 للنسخ</p>
      <div id="basiclist"></div>
    </div>
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
    d.querySelector(".ban").onclick=()=>{if(ask("تحظر القناة {n} استخدام البوت؟",c.name))act(()=>api("POST","/api/ban",{name:c.name}),"تم حظر القناة")};
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
  renderBasic($("#basiclist"));
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
  for(const t of ["ch","cmd","msg","basic"])$("#t-"+t).hidden=t!==b.dataset.t;
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
<style>
body{background:#0a0e17}
.shell{display:flex;min-height:100vh}
aside{width:250px;background:#0d1220;border-inline-end:1px solid #1c2438;display:flex;flex-direction:column;padding:16px 12px;position:sticky;top:0;height:100vh;flex-shrink:0}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;padding:4px 8px 14px}
.brand .logo{width:36px;height:36px;font-size:18px}
aside select{margin:0 0 14px}
.sec{font-size:11px;color:#5d6785;letter-spacing:.08em;padding:10px 12px 6px}
.nav a{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;color:var(--mut);cursor:pointer;font-weight:500;margin-bottom:2px;border-inline-start:3px solid transparent}
.nav a:hover{background:#151c2e;color:var(--tx)}
.nav a.on{background:linear-gradient(90deg,rgba(145,70,255,.22),rgba(145,70,255,.04));color:#fff;border-inline-start-color:var(--acc)}
.nav i{font-style:normal;width:22px;text-align:center}
.me{margin-top:auto;border-top:1px solid #1c2438;padding-top:12px}
.meinfo{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.mav{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-weight:700}
.meinfo b{display:block;font-size:14px}
.mebtns{display:flex;gap:8px}
.mebtns .btn{flex:1;text-align:center}
main{flex:1;min-width:0}
.top{display:flex;align-items:center;gap:12px;padding:14px 24px;border-bottom:1px solid #1c2438;position:sticky;top:0;background:rgba(10,14,23,.88);backdrop-filter:blur(8px);z-index:5}
.top h1{font-size:18px;margin:0;flex:1}
.burger{display:none;width:auto!important;padding:8px 12px!important}
.content{max-width:1080px;margin:0 auto;padding:24px}
.panel,.stat,.hero,.cmd{background:#111827;border:1px solid #1c2438;border-radius:16px}
.panel{padding:18px}
.panel h3{margin:0 0 4px;font-size:15px}
.hero{padding:28px 20px;text-align:center;margin-bottom:14px;background:radial-gradient(circle at 50% 0,rgba(145,70,255,.28),transparent 65%),#111827}
.av{width:84px;height:84px;border-radius:50%;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-size:36px;font-weight:700;margin:0 auto 12px;box-shadow:0 0 0 5px rgba(145,70,255,.22)}
.hero h2{font-size:26px;margin:0 0 8px;color:var(--tx)}
.pill{display:inline-block;font-size:12px;padding:4px 12px;border-radius:20px;background:#1c2438;color:var(--mut);font-weight:700}
.pill.live{background:rgba(46,204,113,.15);color:#2ecc71}
.acts{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:18px}
.acts .btn,.acts a.btn{width:auto;padding:10px 18px}
.btn.line{background:none;border:1px solid #2a3350;color:var(--tx)}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:14px}
.stat{padding:18px}
.stat small{font-size:12px;color:var(--mut)}
.stat b{display:block;font-size:28px;margin-top:6px}
.stat b.ok{color:var(--ok)}.stat b.bad{color:var(--bad);font-size:20px;margin-top:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.bar{display:flex;align-items:center;gap:10px;margin:12px 0;font-size:14px}
.bar b{min-width:70px}
.bar i{flex:1;height:10px;background:#1c2438;border-radius:6px;overflow:hidden}
.bar s{display:block;height:100%;background:linear-gradient(90deg,#9146ff,#c084fc);border-radius:6px}
.bar em{font-style:normal;color:var(--mut);min-width:24px;text-align:end}
.bubble{background:#0a0e17;border:1px solid #1c2438;border-radius:12px;padding:12px 14px;min-height:56px;white-space:pre-wrap;word-break:break-word;font-size:14px}
.bubble:before{content:"🤖 ";}
.simrow{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tool{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.tool input{flex:1;min-width:160px;margin:0}
.tool .btn{width:auto}
.chip,.lchip,.rchip{background:#111827;border:1px solid #1c2438;color:var(--mut);padding:8px 14px;border-radius:20px;font:inherit;cursor:pointer;font-size:13px}
.chip.on,.lchip.on,.rchip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.cmd{display:flex;gap:12px;padding:14px;margin-bottom:10px;align-items:flex-start}
.cbody{flex:1;min-width:0}
.chead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.chead b{font-size:16px;color:#e9ddff}
.cbody p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.bd{font-size:11px;padding:3px 10px;border-radius:20px;background:#1c2438;color:var(--mut)}
.bd.g{background:rgba(145,70,255,.2);color:#c4a1ff}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:grid;place-items:center;z-index:50;padding:16px}
.sheet{background:#111827;border:1px solid #1c2438;border-radius:18px;padding:20px;width:100%;max-width:520px;max-height:92vh;overflow:auto}
.sheet .card{background:none;border:0;padding:0;margin:0}
.ar-item{background:#0a0e17;border:1px solid #1c2438;border-radius:12px;padding:12px;margin-bottom:10px}
.ar-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
.ar-head b{font-size:14px;color:#e9ddff}
.ar-item input{margin-bottom:0;background:#111827}
.chkrow{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0}
.chkrow label{display:flex;align-items:center;gap:6px;cursor:pointer;color:var(--tx);margin:0}
.chkrow input[type=checkbox]{width:auto;margin:0;accent-color:var(--acc)}
.timer-form{display:grid;grid-template-columns:1fr 110px;gap:8px;margin-top:10px}
.timer-form input{margin:0}
.timer-form textarea{grid-column:1/-1;margin:0;min-height:66px}
.timer-form .btn{grid-column:1/-1}
#bd{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:30}
@media(max-width:860px){
 aside{display:none}
 aside.open{display:flex;position:fixed;inset-block:0;inset-inline-start:0;z-index:40;width:270px}
 .burger{display:block}
 .grid2,.simrow,.timer-form{grid-template-columns:1fr}
 .content{padding:16px}.top{padding:12px 16px}
}
</style>
<div id="login" hidden style="padding:16px">
  <div class="card" style="max-width:380px;margin:12vh auto 0;text-align:center">
    <div class="logo" style="margin:0 auto 12px">🎮</div>
    <h1 style="font-size:20px;margin:0 0 8px">موقع الستريمر</h1>
    <p class="mut">ضغطة وحدة وتتفعّل الأمور: البوت يدخل قناتك ويرتبط تغيير اللعبة</p>
    <div id="loginbtns">
      <a class="btn" href="/auth/streamer">أنا ستريمر: تفعيل البوت في قناتي</a>
      <a class="btn line mt" href="/auth/login">أنا مود: دخول فقط</a>
    </div>
    <p class="mut" id="nolink" hidden>الموقع غير مفعّل بعد من المطوّر.</p>
    <button class="btn ghost langbtn" style="margin-top:10px">EN</button>
  </div>
</div>

<div class="shell" id="app" hidden>
  <aside id="side">
    <div class="brand"><div class="logo">🎮</div><span>موقع الستريمر</span></div>
    <select id="chsel" hidden></select>
    <div class="nav" id="nav">
      <a data-p="ov" class="on"><i>🏠</i><span>الرئيسية</span></a>
      <a data-p="cmd"><i>⌨️</i><span>الكوماندات</span></a>
      <a data-p="mods" class="own"><i>🛡️</i><span>المودات</span></a>
      <a data-p="set" class="own"><i>⚙️</i><span>الإعدادات</span></a>
    </div>
    <div class="me">
      <div class="meinfo"><div class="mav" id="meav"></div><div><b id="who" dir="ltr" data-nt></b><small class="mut" id="role"></small></div></div>
      <div class="mebtns"><button class="btn ghost langbtn">EN</button><button class="btn ghost" id="logout">خروج</button></div>
    </div>
  </aside>
  <div id="bd" hidden></div>
  <main>
    <div class="top">
      <button class="btn ghost burger" id="burger">☰</button>
      <h1 id="ptitle">الرئيسية</h1>
      <span class="pill" id="livepill"></span>
    </div>
    <div class="content">
      <div class="card" id="nochan" hidden>
        <p class="mut" style="margin:0">ما عندك قنوات هنا. إذا أنت ستريمر اضغط "أنا ستريمر" عشان تفعّل البوت في قناتك، وإذا أنت مود خلّ الستريمر يضيفك.</p>
      </div>
      <div class="card" id="banned" hidden>
        <h2>🚫 قناتك محظورة</h2>
        <p class="mut" style="margin:0">تم حظر قناتك من استخدام البوت. إذا تعتقد أن هذا خطأ تواصل مع المطوّر.</p>
      </div>

      <div id="main" hidden>
        <section class="pg" id="p-ov">
          <div class="hero">
            <div class="av" id="av"></div>
            <h2 id="chname" dir="ltr" data-nt></h2>
            <div class="mut" id="curgame" data-nt style="margin-top:10px"></div>
            <div class="acts">
              <button class="btn plus" id="ovnew">كوماند جديد</button>
              <a class="btn line" id="pubbtn" target="_blank">فتح صفحة الكوماندات العامة</a>
            </div>
          </div>
          <div class="panel" style="margin-bottom:14px">
            <h3>عنوان البث</h3>
            <p class="mut" id="curtitle" data-nt style="margin:6px 0 0"></p>
            <div class="tool" style="margin:12px 0 0">
              <input id="newtitle" placeholder="العنوان الجديد" maxlength="140">
              <button class="btn" id="savetitle">تغيير العنوان</button>
            </div>
            <p class="hint" id="titlehint" style="margin:8px 0 0" hidden>يحتاج ربط تويتش من الإعدادات عشان يشتغل</p>
          </div>
          <div class="grid4">
            <div class="stat"><small>كوماندات عادية</small><b id="s-text">0</b></div>
            <div class="stat"><small>اختصارات الألعاب</small><b id="s-game">0</b></div>
            <div class="stat"><small>المودات</small><b id="s-mods">0</b></div>
            <div class="stat"><small>حالة الربط</small><b id="s-link"></b></div>
          </div>
          <div class="grid2">
            <div class="panel">
              <h3>الأكثر استخداماً</h3>
              <p class="hint" style="margin:0 0 6px">الاستخدام يُحسب من آخر تشغيل للبوت</p>
              <div id="topbox"></div>
            </div>
            <div class="panel">
              <h3>محاكي الكوماند</h3>
              <p class="hint" style="margin:0 0 10px">جرّب الكوماند قبل ما ينشر. يستخدم نفس المتغيرات</p>
              <select id="simcmd"></select>
              <div class="simrow">
                <input id="simuser" placeholder="اسم المشاهد" dir="ltr">
                <input id="simarg" placeholder="كلمة بعد الكوماند (اختياري)" dir="ltr">
              </div>
              <div class="bubble" id="simout" data-nt></div>
            </div>
          </div>
          <div class="panel">
            <h3>كوماندات الشات الأساسية</h3>
            <p class="hint" style="margin:0 0 6px">للستريمر والمودات. اضغط 📋 للنسخ</p>
            <div id="basiclist"></div>
          </div>
        </section>

        <section class="pg" id="p-cmd" hidden>
          <div class="tool">
            <input id="q" placeholder="بحث في الكوماندات">
            <button class="chip on" data-f="all">كل الأنواع</button>
            <button class="chip" data-f="text">ردود</button>
            <button class="chip" data-f="game">ألعاب</button>
            <button class="btn plus" id="newcmd">كوماند جديد</button>
          </div>
          <div id="cmdlist"></div>
        </section>

        <section class="pg own" id="p-mods" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>المودات المصرّح لهم يعدلون الكوماندات</h3>
            <div style="display:flex;gap:10px;margin-top:12px">
              <input id="newed" dir="ltr" placeholder="يوزر المود في تويتش" style="margin:0">
              <button class="btn" id="added" style="width:auto">إضافة مود</button>
            </div>
            <div id="edlist" style="margin-top:10px"></div>
            <p class="hint">المود يدخل بحسابه من نفس الموقع ويعدل الكوماندات فقط. ما يقدر يشيل البوت أو يغيّر الإعدادات.</p>
          </div>
        </section>

        <section class="pg own" id="p-set" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>الردود التلقائية للبوت (الافتراضية)</h3>
            <p class="mut">عدّل نص الرد أو عطّل أي رد تلقائي ما تبيه يشتغل في قناتك. استخدم <code dir="ltr">$(user)</code> لاسم المشاهد.</p>
            <div id="arlist" style="margin-top:12px"></div>
            <div style="display:flex;gap:10px;margin-top:10px">
              <button class="btn" id="savear">حفظ الردود التلقائية</button>
              <button class="btn ghost" id="resetar">استعادة الافتراضي</button>
            </div>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3>الرسائل الدورية الافتراضية (الأذكار، الأدعية، الماء)</h3>
            <p class="mut">تُرسل تلقائياً أثناء البث المباشر فقط حسب المدة اللي تحددها</p>
            <div class="tool" style="margin:12px 0 6px">
              <button class="rchip" data-rm="on">مفعّلة</button>
              <button class="rchip" data-rm="off">متوقفة</button>
            </div>
            <div id="remcfgbox" style="margin-top:12px">
              <label>المدة بين كل رسالة والأخرى (بالدقائق)</label>
              <input id="reminterval" type="number" min="1" max="180" value="30">
              <div class="chkrow">
                <label><input type="checkbox" id="remsaudi"> أدعية المملكة</label>
                <label><input type="checkbox" id="remdhikr"> أذكار</label>
                <label><input type="checkbox" id="remwater"> تذكير شرب الماء</label>
              </div>
              <label>نص تذكير الماء</label>
              <input id="remwatertxt" placeholder="اشربوا ماااااااي">
              <button class="btn" id="saveremcfg">حفظ إعدادات الرسائل الدورية</button>
            </div>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3>رسائل دورية مخصصة (مؤقتات)</h3>
            <p class="mut">أضف أي رسالة أو دعاء وحدد كل كم دقيقة ينكتب تلقائياً في الشات أثناء البث (مثلاً كل 5 دقائق)</p>
            <div class="timer-form">
              <input id="tmname" placeholder="اسم المؤقت (مثلاً: دعاء أو حساباتي)">
              <input id="tminterval" type="number" min="1" max="180" value="5" placeholder="المدة (دقائق)">
              <textarea id="tmtext" placeholder="نص الرسالة اللي بتتكرر تلقائياً..."></textarea>
              <button class="btn" id="addtimer">إضافة / حفظ المؤقت</button>
            </div>
            <div id="timerlist" style="margin-top:14px"></div>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3>حساب بوت مخصص للقناة (تغيير اسم البوت)</h3>
            <p class="mut" id="cbotstate"></p>
            <p class="hint" style="margin:6px 0 10px">تقدر تربط حسابك الشخصي نفسه أو أي حساب بوت ثاني بالاسم اللي تبيه، وبتطلع ردود البوت في قناتك باسم وصورة الحساب اللي تختاره.</p>
            <a class="btn" id="cbotbtn" href="#">ربط حساب بوت مخصص لقناتي</a>
            <button class="btn ghost mt" id="cbotdel" hidden>إلغاء البوت المخصص (العودة للافتراضي)</button>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3>لغة ردود البوت</h3>
            <p class="mut">تتحكم في لغة رسائل الكوماندات الأساسية (إضافة، تعديل، حذف، اللعبة، العنوان)</p>
            <div class="tool" style="margin:12px 0 10px">
              <button class="lchip" data-bl="ar">العربية</button>
              <button class="lchip" data-bl="en">English</button>
            </div>
            <div class="bubble" id="langprev" data-nt></div>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3>ربط تويتش (لتغيير اللعبة والعنوان)</h3>
            <p class="mut" id="linkstate"></p>
            <a class="btn" id="connect" href="/auth/connect">ربط تويتش</a>
            <button class="btn ghost mt" id="unlink" hidden>إلغاء الربط</button>
          </div>
          <div class="panel">
            <h3>إزالة البوت</h3>
            <p class="mut">يطلع البوت من قناتك وتتوقف كل الكوماندات والردود. الربط مع تويتش ينحذف.</p>
            <button class="btn red" id="leave">إزالة البوت من قناتي</button>
          </div>
        </section>
      </div>
    </div>
  </main>
</div>

<div class="modal" id="modal" hidden>
  <div class="sheet">
    {{FORM}}
    <button class="btn ghost mt" id="cancelcmd" style="width:100%">إلغاء</button>
  </div>
</div>
<div id="toast"></div>

<script>
//COMMON_JS
Object.assign(EN,{
"الرئيسية":"Overview","المودات":"Mods","كوماند جديد":"New command","بحث في الكوماندات":"Search commands",
"كل الأنواع":"All types","ردود":"Replies","ألعاب":"Games","اختصارات الألعاب":"Game shortcuts",
"كوماندات عادية":"Text commands","حالة الربط":"Twitch link","مربوط":"Linked","غير مربوط":"Not linked",
"الأكثر استخداماً":"Most used","الاستخدام يُحسب من آخر تشغيل للبوت":"Usage is counted since the bot's last restart",
"ما فيه استخدام للحين":"No usage yet","محاكي الكوماند":"Command simulator",
"جرّب الكوماند قبل ما ينشر. يستخدم نفس المتغيرات":"Try a command before going live. Uses the same variables",
"اسم المشاهد":"Viewer name","كلمة بعد الكوماند (اختياري)":"Word after the command (optional)",
"🎮 سيتغيّر كاتيقوري البث إلى:":"🎮 The stream category will change to:",
"رابط الكوماندات للجميع":"Public commands link","فتح صفحة الكوماندات العامة":"Open public commands page",
"إلغاء":"Cancel","ستريمر":"Streamer","مود":"Mod","ما فيه كوماندات تطابق بحثك":"No commands match your search",
"مفعّلة":"On","متوقفة":"Off","تم الحفظ":"Saved"
});
for(const k in EN)AR[EN[k]]=k;
let ME=null,CH=null,PG="ov",FILT="all",Q="",EDIT_TM_ID=null;
const TITLES={ov:"الرئيسية",cmd:"الكوماندات",mods:"المودات",set:"الإعدادات"};
const AR_LABELS={
  salam:"رد السلام (السلام عليكم / سلام)",
  salam_evening:"رد السلام + مساء الخير معاً",
  evening:"رد مساء الخير",
  back:"رد باك",
  brb:"رد برب / brb"
};
const dn=(n,c)=>((c&&c.bang===false)?"":"!")+n;
const base=()=>"/s/api/channel/"+encodeURIComponent(CH.name);
const base2=()=>"/s/api/channel/"+encodeURIComponent($("#chsel").value);
onAuth=d=>{
  $("#app").hidden=true;$("#login").hidden=false;
  if(d&&d.enabled===false){$("#loginbtns").hidden=true;$("#nolink").hidden=false}
};
onLang=()=>{if(ME)fillSel();if(CH)render();cmdFormSync();$("#ptitle").textContent=t(TITLES[PG])};
function fillSel(){
  const sel=$("#chsel"),prev=sel.value;sel.innerHTML="";
  ME.channels.forEach(c=>sel.add(new Option(c.name+(c.role==="editor"?" "+t("(مود)"):""),c.name)));
  if(ME.channels.some(c=>c.name===prev))sel.value=prev;
}
function go(p){
  if((p==="mods"||p==="set")&&(!CH||CH.role!=="owner"))p="ov";
  PG=p;
  document.querySelectorAll(".pg").forEach(x=>x.hidden=x.id!=="p-"+p);
  document.querySelectorAll("#nav a").forEach(x=>x.classList.toggle("on",x.dataset.p===p));
  $("#ptitle").textContent=t(TITLES[p]);
  $("#side").classList.remove("open");$("#bd").hidden=true;
}
const openModal=()=>{$("#modal").hidden=false};
const closeModal=()=>{$("#modal").hidden=true};
async function act(fn,msg,reinit){
  try{await fn();if(msg)toast(msg);reinit?await init():await loadCh()}
  catch(e){if(e.message!=="auth")toast(e.message,1)}
}
async function init(){
  try{ME=await api("GET","/s/api/me")}catch(e){if(e.message!=="auth")toast(e.message,1);return}
  $("#login").hidden=true;$("#app").hidden=false;
  $("#who").textContent=ME.login;$("#meav").textContent=ME.login.charAt(0).toUpperCase();
  $("#banned").hidden=!ME.banned;
  $("#nav").hidden=!!ME.banned;
  if(ME.banned){$("#nochan").hidden=true;$("#main").hidden=true;$("#chsel").hidden=true;return}
  fillSel();
  $("#chsel").hidden=ME.channels.length<2;
  $("#nochan").hidden=ME.channels.length>0;
  $("#main").hidden=!ME.channels.length;
  $("#nav").hidden=!ME.channels.length;
  if(ME.channels.length)await loadCh();
}
async function loadCh(){
  try{CH=await api("GET",base2())}catch(e){if(e.message!=="auth")toast(e.message,1);return}
  render();
}
function render(){
  const c=CH,own=c.role==="owner",names=Object.keys(c.commands);
  const games=names.filter(n=>c.commands[n].type==="game").length;
  $("#chname").textContent=c.name;$("#av").textContent=c.name.charAt(0).toUpperCase();
  $("#livepill").className="pill"+(c.live?" live":"");
  $("#livepill").textContent=t(c.live?"لايف":"أوفلاين");
  $("#curgame").textContent=c.game?t("🎮 اللعبة الحالية:")+" "+c.game:"";
  $("#pubbtn").href="/c/"+encodeURIComponent(c.name);
  $("#curtitle").textContent=c.title?t("📝 العنوان الحالي:")+" "+c.title:"";
  $("#curtitle").hidden=!c.title;
  $("#titlehint").hidden=!!c.linked;
  document.querySelectorAll(".lchip").forEach(x=>x.classList.toggle("on",x.dataset.bl===(c.lang==="en"?"en":"ar")));
  document.querySelectorAll(".rchip").forEach(x=>x.classList.toggle("on",x.dataset.rm===(c.reminders?"on":"off")));
  $("#langprev").textContent=c.lang==="en"?"@viewer -> The command !hi has been added successfully":"@viewer تمت إضافة الكوماند !hi بنجاح ✅";
  renderBasic($("#basiclist"));
  $("#role").textContent=t(own?"ستريمر":"مود");
  $("#s-text").textContent=names.length-games;$("#s-game").textContent=games;
  $("#s-mods").textContent=own?c.editors.length:"—";
  const sl=$("#s-link");sl.textContent=t(c.linked?"مربوط":"غير مربوط");sl.className=c.linked?"ok":"bad";
  document.querySelectorAll(".own").forEach(x=>x.hidden=!own||(x.classList.contains("pg")&&x.id!=="p-"+PG));
  if(!own&&(PG==="mods"||PG==="set"))go("ov");
  renderTop();renderSim();renderCmds();
  if(own)renderOwn();
}
function renderTop(){
  const u=CH.usage||{},k=Object.keys(u).sort((a,b)=>u[b]-u[a]).slice(0,5),max=k.length?u[k[0]]:1,box=$("#topbox");
  box.innerHTML="";
  if(!k.length){box.innerHTML='<p class="empty">'+t("ما فيه استخدام للحين")+'</p>';return}
  k.forEach(n=>{
    const d=document.createElement("div");d.className="bar";
    d.innerHTML='<b dir="ltr" data-nt></b><i><s></s></i><em data-nt></em>';
    d.querySelector("b").textContent=dn(n,CH.commands[n]);
    d.querySelector("s").style.width=Math.max(6,u[n]/max*100)+"%";
    d.querySelector("em").textContent=u[n];
    box.appendChild(d);
  });
}
function renderSim(){
  const s=$("#simcmd"),v=s.value;s.innerHTML="";
  Object.keys(CH.commands).sort().forEach(n=>s.add(new Option(dn(n,CH.commands[n]),n)));
  if(CH.commands[v])s.value=v;
  runSim();
}
function runSim(){
  const c=CH&&CH.commands[$("#simcmd").value],o=$("#simout");
  if(!c){o.textContent="…";return}
  const user=$("#simuser").value.trim()||"viewer",arg=$("#simarg").value.trim().replace(/^@/,"");
  const rep=(c.reply||"").split("$(user)").join(user).split("$(touser)").join(arg||user).split("$(channel)").join(CH.name).split("$(game)").join(c.game||"");
  o.textContent=(c.type==="game"?t("🎮 سيتغيّر كاتيقوري البث إلى:")+" "+c.game+"\n":"")+rep;
}
function renderCmds(){
  const box=$("#cmdlist"),cmds=CH.commands,q=Q.toLowerCase();box.innerHTML="";
  const names=Object.keys(cmds).sort().filter(n=>{
    const c=cmds[n];
    if(FILT!=="all"&&c.type!==FILT)return false;
    return !q||n.includes(q)||(c.reply||"").toLowerCase().includes(q)||(c.game||"").toLowerCase().includes(q);
  });
  if(!names.length){box.innerHTML='<p class="empty">'+t(Object.keys(cmds).length?"ما فيه كوماندات تطابق بحثك":"ما فيه كوماندات")+'</p>';return}
  names.forEach(n=>{
    const c=cmds[n],d=document.createElement("div");d.className="cmd";
    d.innerHTML='<div class="cbody"><div class="chead"><b dir="ltr" data-nt></b><span class="bd t" data-nt></span><span class="bd" data-nt></span></div><p data-nt></p></div><div><button class="ic ed">✏️</button><button class="ic del">🗑</button></div>';
    d.querySelector("b").textContent=dn(n,c);
    const bt=d.querySelector(".bd.t");bt.textContent=c.type==="game"?t("🎮 يغيّر اللعبة إلى:")+" "+c.game:t("💬 رد عادي");
    if(c.type==="game")bt.classList.add("g");
    d.querySelectorAll(".bd")[1].textContent=t(PERMS[c.perm]||"الكل");
    d.querySelector("p").textContent=c.reply||"";
    d.querySelector(".ed").onclick=()=>{cmdFormFill(n,c);openModal()};
    d.querySelector(".del").onclick=()=>{if(ask("تحذف !{n}؟",n))act(()=>api("DELETE",base()+"/commands/"+encodeURIComponent(n)),"تم حذف الكوماند")};
    box.appendChild(d);
  });
}
function renderOwn(){
  const c=CH;
  // 1. الردود التلقائية الافتراضية
  const arBox=$("#arlist");arBox.innerHTML="";
  const ars=c.auto_replies||{};
  Object.keys(AR_LABELS).forEach(k=>{
    const item=ars[k]||{enabled:true,text:""};
    const d=document.createElement("div");d.className="ar-item";
    d.innerHTML='<div class="ar-head"><b data-nt></b><label style="display:flex;align-items:center;gap:6px;margin:0;cursor:pointer;color:var(--tx)"><input type="checkbox" style="width:auto;margin:0;accent-color:var(--acc)"> <span>مفعّل</span></label></div><input type="text" maxlength="450" data-nt>';
    d.querySelector("b").textContent=AR_LABELS[k];
    const chk=d.querySelector("input[type=checkbox]");chk.checked=!!item.enabled;chk.dataset.key=k;
    const inp=d.querySelector("input[type=text]");inp.value=item.text||"";inp.dataset.key=k;
    arBox.appendChild(d);
  });

  // 2. إعدادات الرسائل الدورية الافتراضية
  const rcfg=c.reminder_cfg||{interval:30,saudi:true,dhikr:true,water:true,water_text:"اشربوا ماااااااي"};
  $("#reminterval").value=rcfg.interval||30;
  $("#remsaudi").checked=!!rcfg.saudi;
  $("#remdhikr").checked=!!rcfg.dhikr;
  $("#remwater").checked=!!rcfg.water;
  $("#remwatertxt").value=rcfg.water_text||"اشربوا ماااااااي";

  // 3. المؤقتات المخصصة
  const tBox=$("#timerlist");tBox.innerHTML="";
  const timers=c.custom_timers||[];
  if(!timers.length)tBox.innerHTML='<p class="empty">ما أضفت رسائل دورية مخصصة للحين</p>';
  timers.forEach(tm=>{
    const d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b data-nt></b><span><button class="ic tog"></button><button class="ic ed">✏️</button><button class="ic del">🗑</button></span></div><div class="meta" data-nt></div><p data-nt></p>';
    d.querySelector("b").textContent=tm.name||"مؤقت";
    d.querySelector(".meta").textContent="كل "+tm.interval+" دقيقة • "+(tm.enabled?"مفعّل ✅":"متوقف ⏸");
    d.querySelector("p").textContent=tm.text||"";
    const tog=d.querySelector(".tog");tog.textContent=tm.enabled?"⏸":"▶️";tog.title=tm.enabled?"إيقاف مؤقت":"تفعيل";
    tog.onclick=()=>act(()=>api("POST",base()+"/timers",{id:tm.id,name:tm.name,text:tm.text,interval:tm.interval,enabled:!tm.enabled}),"تم التحديث");
    d.querySelector(".ed").onclick=()=>{
      EDIT_TM_ID=tm.id;
      $("#tmname").value=tm.name||"";
      $("#tminterval").value=tm.interval||5;
      $("#tmtext").value=tm.text||"";
      $("#tmname").focus();
    };
    d.querySelector(".del").onclick=()=>{if(confirm("تحذف المؤقت؟"))act(()=>api("DELETE",base()+"/timers/"+encodeURIComponent(tm.id)),"تم الحذف")};
    tBox.appendChild(d);
  });

  // 4. حساب البوت المخصص
  $("#cbotstate").textContent=c.custom_bot
    ? "✅ البوت الحالي في قناتك هو: "+c.custom_bot
    : "البوت الحالي في قناتك هو البوت الافتراضي ("+(c.default_bot||"majek_bot")+")";
  $("#cbotbtn").href="/auth/custom_bot?ch="+encodeURIComponent(c.name);
  $("#cbotbtn").textContent=c.custom_bot?"تغيير حساب البوت المخصص":"ربط حساب بوت مخصص لقناتي";
  $("#cbotdel").hidden=!c.custom_bot;

  // 5. ربط تويتش والمودات
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
document.querySelectorAll("#nav a").forEach(a=>a.onclick=()=>go(a.dataset.p));
$("#burger").onclick=()=>{$("#side").classList.add("open");$("#bd").hidden=false};
$("#bd").onclick=()=>{$("#side").classList.remove("open");$("#bd").hidden=true};
$("#chsel").onchange=loadCh;
$("#q").oninput=e=>{Q=e.target.value.trim();renderCmds()};
document.querySelectorAll(".chip").forEach(b=>b.onclick=()=>{
  FILT=b.dataset.f;document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("on",x===b));renderCmds();
});
$("#simcmd").onchange=runSim;$("#simuser").oninput=runSim;$("#simarg").oninput=runSim;
const newCmd=()=>{cmdFormClear();openModal()};
$("#newcmd").onclick=newCmd;
$("#ovnew").onclick=()=>{go("cmd");newCmd()};
$("#savetitle").onclick=()=>act(async()=>{
  await api("POST",base()+"/title",{title:$("#newtitle").value});$("#newtitle").value="";
},"تم تغيير عنوان البث");
document.querySelectorAll(".lchip").forEach(b=>b.onclick=()=>act(()=>api("POST",base()+"/lang",{lang:b.dataset.bl}),"تم تغيير لغة ردود البوت"));
document.querySelectorAll(".rchip").forEach(b=>b.onclick=()=>act(()=>api("POST",base()+"/reminders",{on:b.dataset.rm==="on"}),"تم الحفظ"));
$("#savear").onclick=()=>act(async()=>{
  const payload={};
  document.querySelectorAll("#arlist input[type=checkbox]").forEach(chk=>{
    const k=chk.dataset.key;
    const txt=document.querySelector('#arlist input[type=text][data-key="'+k+'"]').value;
    payload[k]={enabled:chk.checked,text:txt};
  });
  await api("POST",base()+"/auto_replies",payload);
},"تم حفظ الردود التلقائية");
$("#resetar").onclick=()=>{
  if(confirm("تستعيد جميع الردود التلقائية للنص الافتراضي؟"))
    act(()=>api("POST",base()+"/auto_replies",{reset:true}),"تمت الاستعادة");
};
$("#saveremcfg").onclick=()=>act(()=>api("POST",base()+"/reminder_cfg",{
  interval:parseInt($("#reminterval").value,10)||30,
  saudi:$("#remsaudi").checked,
  dhikr:$("#remdhikr").checked,
  water:$("#remwater").checked,
  water_text:$("#remwatertxt").value
}),"تم حفظ إعدادات الرسائل الدورية");
$("#addtimer").onclick=()=>act(async()=>{
  await api("POST",base()+"/timers",{
    id:EDIT_TM_ID,
    name:$("#tmname").value,
    interval:parseInt($("#tminterval").value,10)||5,
    text:$("#tmtext").value,
    enabled:true
  });
  EDIT_TM_ID=null;
  $("#tmname").value="";$("#tminterval").value="5";$("#tmtext").value="";
},"تم حفظ المؤقت");
$("#cbotdel").onclick=()=>{
  if(confirm("تلغي البوت المخصص وترجع للبوت الافتراضي؟"))
    act(()=>api("POST",base()+"/custom_bot/remove"),"تمت العودة للبوت الافتراضي");
};
$("#cancelcmd").onclick=closeModal;
$("#modal").onclick=e=>{if(e.target.id==="modal")closeModal()};
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST",base()+"/commands",cmdFormGet());cmdFormClear();closeModal();
},"تم حفظ الكوماند");
$("#added").onclick=()=>act(async()=>{
  await api("POST",base()+"/editors",{name:$("#newed").value});$("#newed").value="";
},"تمت إضافة المود");
$("#unlink").onclick=()=> {if(ask("تلغي الربط مع تويتش؟"))act(()=>api("POST",base()+"/unlink"),"تم إلغاء الربط")};
$("#leave").onclick=()=>{
  if(ask("متأكد تبي تشيل البوت من قناتك؟"))act(()=>api("POST",base()+"/leave"),"تم إزالة البوت",true);
};
$("#logout").onclick=async()=>{await api("POST","/s/api/logout");onAuth({enabled:true})};
const qp=new URLSearchParams(location.search);
if(qp.get("msg")==="ready")toast("تم تفعيل البوت وربط تويتش ✅");
if(qp.get("msg")==="cbot")toast("تم ربط حساب البوت المخصص لقناتك بنجاح ✅");
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
<style>
.wrap{max-width:900px}
.hero{display:flex;align-items:center;gap:16px;padding:20px;border:1px solid var(--line);border-radius:18px;margin-bottom:16px;background:radial-gradient(circle at 100% 0,rgba(145,70,255,.28),transparent 60%),var(--card)}
.av{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-size:28px;font-weight:700;flex-shrink:0;box-shadow:0 0 0 4px rgba(145,70,255,.22)}
.info{flex:1;min-width:0}
.info h1{margin:0 0 6px;font-size:22px;word-break:break-all}
.sub{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{display:inline-block;font-size:12px;padding:4px 12px;border-radius:20px;background:#1c2438;color:var(--mut);font-weight:700}
.pill.live{background:rgba(46,204,113,.15);color:#2ecc71}
.tool{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.tool input{flex:1;min-width:180px;margin:0}
.chip{background:var(--card);border:1px solid var(--line);color:var(--mut);padding:8px 14px;border-radius:20px;font:inherit;cursor:pointer;font-size:13px}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.cc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.cc .h{display:flex;align-items:center;justify-content:space-between;gap:8px}
.cc b{font-size:16px;color:#e9ddff;cursor:pointer;word-break:break-all}
.cc b:hover{color:#fff}
.cc p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.bd.p-sub{background:rgba(59,130,246,.18);color:#7db4ff}
.bd.p-vip{background:rgba(236,72,153,.18);color:#f59ac8}
.bd.p-mod{background:rgba(46,204,113,.15);color:#2ecc71}
.bd.p-broadcaster{background:rgba(245,166,35,.18);color:#f5a623}
.sec{margin-top:22px}
@media(max-width:560px){.hero{padding:16px}.av{width:52px;height:52px;font-size:22px}}
</style>
<div class="wrap">
  <div class="hero">
    <div class="av" id="av"></div>
    <div class="info">
      <h1 id="chname" dir="ltr" data-nt></h1>
      <div class="sub"><span class="pill" id="live" hidden></span><span class="mut" id="cnt" data-nt></span></div>
    </div>
    <button class="btn ghost langbtn">EN</button>
  </div>
  <div class="card" id="nf" hidden><p class="mut" style="margin:0">القناة غير موجودة أو البوت غير مفعّل فيها</p></div>
  <div id="box">
    <div class="tool">
      <input id="q" placeholder="بحث في الكوماندات">
      <button class="chip on" data-f="all">كل الأنواع</button>
      <button class="chip" data-f="text">ردود</button>
      <button class="chip" data-f="game">ألعاب</button>
    </div>
    <div class="grid" id="list"></div>
    <div class="card sec">
      <h2>كوماندات الشات الأساسية</h2>
      <p class="hint">للستريمر والمودات. اضغط 📋 للنسخ</p>
      <div id="basiclist"></div>
    </div>
  </div>
  <p class="hint" style="text-align:center;margin-top:18px"><a href="/s" style="color:var(--acc)">أنت الستريمر أو مود؟ ادخل لوحة التحكم</a></p>
</div>
<div id="toast"></div>
<script>
//COMMON_JS
const CHN=decodeURIComponent(location.pathname.split("/").pop()).toLowerCase();
let D=null,BAD=false,FILT="all",Q="";
function render(){
  $("#chname").textContent=CHN;$("#av").textContent=CHN.charAt(0).toUpperCase();
  $("#nf").hidden=!BAD;$("#box").hidden=BAD;
  if(BAD||!D)return;
  const lp=$("#live");lp.hidden=false;lp.className="pill"+(D.live?" live":"");lp.textContent=t(D.live?"لايف":"أوفلاين");
  const all=Object.keys(D.commands).sort(),q=Q.toLowerCase();
  $("#cnt").textContent=all.length+" "+t("كوماند");
  const box=$("#list");box.innerHTML="";
  const names=all.filter(n=>{
    const c=D.commands[n];
    if(FILT!=="all"&&c.type!==FILT)return false;
    return !q||n.includes(q)||(c.reply||"").toLowerCase().includes(q)||(c.game||"").toLowerCase().includes(q);
  });
  if(!names.length){
    box.innerHTML='<p class="empty" style="grid-column:1/-1">'+t(all.length?"ما فيه كوماندات تطابق بحثك":"ما فيه كوماندات")+'</p>';
  }
  names.forEach(n=>{
    const c=D.commands[n],d=document.createElement("div");d.className="cc";
    d.innerHTML='<div class="h"><b dir="ltr" data-nt></b><span class="bd" data-nt></span></div><div class="meta" data-nt></div><p data-nt></p>';
    const nm=(c.bang===false?"":"!")+n,b=d.querySelector("b");
    b.textContent=nm;b.title=t("اضغط للنسخ");b.onclick=()=>copyText(nm);
    const bd=d.querySelector(".bd");bd.textContent=t(PERMS[c.perm]||"الكل");
    if(c.perm&&c.perm!=="everyone")bd.classList.add("p-"+c.perm);
    d.querySelector(".meta").textContent=c.type==="game"?t("🎮 يغيّر اللعبة إلى:")+" "+c.game:t("💬 رد عادي");
    d.querySelector("p").textContent=c.type==="game"?"":(c.reply||"");
    box.appendChild(d);
  });
  renderBasic($("#basiclist"));
}
onLang=render;
$("#q").oninput=e=>{Q=e.target.value.trim();render()};
document.querySelectorAll(".chip").forEach(b=>b.onclick=()=>{
  FILT=b.dataset.f;document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("on",x===b));render();
});
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
    store.data.get("custom_bots", {}).pop(name, None)
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
    store.data.get("custom_bots", {}).pop(name, None)
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
        "scope": SCOPES.get(mode, ""),
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

  async def auth_bot(request):
    state_val, url = await auth_start("b")
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def auth_custom_bot(request):
    login = read_session(request.cookies.get("ssess", ""))
    ch = request.query.get("ch", "").lower()
    if not login or role_of(login, ch) != "owner":
      raise web.HTTPFound("/s")
    if not twitch.enabled:
      raise web.HTTPFound("/s")
    state_val = "x" + secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urlencode({
        "client_id": CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "state": state_val,
        "scope": SCOPES["cb"],
        "force_verify": "true",
    })
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    resp.set_cookie("cbot_ch", ch, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def eventsub_hook(request):
    raw = await request.read()
    h = request.headers
    mid = h.get("Twitch-Eventsub-Message-Id", "")
    ts = h.get("Twitch-Eventsub-Message-Timestamp", "")
    sig = h.get("Twitch-Eventsub-Message-Signature", "")
    mine = "sha256=" + hmac.new(
        EVENTSUB_SECRET.encode(), mid.encode() + ts.encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig.encode(), mine.encode()):
      return web.Response(status=403)
    try:
      body = json.loads(raw)
    except Exception:
      return web.Response(status=400)
    kind = h.get("Twitch-Eventsub-Message-Type", "")
    if kind == "webhook_callback_verification":
      return web.Response(text=str(body.get("challenge", "")), content_type="text/plain")
    if kind == "notification":
      asyncio.create_task(bot.on_chat_event(mid, body.get("event") or {}))
    elif kind == "revocation":
      asyncio.create_task(bot.on_revocation(body.get("subscription") or {}))
    return web.Response(status=204)

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

    # 1. ربط حساب البوت الأساسي
    if state_val[0] == "b":
      if login_name != BOT_LOGIN:
        resp = web.Response(
            text=f"دخلت بحساب {login_name}، لازم تدخل بحساب {BOT_LOGIN}", status=400)
        resp.del_cookie("ostate")
        return resp
      resp = web.Response(text="تم ربط حساب البوت بنجاح ✅ تقدر تقفل الصفحة")
      resp.del_cookie("ostate")
      return resp

    # 2. ربط حساب بوت مخصص للستريمر (يقبل حساب البوت الجديد أو حساب الستريمر نفسه)
    if state_val[0] == "x":
      target_ch = request.cookies.get("cbot_ch", "").lower()
      sess_login = read_session(request.cookies.get("ssess", ""))
      if not target_ch or not sess_login or role_of(sess_login, target_ch) != "owner":
        resp = web.HTTPFound("/s?err=fail")
        resp.del_cookie("ostate")
        resp.del_cookie("cbot_ch")
        raise resp
      store.data.setdefault("custom_bots", {})[target_ch] = {
          "login": login_name,
          "user_id": str(user["id"]),
      }
      twitch.user_ids[login_name] = str(user["id"])
      await store.save()
      try:
        await twitch.unsubscribe_chat(target_ch)
        await twitch.make_bot_mod(target_ch, login_name)
        await bot.join_channels([target_ch])
      except Exception as e:
        print(f"تعذر ربط البوت المخصص {login_name} لقناة {target_ch}: {e}")
      resp = web.HTTPFound("/s?msg=cbot")
      resp.del_cookie("ostate")
      resp.del_cookie("cbot_ch")
      raise resp

    # 3. دخول الستريمر / المود
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
        try:
          active_bot, _ = twitch.bot_for(login_name)
          await twitch.make_bot_mod(login_name, active_bot)
          await bot.join_channels([login_name])
        except Exception as e:
          print(f"تعذر تجهيز القناة {login_name}: {e}")
        dest = "/s?msg=ready"
    resp = web.HTTPFound(dest)
    resp.set_cookie("ssess", make_session(login_name), max_age=60 * 60 * 24 * 30,
                    httponly=True, samesite="Lax", secure=is_https(request))
    resp.del_cookie("ostate")
    raise resp

  async def c_page(request):
    return web.Response(text=PUBLIC_HTML, content_type="text/html")

  async def pub(request):
    ch = request.match_info["channel"].lower()
    if ch not in store.data["channels"]:
      return jerr("القناة غير موجودة", 404)
    return web.json_response({
        "name": ch,
        "live": await bot.is_channel_live(ch),
        "commands": store.data["commands"].get(ch, {}),
    })

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
    game = title = None
    if twitch.enabled:
      try:
        game, title = await twitch.channel_info(ch)
      except Exception:
        game = title = None
    cb = store.data.get("custom_bots", {}).get(ch)
    return web.json_response({
        "name": ch, "role": role,
        "live": await bot.is_channel_live(ch),
        "game": game,
        "title": title,
        "twitch": twitch.enabled,
        "linked": ch in store.data["tokens"],
        "commands": store.data["commands"].get(ch, {}),
        "editors": store.data["editors"].get(ch, []) if role == "owner" else [],
        "usage": bot.usage.get(ch, {}),
        "lang": store.data["lang"].get(ch, "ar"),
        "reminders": bool(store.data["reminders"].get(ch, False)),
        "reminder_cfg": store.get_reminder_cfg(ch) if role == "owner" else {},
        "custom_timers": store.get_custom_timers(ch) if role == "owner" else {},
        "auto_replies": store.get_auto_replies(ch) if role == "owner" else {},
        "custom_bot": cb.get("login") if isinstance(cb, dict) else None,
        "default_bot": BOT_LOGIN,
    })

  async def s_remove_custom_bot(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    if ch in store.data.get("custom_bots", {}):
      store.data["custom_bots"].pop(ch, None)
      await store.save()
      try:
        await twitch.unsubscribe_chat(ch)
        await twitch.make_bot_mod(ch, BOT_LOGIN)
        await bot.join_channels([ch])
      except Exception as e:
        print(f"تعذر استعادة البوت الافتراضي في {ch}: {e}")
    return web.json_response({"ok": True})

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
    store.data.get("custom_bots", {}).pop(ch, None)
    twitch.user_access.pop(ch, None)
    await store.save()
    try:
      await bot.part_channels([ch])
    except Exception as e:
      print(f"تعذر الخروج من {ch}: {e}")
    return web.json_response({"ok": True})

  async def s_lang(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    lang = (await jbody(request)).get("lang")
    if lang not in ("ar", "en"):
      return jerr("صار خطأ")
    store.data["lang"][ch] = lang
    await store.save()
    return web.json_response({"ok": True})

  async def s_reminders(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    store.data["reminders"][ch] = bool((await jbody(request)).get("on"))
    await store.save()
    return web.json_response({"ok": True})

  async def s_reminder_cfg(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    try:
      iv = max(1, min(180, int(b.get("interval", 30))))
    except Exception:
      iv = 30
    wt = str(b.get("water_text", "")).strip()[:450] or "اشربوا ماااااااي"
    store.data.setdefault("reminder_cfg", {})[ch] = {
        "interval": iv,
        "saudi": bool(b.get("saudi", True)),
        "dhikr": bool(b.get("dhikr", True)),
        "water": bool(b.get("water", True)),
        "water_text": wt,
    }
    await store.save()
    return web.json_response({"ok": True})

  async def s_save_timer(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    text = str(b.get("text", "")).strip()[:450]
    if not text:
      return jerr("اكتب نص الرسالة")
    name = str(b.get("name", "")).strip()[:40] or "مؤقت"
    try:
      iv = max(1, min(180, int(b.get("interval", 5))))
    except Exception:
      return jerr("المدة غير صحيحة")
    enabled = b.get("enabled") is not False
    tid = str(b.get("id") or "").strip()
    timers = store.data.setdefault("custom_timers", {}).setdefault(ch, [])
    if tid:
      for tm in timers:
        if tm.get("id") == tid:
          tm["name"] = name
          tm["text"] = text
          tm["interval"] = iv
          tm["enabled"] = enabled
          break
      else:
        timers.append({"id": tid, "name": name, "text": text, "interval": iv, "enabled": enabled})
    else:
      if len(timers) >= 20:
        return jerr("الحد الأقصى 20 مؤقت")
      timers.append({
          "id": secrets.token_hex(4),
          "name": name,
          "text": text,
          "interval": iv,
          "enabled": enabled,
      })
    await store.save()
    return web.json_response({"ok": True})

  async def s_del_timer(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    tid = request.match_info["id"]
    timers = store.data.setdefault("custom_timers", {}).get(ch, [])
    store.data["custom_timers"][ch] = [tm for tm in timers if tm.get("id") != tid]
    await store.save()
    return web.json_response({"ok": True})

  async def s_auto_replies(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    if b.get("reset"):
      store.data.setdefault("auto_replies", {}).pop(ch, None)
      await store.save()
      return web.json_response({"ok": True})
    ar_map = store.data.setdefault("auto_replies", {}).setdefault(ch, {})
    for k, default_val in DEFAULT_AUTO_REPLIES.items():
      if k in b and isinstance(b[k], dict):
        txt = str(b[k].get("text", "")).strip()[:450]
        ar_map[k] = {
            "enabled": bool(b[k].get("enabled", True)),
            "text": txt if txt else default_val["text"],
        }
    await store.save()
    return web.json_response({"ok": True})

  async def s_title(request):
    a, err = access(request)
    if err:
      return err
    _, ch, _ = a
    title = str((await jbody(request)).get("title", "")).strip()[:140]
    if not title:
      return jerr("اكتب العنوان")
    ok, result = await twitch.set_title(ch, title)
    if not ok:
      return jerr(MSG["e_" + result][0].format(q=""))
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
  # EventSub
  r.add_post("/eventsub", eventsub_hook)
  # موقع الستريمر
  r.add_get("/s", s_index)
  r.add_get("/auth/login", auth_login)
  r.add_get("/c/{channel}", c_page)
  r.add_get("/pub/{channel}", pub)
  r.add_get("/auth/streamer", auth_streamer)
  r.add_get("/auth/connect", auth_connect)
  r.add_get("/auth/bot", auth_bot)
  r.add_get("/auth/custom_bot", auth_custom_bot)
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
  r.add_post("/s/api/channel/{channel}/lang", s_lang)
  r.add_post("/s/api/channel/{channel}/reminders", s_reminders)
  r.add_post("/s/api/channel/{channel}/reminder_cfg", s_reminder_cfg)
  r.add_post("/s/api/channel/{channel}/timers", s_save_timer)
  r.add_delete("/s/api/channel/{channel}/timers/{id}", s_del_timer)
  r.add_post("/s/api/channel/{channel}/auto_replies", s_auto_replies)
  r.add_post("/s/api/channel/{channel}/custom_bot/remove", s_remove_custom_bot)
  r.add_post("/s/api/channel/{channel}/title", s_title)
  return app


async def start_web_server(bot):
  runner = web.AppRunner(make_web_app(bot))
  await runner.setup()
  port = int(os.environ.get("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


# ============================================================
# البوت (EventSub للقراءة + Send Chat Message API للإرسال)
# ============================================================
class IRCClient:

  def __init__(self, bot, token):
    self.bot = bot
    self.token = token if token.startswith("oauth:") else "oauth:" + token
    self.writer = None
    self.ready = asyncio.Event()
    self.channels = set()

  def _raw(self, line):
    if self.writer:
      self.writer.write((line.replace("\r", " ").replace("\n", " ") + "\r\n").encode("utf-8"))

  async def run(self):
    delay = 5
    while True:
      try:
        await self._session()
        delay = 5
      except Exception as e:
        print(f"IRC: انقطع الاتصال ({e})")
        if "auth" in str(e):
          delay = 300
      self.ready.clear()
      self.writer = None
      await asyncio.sleep(delay)
      delay = min(delay * 2, 120)

  async def _session(self):
    reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT, ssl=IRC_SSL)
    self.writer = writer
    self._raw("CAP REQ :twitch.tv/tags twitch.tv/commands")
    self._raw("PASS " + self.token)
    self._raw("NICK " + BOT_LOGIN)
    while True:
      line = await asyncio.wait_for(reader.readline(), timeout=400)
      if not line:
        raise ConnectionError("closed")
      await self._handle(line.decode("utf-8", "ignore").rstrip("\r\n"))

  async def _rejoin(self):
    for c in list(self.channels):
      self._raw("JOIN #" + c)
      await asyncio.sleep(0.6)

  async def _handle(self, line):
    tags = {}
    rest = line
    if rest.startswith("@"):
      raw, _, rest = rest.partition(" ")
      for kv in raw[1:].split(";"):
        k, _, v = kv.partition("=")
        tags[k] = v
    if rest.startswith("PING"):
      self._raw("PONG :tmi.twitch.tv")
      return
    parts = rest.split(" ", 3)
    if len(parts) < 2:
      return
    cmd = parts[1]
    if cmd == "001":
      self.ready.set()
      print("IRC: تم الاتصال بحساب البوت")
      asyncio.create_task(self._rejoin())
    elif cmd == "RECONNECT":
      raise ConnectionError("reconnect requested")
    elif cmd == "NOTICE" and "authentication failed" in rest.lower():
      raise RuntimeError("auth failed: التوكن غلط أو من حساب ثاني")
    elif cmd == "PRIVMSG" and len(parts) == 4:
      nick = parts[0][1:].split("!", 1)[0].lower()
      chan = parts[2].lstrip("#").lower()
      text = parts[3][1:] if parts[3].startswith(":") else parts[3]
      if text.startswith("\x01ACTION ") and text.endswith("\x01"):
        text = text[8:-1]
      ev = {
          "chatter_user_login": nick,
          "chatter_user_id": tags.get("user-id", ""),
          "broadcaster_user_login": chan,
          "broadcaster_user_id": tags.get("room-id", ""),
          "message": {"text": text},
          "badges": [{"set_id": b.split("/")[0]} for b in tags.get("badges", "").split(",") if b],
      }
      await self.bot.on_chat_event("irc-" + (tags.get("id") or secrets.token_hex(6)), ev)

  def join(self, ch):
    self.channels.add(ch)
    if self.ready.is_set():
      self._raw("JOIN #" + ch)

  def part(self, ch):
    if ch in self.channels:
      self.channels.discard(ch)
      if self.ready.is_set():
        self._raw("PART #" + ch)

  async def say(self, ch, text):
    if not self.ready.is_set() or not self.writer:
      return False
    self._raw(f"PRIVMSG #{ch} :{text[:490]}")
    return True


class Author:

  def __init__(self, ev):
    self.name = (ev.get("chatter_user_login") or "").lower()
    ids = {b.get("set_id") for b in ev.get("badges") or []}
    same_id = bool(ev.get("chatter_user_id")) and ev.get("chatter_user_id") == ev.get("broadcaster_user_id")
    self.is_broadcaster = "broadcaster" in ids or same_id
    self.is_mod = "moderator" in ids
    self.is_vip = "vip" in ids
    self.is_subscriber = bool(ids & {"subscriber", "founder"})
    self.badges = {i: "1" for i in ids}


class ChatChannel:

  def __init__(self, bot, name):
    self.bot = bot
    self.name = name

  async def send(self, text):
    await self.bot.send_chat(self.name, text)


class ChatMessage:

  def __init__(self, bot, ev):
    self.author = Author(ev)
    self.channel = ChatChannel(bot, (ev.get("broadcaster_user_login") or "").lower())
    self.content = (ev.get("message") or {}).get("text", "")
    self.echo = False


class Bot:

  def __init__(self):
    self.store = Store()
    self.twitch = TwitchAPI(self.store)
    self.nick = BOT_LOGIN
    self.last_dhikr = None
    self.last_saudi_prayer = None
    self.live_cache = {}
    self.cmd_cooldown = {}
    self.usage = {}
    self.seen = {}
    self.recent_sent = []
    self.queues = {}
    self.paused = set()
    self.irc = IRCClient(self, IRC_TOKEN) if IRC_TOKEN else None
    self.irc_channels = set()
    self.rem_state = {}
    self.timer_last = {}

  def run(self):
    loop = asyncio.get_event_loop()
    loop.create_task(self.start())
    loop.run_forever()

  async def start(self):
    print(f"البوت يشتغل بحساب ({self.nick}) عبر EventSub.")
    await self.store.load()
    data = self.store.data
    if OWNER not in data["channels"] and OWNER not in data["banned"]:
      data["channels"].append(OWNER)
    asyncio.create_task(start_web_server(self))
    asyncio.create_task(self.periodic_reminders())
    asyncio.create_task(self.resub_loop())
    if self.irc:
      asyncio.create_task(self.irc.run())
    else:
      print("ملاحظة: ما فيه TWITCH_TOKEN، فالقنوات اللي ما أعطت صلاحية ما راح يرد فيها البوت")

  async def resub_all(self):
    for s in await self.twitch.list_subs():
      if s.get("status") not in ("enabled", "webhook_callback_verification_pending"):
        await self.twitch.drop_sub(s["id"])
    await self.join_channels([
        c for c in self.store.data["channels"]
        if c not in self.store.data["banned"] and c not in self.paused
    ])

  async def resub_loop(self):
    await asyncio.sleep(10)
    while True:
      try:
        await self.resub_all()
      except Exception as e:
        print(f"خطأ في الاشتراك: {e}")
      await asyncio.sleep(3600)

  async def join_channels(self, names):
    for n in names:
      self.paused.discard(n)
      ok, why = await self.twitch.subscribe_chat(n)
      if ok:
        print(f"اشتراك الشات {n}: ✅")
        if n in self.irc_channels:
          self.irc_channels.discard(n)
          if self.irc:
            self.irc.part(n)
      elif self.irc:
        print(f"اشتراك الشات {n}: ❌ {why} ← يشتغل بالـ IRC")
        self.irc_channels.add(n)
        self.irc.join(n)
      else:
        print(f"اشتراك الشات {n}: ❌ {why}")
      await asyncio.sleep(0.3)

  async def part_channels(self, names):
    for n in names:
      try:
        await self.twitch.unsubscribe_chat(n)
      except Exception as e:
        print(f"تعذر إلغاء الاشتراك {n}: {e}")
      if n in self.irc_channels:
        self.irc_channels.discard(n)
      if self.irc:
        self.irc.part(n)
      q = self.queues.pop(n, None)
      if q is not None:
        q.put_nowait(None)

  async def on_revocation(self, sub):
    status = sub.get("status")
    print(f"تويتش ألغى اشتراك: {status}")
    if status not in ("authorization_revoked", "user_removed"):
      return
    bid = (sub.get("condition") or {}).get("broadcaster_user_id")
    for name, uid in list(self.twitch.user_ids.items()):
      if uid == bid and name != self.nick:
        self.paused.add(name)
        print(f"أوقفت المحاولات في {name} لين يعيد الستريمر الربط")

  def get_channel(self, name):
    return ChatChannel(self, name) if name in self.store.data["channels"] else None

  async def send_chat(self, channel_name, text):
    if channel_name in self.store.data["banned"]:
      return
    q = self.queues.get(channel_name)
    if q is None:
      q = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
      self.queues[channel_name] = q
      asyncio.create_task(self._send_worker(channel_name, q))
    try:
      q.put_nowait((text, time.time()))
    except asyncio.QueueFull:
      print(f"طابور الإرسال ممتلئ في {channel_name}، تجاهلت رسالة")

  async def _send_worker(self, ch, q):
    times = []
    while True:
      item = await q.get()
      if item is None:
        return
      text, queued_at = item
      if time.time() - queued_at > SEND_STALE:
        continue
      while True:
        now = time.time()
        times = [t for t in times if now - t < SEND_WINDOW]
        wait = 0
        if times and now - times[-1] < SEND_MIN_GAP:
          wait = SEND_MIN_GAP - (now - times[-1])
        if len(times) >= SEND_MAX_PER_WINDOW:
          wait = max(wait, SEND_WINDOW - (now - times[0]) + 0.1)
        if wait <= 0:
          break
        await asyncio.sleep(wait)
      if ch in self.store.data["banned"] or ch not in self.store.data["channels"]:
        continue
      now_send = time.time()
      times.append(now_send)
      self.recent_sent = [x for x in self.recent_sent if now_send - x[2] < 20]
      self.recent_sent.append((ch, text[:490].strip(), now_send))
      try:
        if ch in self.irc_channels and self.irc:
          ok = await self.irc.say(ch, text)
          why = "IRC غير متصل"
        else:
          ok, why = await self.twitch.chat_send(ch, text)
        if not ok:
          print(f"تعذر الإرسال في {ch}: {why}")
          if str(why).startswith("429"):
            await asyncio.sleep(10)
      except Exception as e:
        print(f"خطأ إرسال في {ch}: {e}")

  async def on_chat_event(self, mid, ev):
    try:
      now = time.time()
      for k in [k for k, v in self.seen.items() if now - v > 600]:
        del self.seen[k]
      if mid in self.seen:
        return
      self.seen[mid] = now
      who = (ev.get("chatter_user_login") or "").lower()
      chan = (ev.get("broadcaster_user_login") or "").lower()
      msg_txt = ((ev.get("message") or {}).get("text") or "").strip()
      ch_bot, _ = self.twitch.bot_for(chan)
      if who == self.nick or who in KNOWN_BOTS:
        return
      if who == ch_bot and who != chan:
        return
      # تجاهل الرسائل اللي أرسلها البوت نفسه قبل ثوانٍ (مهم إذا الستريمر ربط حسابه نفسه كبوت)
      if any(c == chan and t == msg_txt and now - ts < 15 for c, t, ts in self.recent_sent):
        return
      await self.event_message(ChatMessage(self, ev))
    except Exception as e:
      print(f"خطأ في معالجة رسالة: {e}")

  async def is_channel_live(self, channel_name):
    now = time.time()
    cached = self.live_cache.get(channel_name)
    if cached and now - cached[0] < LIVE_CACHE_SECONDS:
      return cached[1]
    try:
      live = await self.twitch.is_live(channel_name)
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
    while True:
      await asyncio.sleep(30)
      now = time.time()
      for channel_name in list(self.store.data["channels"]):
        if channel_name in self.store.data["banned"]:
          continue

        rem_on = self.store.data["reminders"].get(channel_name, False)
        timers = [tm for tm in self.store.get_custom_timers(channel_name) if tm.get("enabled")]

        if not rem_on and not timers:
          continue

        if not await self.is_channel_live(channel_name):
          continue

        channel = self.get_channel(channel_name)
        if not channel:
          continue

        if rem_on:
          cfg = self.store.get_reminder_cfg(channel_name)
          pool = []
          if cfg["saudi"]:
            pool.append(f"اللهم صلِّ وسلم على نبينا محمد، {self.get_random_saudi_prayer()}")
          if cfg["dhikr"]:
            pool.append(self.get_random_dhikr())
          if cfg["water"]:
            pool.append(cfg["water_text"])

          if pool:
            st = self.rem_state.setdefault(channel_name, {"last": now, "step": 0})
            if now - st["last"] >= cfg["interval"] * 60:
              msg_text = pool[st["step"] % len(pool)]
              st["step"] = (st["step"] + 1) % len(pool)
              st["last"] = now
              try:
                await channel.send(msg_text)
              except Exception as e:
                print(f"تعذر إرسال التذكير في {channel_name}: {e}")

        for tm in timers:
          tid = tm.get("id")
          if not tid:
            continue
          key = (channel_name, tid)
          if key not in self.timer_last:
            self.timer_last[key] = now
            continue
          iv_sec = max(1, int(tm.get("interval", 5))) * 60
          if now - self.timer_last[key] >= iv_sec:
            self.timer_last[key] = now
            txt = format_response(tm.get("text", ""), channel_name, channel_name, channel_name)
            if txt:
              try:
                await channel.send(txt[:490])
              except Exception as e:
                print(f"تعذر إرسال المؤقت في {channel_name}: {e}")

  # ----------------------------------------------------------
  # الكوماندات
  # ----------------------------------------------------------
  def lang_of(self, ch):
    return "en" if self.store.data["lang"].get(ch) == "en" else "ar"

  def tr(self, ch, key, **kw):
    ar, en = MSG[key]
    return (en if self.lang_of(ch) == "en" else ar).format(**kw)

  async def say(self, message, ch, key, extra="", **kw):
    sep = " -> " if self.lang_of(ch) == "en" else " "
    text = self.tr(ch, key, **kw) + (self.tr(ch, extra) if extra else "")
    await message.channel.send(f"@{message.author.name}{sep}{text}"[:490])

  async def send_cmd_list(self, message, ch, level):
    cmds = self.store.data["commands"].get(ch, {})
    usable = [n for n, c in cmds.items() if level >= PERMS[c["perm"]]]
    if not usable:
      await self.say(message, ch, "no_cmds")
    else:
      names = " ".join(disp_cmd(n, cmds[n]) for n in sorted(usable))
      await self.say(message, ch, "cmds_list", n=names)

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

    async def say(key, extra="", **kw):
      await self.say(message, channel_name, key, extra, **kw)

    if cmd == "commands":
      ckey = (channel_name, "!commands")
      now = time.time()
      if now - self.cmd_cooldown.get(ckey, 0) < 10:
        return True
      self.cmd_cooldown[ckey] = now
      if SITE_URL:
        await say("cmds_link", u=f"{SITE_URL}/c/{channel_name}")
      else:
        await self.send_cmd_list(message, channel_name, level)
      return True

    if cmd == "bot" and "bot" not in channel_cmds:
      bkey = (channel_name, "!bot")
      now = time.time()
      if now - self.cmd_cooldown.get(bkey, 0) < 30:
        return True
      self.cmd_cooldown[bkey] = now
      if SITE_URL:
        await say("bot_info", u=f"{SITE_URL}/s")
      return True

    if cmd == "reminders":
      if not is_mod:
        return True
      arg = parts[1].lower() if len(parts) > 1 else ""
      if arg not in ("on", "off"):
        await say("rem_usage")
        return True
      self.store.data["reminders"][channel_name] = arg == "on"
      await self.store.save()
      await say("rem_on" if arg == "on" else "rem_off")
      return True

    if cmd in ("addcmd", "editcmd", "delcmd", "removecmd", "cmds"):
      if cmd == "cmds":
        await self.send_cmd_list(message, channel_name, level)
        return True

      if not is_mod:
        return True

      if cmd in ("delcmd", "removecmd"):
        if len(parts) < 2:
          await say("usage_del")
          return True
        name = parts[1].lstrip("!").lower()
        if name in channel_cmds:
          shown = disp_cmd(name, channel_cmds[name])
          del channel_cmds[name]
          await self.store.save()
          await say("deleted", c=shown)
        else:
          await say("del_nf", c=parts[1])
        return True

      if len(parts) < 3:
        await say("usage_add", cmd=cmd)
        return True
      bang = parts[1].startswith("!")
      name = parts[1].lstrip("!").lower()
      reply = parts[2].strip()[:450]
      if not name or len(name) > 30 or name in BUILTIN:
        await say("bad_name")
        return True
      if not bang and not re.fullmatch(r"\w+", name):
        await say("bad_plain")
        return True

      if cmd == "addcmd":
        if name in channel_cmds:
          await say("exists", c=disp_cmd(name, channel_cmds[name]))
          return True
        channel_cmds[name] = norm_cmd(reply)
        channel_cmds[name]["bang"] = bang
        await self.store.save()
        await say("added", c=disp_cmd(name, channel_cmds[name]))
      else:
        if name not in channel_cmds:
          await say("edit_nf", c=parts[1])
          return True
        channel_cmds[name]["reply"] = reply
        await self.store.save()
        await say("edited", c=disp_cmd(name, channel_cmds[name]))
      return True

    if cmd == "addgame":
      if not is_mod:
        return True
      if len(parts) < 3:
        await say("usage_game")
        return True
      if not self.twitch.enabled:
        await say("game_off")
        return True
      raw_name = parts[1]
      bang = raw_name.startswith("!")
      key_name = raw_name.lstrip("!").lower()
      existing = channel_cmds.get(key_name)
      if existing and existing.get("type") != "game":
        await say("game_is_text", c=disp_cmd(key_name, existing))
        return True
      query = parts[2].strip()
      game = await self.twitch.find_game(query)
      if not game:
        await say("game_nf", q=query)
        return True
      try:
        name, entry = build_command({
            "type": "game", "name": raw_name, "bang": bang,
            "game": game["name"], "perm": "mod",
        })
      except ValueError:
        await say("bad_name")
        return True
      updated = existing is not None
      if updated:
        entry["perm"] = existing.get("perm", "mod")
        entry["reply"] = existing.get("reply") or entry["reply"]
      channel_cmds[name] = entry
      await self.store.save()
      warn = "" if channel_name in self.store.data["tokens"] else "link_warn"
      await say("g_edited" if updated else "g_added", warn,
                c=disp_cmd(name, entry), g=game["name"])
      return True

    if cmd == "settitle":
      if not is_mod:
        return True
      args = content.split(maxsplit=1)
      title = args[1].strip() if len(args) > 1 else ""
      if not title:
        await say("title_usage")
        return True
      tkey = (channel_name, "!settitle")
      now = time.time()
      if now - self.cmd_cooldown.get(tkey, 0) < COMMAND_COOLDOWN:
        return True
      self.cmd_cooldown[tkey] = now
      ok, result = await self.twitch.set_title(channel_name, title)
      if ok:
        await say("title_ok", t=result)
      else:
        await say("e_" + result, q="")
      return True

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

    entry = channel_cmds.get(cmd)
    if entry is None:
      return False
    return await self.run_custom(message, cmd, entry, parts, channel_name, level)

  async def handle_plain(self, message, content, channel_name, level):
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

  def count_use(self, channel_name, cmd):
    d = self.usage.setdefault(channel_name, {})
    d[cmd] = d.get(cmd, 0) + 1

  async def run_custom(self, message, cmd, entry, parts, channel_name, level):
    send = message.channel.send

    if level < PERMS[entry["perm"]]:
      return True

    key = (channel_name, cmd)
    now = time.time()

    target = parts[1].lstrip("@") if len(parts) > 1 else ""

    if entry["type"] == "game":
      if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
        return True
      self.cmd_cooldown[key] = now
      self.count_use(channel_name, cmd)
      ok, result = await self.twitch.set_game(channel_name, entry["game"])
      if ok:
        text = format_response(entry["reply"], message.author.name, channel_name, target, result)
        await send(text[:490])
      else:
        await self.say(message, channel_name, "e_" + result, q=entry["game"])
      return True

    if not await self.is_channel_live(channel_name):
      return True

    if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
      return True
    self.cmd_cooldown[key] = now
    self.count_use(channel_name, cmd)

    await send(format_response(entry["reply"], message.author.name, channel_name, target)[:490])
    return True

  # ----------------------------------------------------------
  # الرسائل
  # ----------------------------------------------------------
  async def event_message(self, message):
    if message.echo or not message.author.name:
      return

    username = message.author.name.lower()
    channel_name = message.channel.name.lower()
    content = message.content.strip()
    if channel_name in self.store.data["banned"]:
      return
    is_owner = username == OWNER
    level = user_level(message.author, is_owner)

    if content.startswith("!"):
      if await self.handle_command(
          message, content, username, channel_name, is_owner, level
      ):
        return
    elif await self.handle_plain(message, content, channel_name, level):
      return

    if username in IGNORED_USERS:
      return

    await self.auto_replies(message, content, username, channel_name)

  async def auto_replies(self, message, content, username, channel_name):
    current_time = time.time()
    send = message.channel.send

    if username in user_reply_time and current_time - user_reply_time[username] < USER_COOLDOWN:
      return

    if not await self.is_channel_live(channel_name):
      return

    ars = self.store.get_auto_replies(channel_name)

    content_l = content.lower()
    author_mention = f"@{message.author.name}"
    clean_content = re.sub(r"[^\w\s]", "", content_l)
    words = clean_content.split()

    if not words:
      return

    has_evening = "مساء الخير" in content_l
    has_full_greeting = "السلام عليكم" in content_l or "سلام عليكم" in content_l
    has_single_greeting = words[0] in ["السلام", "سلام"]
    has_greeting = has_full_greeting or has_single_greeting

    key_matched = None
    if has_greeting and has_evening:
      key_matched = "salam_evening"
    elif has_evening:
      key_matched = "evening"
    elif words[0] == "باك":
      key_matched = "back"
    elif words[0] in ["brb", "برب"]:
      key_matched = "brb"
    elif has_greeting:
      key_matched = "salam"

    if not key_matched:
      return

    cfg = ars.get(key_matched)
    if not cfg or not cfg.get("enabled"):
      return

    raw_text = cfg["text"]
    if "$(user)" in raw_text:
      reply_msg = format_response(raw_text, author_mention, channel_name, author_mention)
    else:
      reply_msg = f"{author_mention} {format_response(raw_text, author_mention, channel_name, author_mention)}"

    await send(reply_msg[:490])
    user_reply_time[username] = current_time


if __name__ == "__main__":
  bot = Bot()
  bot.run()
