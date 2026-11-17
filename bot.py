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

try:
  sys.stdout.reconfigure(line_buffering=True)
except Exception:
  pass

asyncio.set_event_loop(asyncio.new_event_loop())

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

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
MODERATE_SCOPE = "moderation:read channel:manage:moderators"
POINTS_SCOPE = "channel:read:redemptions channel:manage:redemptions"
EVENTSUB_SECRET = hashlib.sha256(b"eventsub:" + SECRET).hexdigest()

SCOPES = {
    "s": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE} {MODERATE_SCOPE} {POINTS_SCOPE}",
    "c": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE} {MODERATE_SCOPE} {POINTS_SCOPE}",
    "b": "user:bot user:read:chat user:write:chat",
    "cb": "user:bot user:read:chat user:write:chat",
}

PERMS = {"everyone": 0, "sub": 1, "vip": 2, "mod": 3, "broadcaster": 4}

BUILTIN = {
    "addcmd", "editcmd", "delcmd", "removecmd", "cmds", "addgame", "settitle",
    "addchannel", "removechannel", "channels", "commands", "reminders",
    "sr", "song", "skipsong", "currentsong", "quote", "addquote",
}

DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
]

SAUDI_PRAYERS = [
    "اللهم احفظ المملكة العربية السعودية وبارك في أمنها ورخائها وولاة أمرها وشعبها",
    "اللهم أدِم على السعودية أمنها وأمانها واحفظها من كل شر وسوء",
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
    "usage_add": ("الصيغة: !{cmd} اسم_الكوماند الرد", "Usage: !{cmd} command_name reply"),
    "bad_name": ("هذا الاسم ما ينفع للكوماند", "That command name isn't allowed"),
    "exists": ("الكوماند {c} موجود", "The command {c} already exists"),
    "added": ("تمت إضافة الكوماند {c} بنجاح ✅", "The command {c} has been added successfully"),
    "edited": ("تم تعديل الكوماند {c} بنجاح ✅", "The command {c} has been edited successfully"),
    "edit_nf": ("ما لقيت {c}", "I couldn't find {c}"),
    "link_warn": (" ⚠️ الستريمر لازم يربط تويتش", " ⚠️ The streamer must link Twitch"),
    "title_usage": ("الصيغة: !settitle العنوان الجديد", "Usage: !settitle new title"),
    "title_ok": ("تم تغيير عنوان البث إلى: {t} ✅", "The stream title has been changed to: {t}"),
    "rem_on": ("تم تفعيل الرسائل الدورية ✅", "Periodic messages are now on"),
    "rem_off": ("تم إيقاف الرسائل الدورية ✅", "Periodic messages are now off"),
}


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
    raise ValueError("Invalid command name")
  bang = b.get("bang") is not False
  perm = b.get("perm") if b.get("perm") in PERMS else "everyone"
  reply = str(b.get("reply", "")).strip()[:450]
  if b.get("type") == "game":
    game = str(b.get("game", "")).strip()[:100]
    if not game:
      raise ValueError("Enter game name")
    return name, {
        "type": "game", "game": game, "perm": perm, "bang": bang,
        "reply": reply or "Game changed to $(game) 🎮",
    }
  if not reply:
    raise ValueError("Enter reply")
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


class Store:

  def __init__(self):
    self.data = {
        "channels": list(DEFAULT_CHANNELS),
        "commands": {},
        "editors": {},
        "tokens": {},
        "custom_bots": {},
        "banned": [],
        "lang": {},
        "reminders": {c: True for c in DEFAULT_CHANNELS},
        "reminder_cfg": {},
        "custom_timers": {},
        "auto_replies": {},
        "song_requests": {},
        "quotes": {},
        "points_timeout": {},
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

  def get_points_timeout(self, ch):
    saved = self.data.setdefault("points_timeout", {}).get(ch, {})
    if isinstance(saved, dict):
      return {
          "enabled": bool(saved.get("enabled", False)),
          "duration": int(saved.get("duration", 20)),
          "reward_title": str(saved.get("reward_title", "1v1")).strip(),
      }
    return {"enabled": False, "duration": 20, "reward_title": "1v1"}

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
      self.data["song_requests"] = loaded.get("song_requests", {})
      self.data["quotes"] = loaded.get("quotes", {})
      self.data["points_timeout"] = loaded.get("points_timeout", {})
      if "reminders" in loaded:
        self.data["reminders"] = loaded["reminders"]
      else:
        self.data["reminders"] = {c: True for c in self.data["channels"]}
      self.data["channels"] = [c for c in self.data["channels"] if c not in self.data["banned"]]
    except Exception as e:
      print(f"Error loading data: {e}")

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
              print(f"Gist save failed: {resp.status}")
      else:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
          f.write(raw)
    except Exception as e:
      print(f"Error saving data: {e}")


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
      print(f"Twitch connection error: {e}")
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
      print(f"Helix error: {e}")
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

  async def timeout_user(self, channel, target_user, duration, reason="Channel points loss"):
    if not self.enabled:
      return False
    info = self.store.data["tokens"].get(channel)
    if not info:
      return False
    token = await self.user_token(channel)
    broadcaster_id = str(info["user_id"])
    target_id = await self.user_id(target_user)
    if not token or not target_id:
      return False
    moderator_id = broadcaster_id
    st, _ = await self.call(
        "POST", "moderation/bans", token,
        params={"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
        body={"data": {"user_id": target_id, "duration": int(duration), "reason": reason}}
    )
    return st == 204

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
    
    await self.call("POST", "eventsub/subscriptions", token, body={
        "type": "channel.chat.message", "version": "1",
        "condition": {"broadcaster_user_id": bid, "user_id": sid},
        "transport": {"method": "webhook", "callback": SITE_URL + "/eventsub",
                      "secret": EVENTSUB_SECRET},
    })
    
    await self.call("POST", "eventsub/subscriptions", token, body={
        "type": "channel.channel_points_custom_reward_redemption.add", "version": "1",
        "condition": {"broadcaster_user_id": bid},
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
"""

COMMON_JS = r"""
const $=s=>document.querySelector(s);
const PERMS={everyone:"Everyone",sub:"Subscribers+",vip:"VIP+",mod:"Mods only",broadcaster:"Streamer only"};
const BASIC=[
 {c:"!sr [url/name]",ce:"!sr [url/name]",ar:"طلب أغنية جديدة",en:"Request a song",p:"everyone"},
 {c:"!song",ce:"!song",ar:"عرض الأغنية الحالية",en:"Show current playing song",p:"everyone"},
 {c:"!skipsong",ce:"!skipsong",ar:"تخطي الأغنية الحالية",en:"Skip current song",p:"mod"},
 {c:"!quote",ce:"!quote",ar:"عرض مقولة عشوائية",en:"Show random quote",p:"everyone"},
 {c:"!addquote [text]",ce:"!addquote [text]",ar:"إضافة مقولة جديدة",en:"Add a new quote",p:"mod"},
 {c:"!reminders on/off",ce:"!reminders on/off",ar:"تشغيل أو إيقاف الأذكار والماء",en:"Toggle periodic messages",p:"mod"},
 {c:"!addcmd !hi Hello",ce:"!addcmd !hi Hello",ar:"إضافة كوماند رد",en:"Add a text command",p:"mod"},
 {c:"!editcmd !hi Welcome",ce:"!editcmd !hi Welcome",ar:"تعديل رد كوماند",en:"Edit command reply",p:"mod"},
 {c:"!delcmd !hi",ce:"!delcmd !hi",ar:"حذف كوماند",en:"Delete a command",p:"mod"},
 {c:"!commands",ce:"!commands",ar:"رابط جميع الكوماندات",en:"Link to all commands",p:"everyone"}
];
function copyText(s){
  try{navigator.clipboard.writeText(s).then(()=>toast("Copied"),()=>{})}catch(e){}
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
    const btn=d.querySelector("button");btn.title=t("Copy");btn.onclick=()=>copyText(txt);
    box.appendChild(d);
  });
}
const EN={
"Overview":"Overview","Commands":"Commands","Mods":"Mods","Settings":"Settings",
"Password":"Password","Log in":"Log in","Log out":"Log out",
"Channels":"Channels","Send message":"Send message",
"Add a channel":"Add a channel","Channel name, e.g. majek113":"Channel name, e.g. majek113",
"Add channel":"Add channel","Current channels":"Current channels",
"Add / edit command":"Add / edit command","Command type":"Command type",
"💬 Text reply":"💬 Text reply","🎮 Game shortcut (changes the stream's game)":"🎮 Game shortcut",
"Command name without !, e.g. fortnite":"Command name without !, e.g. fortnite",
"Game name, e.g. Fortnite":"Game name, e.g. Fortnite",
"Bot reply":"Bot reply","Who can use this command?":"Who can use this command?",
"Everyone":"Everyone","Subscribers and above":"Subscribers+",
"VIPs and above":"VIP+","Mods only":"Mods only","Streamer only":"Streamer only",
"Save command":"Save command","Channel commands":"Channel commands",
"Send a message as the bot":"Send a message as the bot","Message text":"Message text","Send":"Send",
"I'm a streamer: activate the bot on my channel":"I'm a streamer: activate the bot",
"I'm a mod: log in only":"I'm a mod: log in only",
"Streamer Site":"Streamer Site","Bot Control Panel":"Bot Control Panel",
"Twitch link (to change the game and title)":"Twitch link (to change game & title)",
"Link Twitch":"Link Twitch","Relink":"Relink","Unlink":"Unlink",
"Mods allowed to edit commands":"Mods allowed to edit commands",
"Mod's Twitch username":"Mod's Twitch username","Add mod":"Add mod",
"Remove the bot":"Remove the bot","Remove the bot from my channel":"Remove the bot from my channel",
"Bot:":"Bot:","No channels":"No channels","Live":"Live","Offline":"Offline",
"No commands":"No commands","Copied":"Copied","Copy":"Copy",
"Core bot commands":"Core bot commands","Core chat commands":"Core chat commands",
"For the streamer and mods. Press 📋 to copy":"For streamer and mods. Press 📋 to copy",
"All types":"All types","Replies":"Replies","Games":"Games","Search commands":"Search commands",
"Stream title":"Stream title","New title":"New title","Change title":"Change title",
"Bot reply language":"Bot reply language","Saved":"Saved","On":"On","Off":"Off",
"Channel Points Timeout Reward (1v1 / Game Loss Penalty)":"Channel Points Timeout Reward (1v1 / Game Loss Penalty)",
"Automatically timeout users in chat when they trigger a specific channel points reward (e.g. losing a 1v1 challenge).":"Automatically timeout users in chat when they trigger a specific channel points reward (e.g. losing a 1v1 challenge).",
"Enable Timeout Reward":"Enable Timeout Reward",
"Timeout Duration (seconds)":"Timeout Duration (seconds)",
"Channel Point Reward Title (exact name)":"Channel Point Reward Title (exact name)",
"Save Reward Settings":"Save Reward Settings",
"Song Requests (Nightbot Style)":"Song Requests (Nightbot Style)",
"View current song (!song), request songs (!sr), or skip (!skipsong).":"View current song (!song), request songs (!sr), or skip (!skipsong).",
"Auto-replies (Default)":"Auto-replies (Default)",
"Periodic Messages (Dhikr, Prayers, Water)":"Periodic Messages (Dhikr, Prayers, Water)",
"Custom Timers":"Custom Timers",
"Custom Bot Account":"Custom Bot Account"
};
const AR={
"Overview":"الرئيسية","Commands":"الكوماندات","Mods":"المودات","Settings":"الإعدادات",
"Password":"كلمة المرور","Log in":"دخول","Log out":"خروج",
"Channels":"القنوات","Send message":"إرسال رسالة",
"Add a channel":"إضافة قناة","Channel name, e.g. majek113":"اسم القناة مثل: majek113",
"Add channel":"إضافة القناة","Current channels":"القنوات الحالية",
"Add / edit command":"إضافة / تعديل كوماند","Command type":"نوع الكوماند",
"💬 Text reply":"💬 رد عادي","🎮 Game shortcut (changes the stream's game)":"🎮 اختصار لعبة",
"Command name without !, e.g. fortnite":"اسم الكوماند بدون ! مثل: fortnite",
"Game name, e.g. Fortnite":"اسم اللعبة مثل: Fortnite",
"Bot reply":"رد البوت","Who can use this command?":"مين يقدر يستخدم الكوماند؟",
"Everyone":"الكل","Subscribers and above":"المشتركين وفوق",
"VIPs and above":"VIP وفوق","Mods only":"المودات فقط","Streamer only":"الستريمر فقط",
"Save command":"حفظ الكوماند","Channel commands":"كوماندات القناة",
"Send a message as the bot":"إرسال رسالة كأنك البوت","Message text":"نص الرسالة","Send":"إرسال",
"I'm a streamer: activate the bot on my channel":"أنا ستريمر: تفعيل البوت في قناتي",
"I'm a mod: log in only":"أنا مود: دخول فقط",
"Streamer Site":"موقع الستريمر","Bot Control Panel":"لوحة تحكم البوت",
"Twitch link (to change the game and title)":"ربط تويتش (لتغيير اللعبة والعنوان)",
"Link Twitch":"ربط تويتش","Relink":"إعادة الربط","Unlink":"إلغاء الربط",
"Mods allowed to edit commands":"المودات المصرّح لهم يعدلون الكوماندات",
"Mod's Twitch username":"يوزر المود في تويتش","Add mod":"إضافة مود",
"Remove the bot":"إزالة البوت","Remove the bot from my channel":"إزالة البوت من قناتي",
"Bot:":"البوت:","No channels":"ما فيه قنوات","Live":"لايف","Offline":"أوفلاين",
"No commands":"ما فيه كوماندات","Copied":"تم النسخ","Copy":"نسخ",
"Core bot commands":"كوماندات البوت الأساسية","Core chat commands":"كوماندات الشات الأساسية",
"For the streamer and mods. Press 📋 to copy":"للستريمر والمودات. اضغط 📋 للنسخ",
"All types":"كل الأنواع","Replies":"ردود","Games":"ألعاب","Search commands":"بحث في الكوماندات",
"Stream title":"عنوان البث","New title":"العنوان الجديد","Change title":"تغيير العنوان",
"Bot reply language":"لغة ردود البوت","Saved":"تم الحفظ","On":"مفعّلة","Off":"متوقفة",
"Channel Points Timeout Reward (1v1 / Game Loss Penalty)":"مكافأة نقاط القناة للتايم آوت (تحدي 1v1 أو الخسارة)",
"Automatically timeout users in chat when they trigger a specific channel points reward (e.g. losing a 1v1 challenge).":"إعطاء تايم آوت تلقائي للمشاهد في الشات عند استخدام مكافأة نقاط قناة معينة (مثل خسارة 1v1).",
"Enable Timeout Reward":"تفعيل مكافأة التايم آوت",
"Timeout Duration (seconds)":"مدة التايم آوت (بالثواني)",
"Channel Point Reward Title (exact name)":"اسم مكافأة نقاط القناة (بالتحديد)",
"Save Reward Settings":"حفظ إعدادات التايم آوت",
"Song Requests (Nightbot Style)":"طلبات الأغاني (مثل نايت بوت)",
"View current song (!song), request songs (!sr), or skip (!skipsong).":"عرض الأغنية الحالية (!song)، طلب أغنية (!sr)، أو تخطي (!skipsong).",
"Auto-replies (Default)":"الردود التلقائية للبوت (الافتراضية)",
"Periodic Messages (Dhikr, Prayers, Water)":"الرسائل الدورية (أذكار، أدعية، ماء)",
"Custom Timers":"مؤقتات مخصصة",
"Custom Bot Account":"حساب بوت مخصص للقناة"
};
let LANG="ar";
try{if(localStorage.getItem("lang")==="en")LANG="en"}catch(e){}
const nz=s=>s.replace(/\s+/g," ").trim();
const t=s=>LANG==="en"?(EN[s]||s):(AR[s]||s);
const ask=(s,v)=>confirm(t(s).replace("{n}",v));
let onAuth=(),onLang=();
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
function toast(m,bad){m=t(m);const x=$("#toast");if(!x)return;x.textContent=m;x.className="show"+(bad?" bad":"");setTimeout(()=>x.className="",2400)}
async function api(method,path,body){
  const r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
  const d=await r.json().catch(()=>({}));
  if(r.status===401&&!path.endsWith("/login")){onAuth(d);throw new Error("auth")}
  if(!r.ok)throw new Error(d.error||"Error");
  return d;
}
function cmdFormSync(){
  const g=$("#ctype").value==="game";
  if($("#cgame"))$("#cgame").hidden=!g;
  if($("#gamehint"))$("#gamehint").hidden=!g;
  if($("#creply"))$("#creply").placeholder=t(g?"Bot reply after changing game (optional)":"Bot reply");
}
function cmdFormInit(){
  if($("#ctype"))$("#ctype").onchange=()=>{
    if($("#ctype").value==="game"&&$("#cperm").value==="everyone")$("#cperm").value="mod";
    cmdFormSync();
  };
  if($("#chips"))$("#chips").onclick=e=>{if(e.target.tagName==="SPAN"){const ta=$("#creply");if(ta){ta.value+=e.target.textContent;ta.focus()}}};
  cmdFormSync();
}
function cmdFormGet(){return{type:$("#ctype").value,bang:$("#cbang").value!=="no",name:$("#cname").value,game:$("#cgame").value,reply:$("#creply").value,perm:$("#cperm").value}}
function cmdFormClear(){
  if($("#ctype"))$("#ctype").value="text";if($("#cperm"))$("#cperm").value="everyone";if($("#cbang"))$("#cbang").value="yes";
  if($("#cname"))$("#cname").value="";if($("#cgame"))$("#cgame").value="";if($("#creply"))$("#creply").value="";cmdFormSync();
}
function cmdFormFill(n,c){
  if($("#ctype"))$("#ctype").value=c.type||"text";if($("#cperm"))$("#cperm").value=c.perm||"everyone";if($("#cbang"))$("#cbang").value=c.bang===false?"no":"yes";
  if($("#cname"))$("#cname").value=n;if($("#cgame"))$("#cgame").value=c.game||"";if($("#creply"))$("#creply").value=c.reply||"";
  cmdFormSync();window.scrollTo({top:0,behavior:"smooth"});
}
function renderCmdList(box,cmds,onDel){
  box.innerHTML="";const names=Object.keys(cmds).sort();
  if(!names.length){box.innerHTML='<p class="empty">'+t("No commands")+'</p>';return}
  names.forEach(n=>{
    const c=cmds[n],d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b dir="ltr" data-nt></b><span><button class="ic ed">✏️</button><button class="ic del">🗑</button></span></div><div class="meta" data-nt></div><p data-nt></p>';
    d.querySelector("b").textContent=(c.bang===false?"":"!")+n;
    d.querySelector(".meta").textContent=(c.type==="game"?t("Game shortcut")+": "+c.game:t("💬 Text reply"))+" • "+t(PERMS[c.perm]||"Everyone");
    d.querySelector("p").textContent=c.reply||"";
    d.querySelector(".ed").onclick=()=>cmdFormFill(n,c);
    d.querySelector(".del").onclick=()=>{if(ask("Delete !{n}?",n))onDel(n)};
    box.appendChild(d);
  });
}
"""

CMD_FORM = r"""
<div class="card">
  <h2>Add / edit command</h2>
  {{TOP}}
  <label>Command type</label>
  <select id="ctype">
    <option value="text">💬 Text reply</option>
    <option value="game">🎮 Game shortcut</option>
  </select>
  <input id="cname" dir="ltr" placeholder="Command name without !, e.g. fortnite">
  <label>Trigger</label>
  <select id="cbang">
    <option value="yes">Starts with ! (e.g. !discord)</option>
    <option value="no">Without ! (e.g. discord)</option>
  </select>
  <input id="cgame" dir="ltr" placeholder="Game name, e.g. Fortnite" hidden>
  <textarea id="creply" placeholder="Bot reply"></textarea>
  <div class="chips" id="chips"><span>$(user)</span><span>$(touser)</span><span>$(channel)</span><span>$(game)</span></div>
  <label>Who can use this command?</label>
  <select id="cperm">
    <option value="everyone">Everyone</option>
    <option value="sub">Subscribers and above</option>
    <option value="vip">VIPs and above</option>
    <option value="mod">Mods only</option>
    <option value="broadcaster">Streamer only</option>
  </select>
  <button class="btn" id="savecmd">Save command</button>
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

STREAMER_HTML = HEAD.replace("{{TITLE}}", "Streamer Site") + r"""
<style>
body{background:#0a0e17}
.shell{display:flex;min-height:100vh}
aside{width:250px;background:#0d1220;border-inline-end:1px solid #1c2438;display:flex;flex-direction:column;padding:16px 12px;position:sticky;top:0;height:100vh;flex-shrink:0}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;padding:4px 8px 14px}
.brand .logo{width:36px;height:36px;font-size:18px}
aside select{margin:0 0 14px}
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
    <h1 style="font-size:20px;margin:0 0 8px" data-nt>Streamer Site</h1>
    <p class="mut">One click activates bot and links channel</p>
    <div id="loginbtns">
      <a class="btn" href="/auth/streamer" data-nt>I'm a streamer: activate the bot on my channel</a>
      <a class="btn line mt" href="/auth/login" data-nt>I'm a mod: log in only</a>
    </div>
    <button class="btn ghost langbtn" style="margin-top:10px">عربي</button>
  </div>
</div>

<div class="shell" id="app" hidden>
  <aside id="side">
    <div class="brand"><div class="logo">🎮</div><span data-nt>Streamer Site</span></div>
    <select id="chsel" hidden></select>
    <div class="nav" id="nav">
      <a data-p="ov" class="on"><i data-nt>🏠</i><span data-nt>Overview</span></a>
      <a data-p="cmd"><i data-nt>⌨️</i><span data-nt>Commands</span></a>
      <a data-p="mods" class="own"><i data-nt>🛡️</i><span data-nt>Mods</span></a>
      <a data-p="set" class="own"><i data-nt>⚙️</i><span data-nt>Settings</span></a>
    </div>
    <div class="me">
      <div class="meinfo"><div class="mav" id="meav"></div><div><b id="who" dir="ltr" data-nt></b><small class="mut" id="role" data-nt></small></div></div>
      <div class="mebtns"><button class="btn ghost langbtn" data-nt>عربي</button><button class="btn ghost" id="logout" data-nt>Log out</button></div>
    </div>
  </aside>
  <div id="bd" hidden></div>
  <main>
    <div class="top">
      <button class="btn ghost burger" id="burger">☰</button>
      <h1 id="ptitle" data-nt>Overview</h1>
      <span class="pill" id="livepill"></span>
    </div>
    <div class="content">
      <div class="card" id="nochan" hidden>
        <p class="mut" style="margin:0" data-nt>No channels here.</p>
      </div>
      <div class="card" id="banned" hidden>
        <h2>🚫 Banned</h2>
        <p class="mut" style="margin:0" data-nt>Your channel is banned.</p>
      </div>

      <div id="main" hidden>
        <section class="pg" id="p-ov">
          <div class="hero">
            <div class="av" id="av"></div>
            <h2 id="chname" dir="ltr" data-nt></h2>
            <div class="mut" id="curgame" data-nt style="margin-top:10px"></div>
            <div class="acts">
              <button class="btn plus" id="ovnew" data-nt>New command</button>
              <a class="btn line" id="pubbtn" target="_blank" data-nt>Open public commands page</a>
            </div>
          </div>
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Stream title</h3>
            <p class="mut" id="curtitle" data-nt style="margin:6px 0 0"></p>
            <div class="tool" style="margin:12px 0 0">
              <input id="newtitle" placeholder="New title" maxlength="140" data-nt>
              <button class="btn" id="savetitle" data-nt>Change title</button>
            </div>
          </div>
          <div class="grid4">
            <div class="stat"><small data-nt>Text commands</small><b id="s-text">0</b></div>
            <div class="stat"><small data-nt>Game shortcuts</small><b id="s-game">0</b></div>
            <div class="stat"><small data-nt>Mods</small><b id="s-mods">0</b></div>
            <div class="stat"><small data-nt>Twitch link</small><b id="s-link"></b></div>
          </div>
          <div class="grid2">
            <div class="panel">
              <h3 data-nt>Most used</h3>
              <div id="topbox"></div>
            </div>
            <div class="panel">
              <h3 data-nt>Command simulator</h3>
              <select id="simcmd"></select>
              <div class="simrow">
                <input id="simuser" placeholder="Viewer name" dir="ltr" data-nt>
                <input id="simarg" placeholder="Argument" dir="ltr" data-nt>
              </div>
              <div class="bubble" id="simout" data-nt></div>
            </div>
          </div>
          <div class="panel">
            <h3 data-nt>Core chat commands</h3>
            <div id="basiclist"></div>
          </div>
        </section>

        <section class="pg" id="p-cmd" hidden>
          <div class="tool">
            <input id="q" placeholder="Search commands" data-nt>
            <button class="chip on" data-f="all" data-nt>All types</button>
            <button class="chip" data-f="text" data-nt>Replies</button>
            <button class="chip" data-f="game" data-nt>Games</button>
            <button class="btn plus" id="newcmd" data-nt>New command</button>
          </div>
          <div id="cmdlist"></div>
        </section>

        <section class="pg own" id="p-mods" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Mods allowed to edit commands</h3>
            <div style="display:flex;gap:10px;margin-top:12px">
              <input id="newed" dir="ltr" placeholder="Mod's Twitch username" style="margin:0" data-nt>
              <button class="btn" id="added" style="width:auto" data-nt>Add mod</button>
            </div>
            <div id="edlist" style="margin-top:10px"></div>
          </div>
        </section>

        <section class="pg own" id="p-set" hidden>
          <!-- Channel Points Timeout Reward Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Channel Points Timeout Reward (1v1 / Game Loss Penalty)</h3>
            <p class="mut" data-nt>Automatically timeout users in chat when they trigger a specific channel points reward (e.g. losing a 1v1 challenge).</p>
            <div class="chkrow" style="margin-top:12px">
              <label><input type="checkbox" id="pt_enabled"> <span data-nt>Enable Timeout Reward</span></label>
            </div>
            <label data-nt>Timeout Duration (seconds)</label>
            <input id="pt_duration" type="number" min="1" max="1209600" value="20">
            <label data-nt>Channel Point Reward Title (exact name)</label>
            <input id="pt_reward" placeholder="1v1" data-nt>
            <button class="btn mt" id="savept" data-nt>Save Reward Settings</button>
          </div>

          <!-- Song Requests Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Song Requests (Nightbot Style)</h3>
            <p class="mut" data-nt>View current song (!song), request songs (!sr), or skip (!skipsong).</p>
            <div id="srlist" class="bubble" style="margin-top:10px">No songs in queue. Use !sr [song] in chat.</div>
            <button class="btn ghost mt" id="clearsr">Clear Song Queue</button>
          </div>

          <!-- Auto Replies Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Auto-replies (Default)</h3>
            <p class="mut">Customize default auto-replies or toggle them off.</p>
            <div id="arlist" style="margin-top:12px"></div>
            <button class="btn mt" id="savear" data-nt>Saved</button>
          </div>

          <!-- Periodic Reminders Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Periodic Messages (Dhikr, Prayers, Water)</h3>
            <p class="mut">Sent automatically during live streams</p>
            <div class="tool" style="margin:12px 0 6px">
              <button class="rchip" data-rm="on" data-nt>On</button>
              <button class="rchip" data-rm="off" data-nt>Off</button>
            </div>
            <div id="remcfgbox" style="margin-top:12px">
              <label>Interval (minutes)</label>
              <input id="reminterval" type="number" min="1" max="180" value="30">
              <div class="chkrow">
                <label><input type="checkbox" id="remsaudi"> Saudi Prayers</label>
                <label><input type="checkbox" id="remdhikr"> Dhikr</label>
                <label><input type="checkbox" id="remwater"> Water Reminder</label>
              </div>
              <label>Water Reminder Text</label>
              <input id="remwatertxt" value="Drink water!">
              <button class="btn mt" id="saveremcfg" data-nt>Saved</button>
            </div>
          </div>

          <!-- Custom Timers Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Custom Timers</h3>
            <div class="timer-form">
              <input id="tmname" placeholder="Timer name">
              <input id="tminterval" type="number" min="1" max="180" value="5" placeholder="Interval">
              <textarea id="tmtext" placeholder="Message text..."></textarea>
              <button class="btn" id="addtimer">Save Timer</button>
            </div>
            <div id="timerlist" style="margin-top:14px"></div>
          </div>

          <!-- Custom Bot Account Section -->
          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Custom Bot Account</h3>
            <p class="mut" id="cbotstate"></p>
            <a class="btn" id="cbotbtn" href="#">Link custom bot account</a>
            <button class="btn ghost mt" id="cbotdel" hidden>Remove Custom Bot</button>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Bot reply language</h3>
            <div class="tool" style="margin:12px 0 10px">
              <button class="lchip" data-bl="ar">العربية</button>
              <button class="lchip" data-bl="en">English</button>
            </div>
            <div class="bubble" id="langprev" data-nt></div>
          </div>

          <div class="panel" style="margin-bottom:14px">
            <h3 data-nt>Twitch link (to change the game and title)</h3>
            <p class="mut" id="linkstate"></p>
            <a class="btn" id="connect" href="/auth/connect" data-nt>Link Twitch</a>
            <button class="btn ghost mt" id="unlink" hidden data-nt>Unlink</button>
          </div>
          <div class="panel">
            <h3 data-nt>Remove the bot</h3>
            <p class="mut" data-nt>The bot leaves your channel and all commands and replies stop.</p>
            <button class="btn red" id="leave" data-nt>Remove the bot from my channel</button>
          </div>
        </section>
      </div>
    </div>
  </main>
</div>

<div class="modal" id="modal" hidden>
  <div class="sheet">
    {{FORM}}
    <button class="btn ghost mt" id="cancelcmd" style="width:100%" data-nt>Cancel</button>
  </div>
</div>
<div id="toast"></div>

<script>
//COMMON_JS
let ME=null,CH=null,PG="ov",FILT="all",Q="",EDIT_TM_ID=null;
const TITLES={ov:"Overview",cmd:"Commands",mods:"Mods",set:"Settings"};
const AR_LABELS={salam:"Salam",salam_evening:"Salam + Evening",evening:"Evening",back:"Back",brb:"BRB"};
const dn=(n,c)=>((c&&c.bang===false)?"":"!")+n;
const base=()=>"/s/api/channel/"+encodeURIComponent(CH.name);
const base2=()=>"/s/api/channel/"+encodeURIComponent($("#chsel").value);
onAuth=d=>{$("#app").hidden=true;$("#login").hidden=false};
onLang=()=>{if(ME)fillSel();if(CH)render();cmdFormSync();$("#ptitle").textContent=t(TITLES[PG])};
function fillSel(){
  const sel=$("#chsel"),prev=sel.value;sel.innerHTML="";
  ME.channels.forEach(c=>sel.add(new Option(c.name+(c.role==="editor"?" (Mod)":""),c.name)));
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
  $("#livepill").textContent=t(c.live?"Live":"Offline");
  $("#curgame").textContent=c.game?"🎮 "+c.game:"";
  $("#pubbtn").href="/c/"+encodeURIComponent(c.name);
  $("#curtitle").textContent=c.title?"📝 "+c.title:"";
  $("#curtitle").hidden=!c.title;
  document.querySelectorAll(".lchip").forEach(x=>x.classList.toggle("on",x.dataset.bl===(c.lang==="en"?"en":"ar")));
  document.querySelectorAll(".rchip").forEach(x=>x.classList.toggle("on",x.dataset.rm===(c.reminders?"on":"off")));
  $("#langprev").textContent=c.lang==="en"?"@viewer -> Command !hi added successfully ✅":"@viewer تمت إضافة الكوماند !hi بنجاح ✅";
  renderBasic($("#basiclist"));
  $("#role").textContent=t(own?"Streamer":"Mod");
  $("#s-text").textContent=names.length-games;$("#s-game").textContent=games;
  $("#s-mods").textContent=own?c.editors.length:"—";
  const sl=$("#s-link");sl.textContent=t(c.linked?"Linked":"Not linked");sl.className=c.linked?"ok":"bad";
  document.querySelectorAll(".own").forEach(x=>x.hidden=!own||(x.classList.contains("pg")&&x.id!=="p-"+PG));
  renderTop();renderSim();renderCmds();
  if(own)renderOwn();
}
function renderTop(){
  const u=CH.usage||{},k=Object.keys(u).sort((a,b)=>u[b]-u[a]).slice(0,5),max=k.length?u[k[0]]:1,box=$("#topbox");
  box.innerHTML="";
  if(!k.length){box.innerHTML='<p class="empty">'+t("No commands")+'</p>';return}
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
  o.textContent=(c.type==="game"?"Game category changes to: "+c.game+"\n":"")+rep;
}
function renderCmds(){
  const box=$("#cmdlist"),cmds=CH.commands,q=Q.toLowerCase();box.innerHTML="";
  const names=Object.keys(cmds).sort().filter(n=>{
    const c=cmds[n];
    if(FILT!=="all"&&c.type!==FILT)return false;
    return !q||n.includes(q)||(c.reply||"").toLowerCase().includes(q)||(c.game||"").toLowerCase().includes(q);
  });
  if(!names.length){box.innerHTML='<p class="empty">'+t("No commands")+'</p>';return}
  names.forEach(n=>{
    const c=cmds[n],d=document.createElement("div");d.className="cmd";
    d.innerHTML='<div class="cbody"><div class="chead"><b dir="ltr" data-nt></b><span class="bd t" data-nt></span><span class="bd" data-nt></span></div><p data-nt></p></div><div><button class="ic ed">✏️</button><button class="ic del">🗑</button></div>';
    d.querySelector("b").textContent=dn(n,c);
    const bt=d.querySelector(".bd.t");bt.textContent=c.type==="game"?"Game shortcut":"Text reply";
    d.querySelectorAll(".bd")[1].textContent=t(PERMS[c.perm]||"Everyone");
    d.querySelector("p").textContent=c.reply||"";
    d.querySelector(".ed").onclick=()=>{cmdFormFill(n,c);openModal()};
    d.querySelector(".del").onclick=()=>{if(ask("Delete !{n}?",n))act(()=>api("DELETE",base()+"/commands/"+encodeURIComponent(n)),"Deleted")};
    box.appendChild(d);
  });
}
function renderOwn(){
  const c=CH;
  const pt=c.points_timeout||{enabled:false,duration:20,reward_title:"1v1"};
  $("#pt_enabled").checked=!!pt.enabled;
  $("#pt_duration").value=pt.duration||20;
  $("#pt_reward").value=pt.reward_title||"1v1";

  const sr=c.song_queue||[];
  $("#srlist").textContent=sr.length?sr.map((s,i)=>`${i+1}. ${s}`).join("\n"):"No songs in queue. Use !sr [song] in chat.";

  const arBox=$("#arlist");arBox.innerHTML="";
  const ars=c.auto_replies||{};
  Object.keys(AR_LABELS).forEach(k=>{
    const item=ars[k]||{enabled:true,text:""};
    const d=document.createElement("div");d.className="ar-item";
    d.innerHTML='<div class="ar-head"><b>'+AR_LABELS[k]+'</b><label><input type="checkbox" style="width:auto;margin:0"> Enabled</label></div><input type="text" maxlength="450">';
    const chk=d.querySelector("input[type=checkbox]");chk.checked=!!item.enabled;chk.dataset.key=k;
    const inp=d.querySelector("input[type=text]");inp.value=item.text||"";inp.dataset.key=k;
    arBox.appendChild(d);
  });

  const rcfg=c.reminder_cfg||{interval:30,saudi:true,dhikr:true,water:true,water_text:"Drink water!"};
  $("#reminterval").value=rcfg.interval||30;
  $("#remsaudi").checked=!!rcfg.saudi;
  $("#remdhikr").checked=!!rcfg.dhikr;
  $("#remwater").checked=!!rcfg.water;
  $("#remwatertxt").value=rcfg.water_text||"Drink water!";

  const tBox=$("#timerlist");tBox.innerHTML="";
  const timers=c.custom_timers||[];
  if(!timers.length)tBox.innerHTML='<p class="empty">No custom timers</p>';
  timers.forEach(tm=>{
    const d=document.createElement("div");d.className="row col";
    d.innerHTML='<div class="top"><b>'+tm.name+'</b><span><button class="ic tog"></button><button class="ic ed">✏️</button><button class="ic del">🗑</button></span></div><div class="meta">Every '+tm.interval+'m • '+(tm.enabled?"On":"Off")+'</div><p>'+tm.text+'</p>';
    d.querySelector(".tog").onclick=()=>act(()=>api("POST",base()+"/timers",{id:tm.id,name:tm.name,text:tm.text,interval:tm.interval,enabled:!tm.enabled}),"Updated");
    d.querySelector(".ed").onclick=()=>{
      EDIT_TM_ID=tm.id;
      $("#tmname").value=tm.name;$("#tminterval").value=tm.interval;$("#tmtext").value=tm.text;
    };
    d.querySelector(".del").onclick=()=>{if(confirm("Delete timer?"))act(()=>api("DELETE",base()+"/timers/"+encodeURIComponent(tm.id)),"Deleted")};
    tBox.appendChild(d);
  });

  $("#cbotstate").textContent=c.custom_bot?"Custom bot: "+c.custom_bot:"Default bot: "+c.default_bot;
  $("#cbotbtn").href="/auth/custom_bot?ch="+encodeURIComponent(c.name);
  $("#cbotdel").hidden=!c.custom_bot;

  $("#linkstate").textContent=t(c.linked?"Linked: game shortcuts can change stream game.":"Not linked: link Twitch to enable game changing.");
  $("#connect").hidden=!c.twitch;
  $("#unlink").hidden=!c.linked;
  const box=$("#edlist");box.innerHTML="";
  if(!c.editors.length)box.innerHTML='<p class="empty">No mods added</p>';
  c.editors.forEach(n=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<b dir="ltr" data-nt></b><button class="ic">🗑</button>';
    d.querySelector("b").textContent=n;
    d.querySelector("button").onclick=()=>act(()=>api("DELETE",base()+"/editors/"+encodeURIComponent(n)),"Removed");
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
},"Title changed");
document.querySelectorAll(".lchip").forEach(b=>b.onclick=()=>act(()=>api("POST",base()+"/lang",{lang:b.dataset.bl}),"Language updated"));
document.querySelectorAll(".rchip").forEach(b=>b.onclick=()=>act(()=>api("POST",base()+"/reminders",{on:b.dataset.rm==="on"}),"Saved"));
$("#savear").onclick=()=>act(async()=>{
  const payload={};
  document.querySelectorAll("#arlist input[type=checkbox]").forEach(chk=>{
    const k=chk.dataset.key;
    const txt=document.querySelector('#arlist input[type=text][data-key="'+k+'"]').value;
    payload[k]={enabled:chk.checked,text:txt};
  });
  await api("POST",base()+"/auto_replies",payload);
},"Saved");
$("#saveremcfg").onclick=()=>act(()=>api("POST",base()+"/reminder_cfg",{
  interval:parseInt($("#reminterval").value,10)||30,
  saudi:$("#remsaudi").checked,
  dhikr:$("#remdhikr").checked,
  water:$("#remwater").checked,
  water_text:$("#remwatertxt").value
}),"Saved");
$("#addtimer").onclick=()=>act(async()=>{
  await api("POST",base()+"/timers",{
    id:EDIT_TM_ID,name:$("#tmname").value,interval:parseInt($("#tminterval").value,10)||5,text:$("#tmtext").value,enabled:true
  });
  EDIT_TM_ID=null;$("#tmname").value="";$("#tminterval").value="5";$("#tmtext").value="";
},"Saved");
$("#savept").onclick=()=>act(()=>api("POST",base()+"/points_timeout",{
  enabled:$("#pt_enabled").checked,
  duration:parseInt($("#pt_duration").value,10)||20,
  reward_title:$("#pt_reward").value
}),"Saved");
$("#clearsr").onclick=()=>act(()=>api("POST",base()+"/clearsr"),"Cleared");
$("#cbotdel").onclick=()=>{if(confirm("Remove custom bot?"))act(()=>api("POST",base()+"/custom_bot/remove"),"Removed")};
$("#cancelcmd").onclick=closeModal;
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST",base()+"/commands",cmdFormGet());cmdFormClear();closeModal();
},"Saved");
$("#added").onclick=()=>act(async()=>{
  await api("POST",base()+"/editors",{name:$("#newed").value});$("#newed").value="";
},"Mod added");
$("#unlink").onclick=()=>{if(ask("Unlink Twitch?"))act(()=>api("POST",base()+"/unlink"),"Unlinked")};
$("#leave").onclick=()=>{if(ask("Remove the bot from your channel?"))act(()=>api("POST",base()+"/leave"),"Bot removed",true)};
$("#logout").onclick=async()=>{await api("POST","/s/api/logout");onAuth()};
const qp=new URLSearchParams(location.search);
if(qp.get("msg")==="ready")toast("Bot activated successfully ✅");
if(qp.get("err"))toast("Error",1);
if(location.search)history.replaceState(null,"","/s");
initLang();
init();
</script>
</body>
</html>
"""

PUBLIC_HTML = HEAD.replace("{{TITLE}}", "Channel Commands") + r"""
<style>
.wrap{max-width:900px}
.hero{display:flex;align-items:center;gap:16px;padding:20px;border:1px solid var(--line);border-radius:18px;margin-bottom:16px;background:radial-gradient(circle at 100% 0,rgba(145,70,255,.28),transparent 60%),var(--card)}
.av{width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-size:28px;font-weight:700;flex-shrink:0}
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
.sec{margin-top:22px}
</style>
<div class="wrap">
  <div class="hero">
    <div class="av" id="av"></div>
    <div class="info">
      <h1 id="chname" dir="ltr" data-nt></h1>
      <div class="sub"><span class="pill" id="live" hidden></span><span class="mut" id="cnt" data-nt></span></div>
    </div>
    <button class="btn ghost langbtn" data-nt>عربي</button>
  </div>
  <div class="card" id="nf" hidden><p class="mut" style="margin:0" data-nt>Channel not found</p></div>
  <div id="box">
    <div class="tool">
      <input id="q" placeholder="Search commands" data-nt>
      <button class="chip on" data-f="all" data-nt>All types</button>
      <button class="chip" data-f="text" data-nt>Replies</button>
      <button class="chip" data-f="game" data-nt>Games</button>
    </div>
    <div class="grid" id="list"></div>
    <div class="card sec">
      <h3 data-nt>Core chat commands</h3>
      <div id="basiclist"></div>
    </div>
  </div>
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
  const lp=$("#live");lp.hidden=false;lp.className="pill"+(D.live?" live":"");lp.textContent=t(D.live?"Live":"Offline");
  const all=Object.keys(D.commands).sort(),q=Q.toLowerCase();
  $("#cnt").textContent=all.length+" commands";
  const box=$("#list");box.innerHTML="";
  const names=all.filter(n=>{
    const c=D.commands[n];
    if(FILT!=="all"&&c.type!==FILT)return false;
    return !q||n.includes(q)||(c.reply||"").toLowerCase().includes(q)||(c.game||"").toLowerCase().includes(q);
  });
  if(!names.length){box.innerHTML='<p class="empty" style="grid-column:1/-1">No commands match your search</p>';}
  names.forEach(n=>{
    const c=D.commands[n],d=document.createElement("div");d.className="cc";
    d.innerHTML='<div class="h"><b dir="ltr" data-nt></b><span class="bd" data-nt></span></div><div class="meta" data-nt></div><p data-nt></p>';
    const nm=(c.bang===false?"":"!")+n,b=d.querySelector("b");
    b.textContent=nm;b.onclick=()=>copyText(nm);
    d.querySelector(".bd").textContent=t(PERMS[c.perm]||"Everyone");
    d.querySelector(".meta").textContent=c.type==="game"?"Game shortcut":"Text reply";
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

STREAMER_HTML = (STREAMER_HTML.replace("{{FORM}}", CMD_FORM.replace("{{TOP}}", ""))
                 .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))
PUBLIC_HTML = PUBLIC_HTML.replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS)

SESSION_TOKEN = (
    hashlib.sha256(("dash:" + DASHBOARD_PASSWORD).encode()).hexdigest()
    if DASHBOARD_PASSWORD else None
)
ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="24" fill="#9146ff"/><text x="50" y="68" font-size="56" text-anchor="middle">🤖</text></svg>'
MANIFEST = {"name": "Bot Dashboard", "short_name": "Bot", "start_url": "/", "display": "standalone"}


def make_web_app(bot):
  store = bot.store
  twitch = bot.twitch
  redirect_uri = SITE_URL + "/auth/callback"

  async def eventsub_hook(request):
    raw = await request.read()
    h = request.headers
    mid = h.get("Twitch-Eventsub-Message-Id", "")
    ts = h.get("Twitch-Eventsub-Message-Timestamp", "")
    sig = h.get("Twitch-Eventsub-Message-Signature", "")
    mine = "sha256=" + hmac.new(EVENTSUB_SECRET.encode(), mid.encode() + ts.encode() + raw, hashlib.sha256).hexdigest()
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
      sub_type = (body.get("subscription") or {}).get("type", "")
      event_data = body.get("event") or {}
      if sub_type == "channel.chat.message":
        asyncio.create_task(bot.on_chat_event(mid, event_data))
      elif sub_type == "channel.channel_points_custom_reward_redemption.add":
        asyncio.create_task(bot.on_reward_redemption(event_data))
    return web.Response(status=204)

  async def auth_callback(request):
    q = request.query
    state_val = q.get("state", "")
    cookie = request.cookies.get("ostate", "")
    if not state_val or not hmac.compare_digest(state_val.encode(), cookie.encode()):
      return web.Response(text="Session expired", status=400)
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

    if state_val.startswith("x"):
      target_ch = request.cookies.get("cbot_ch", "").lower()
      sess_login = read_session(request.cookies.get("ssess", ""))
      store.data.setdefault("custom_bots", {})[target_ch] = {"login": login_name, "user_id": str(user["id"])}
      await store.save()
      resp = web.HTTPFound("/s?msg=cbot")
      resp.del_cookie("ostate")
      resp.del_cookie("cbot_ch")
      raise resp

    dest = "/s"
    if login_name not in store.data["banned"]:
      if login_name not in store.data["channels"] and SELF_JOIN and valid_channel(login_name):
        store.data["channels"].append(login_name)
        await store.save()
        await bot.join_channels([login_name])
      store.data["tokens"][login_name] = {"refresh": tok["refresh_token"], "user_id": user["id"]}
      twitch.user_access[login_name] = (tok["access_token"], time.time() + tok.get("expires_in", 3600))
      await store.save()
      await bot.join_channels([login_name])
      dest = "/s?msg=ready"
    resp = web.HTTPFound(dest)
    resp.set_cookie("ssess", make_session(login_name), max_age=60*60*24*30, httponly=True, samesite="Lax")
    resp.del_cookie("ostate")
    raise resp

  def role_of(login, ch):
    if ch not in store.data["channels"]:
      return None
    if login == ch:
      return "owner"
    if login in store.data["editors"].get(ch, []):
      return "editor"
    return None

  def access(request, owner_only=False):
    login = read_session(request.cookies.get("ssess", ""))
    if not login:
      return None, web.json_response({"error": "unauthorized"}, status=401)
    ch = request.match_info["channel"].lower()
    r = role_of(login, ch)
    if not r or (owner_only and r != "owner"):
      return None, web.json_response({"error": "forbidden"}, status=403)
    return (login, ch, r), None

  app = web.Application()
  r = app.router

  # Fix for lambda routing issues: Defined using standard async functions instead of inline lambdas with tuples
  async def handle_streamer_auth(req):
    sv = secrets.token_urlsafe(16)
    target_url = AUTH_URL + "?" + urlencode({"client_id": CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code", "state": sv, "scope": SCOPES["s"]})
    resp = web.HTTPFound(target_url)
    resp.set_cookie("ostate", sv, max_age=600, httponly=True)
    return resp

  async def handle_connect_auth(req):
    sv = secrets.token_urlsafe(16)
    target_url = AUTH_URL + "?" + urlencode({"client_id": CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code", "state": sv, "scope": SCOPES["c"]})
    resp = web.HTTPFound(target_url)
    resp.set_cookie("ostate", sv, max_age=600, httponly=True)
    return resp

  async def handle_custom_bot_auth(req):
    sv = "x" + secrets.token_urlsafe(16)
    target_url = AUTH_URL + "?" + urlencode({"client_id": CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code", "state": sv, "scope": SCOPES["cb"], "force_verify": "true"})
    resp = web.HTTPFound(target_url)
    resp.set_cookie("ostate", sv, max_age=600, httponly=True)
    resp.set_cookie("cbot_ch", req.query.get("ch", "").lower(), max_age=600, httponly=True)
    return resp

  async def handle_logout(req):
    resp = web.json_response({"ok": True})
    resp.del_cookie("ssess")
    return resp

  async def handle_me(req):
    login = read_session(req.cookies.get("ssess", "")) or "user"
    channels = [{"name": c, "role": role_of(login, c)} for c in store.data["channels"] if role_of(login, c)]
    return web.json_response({"login": login, "channels": channels})

  r.add_get("/s", lambda req: web.Response(text=STREAMER_HTML, content_type="text/html"))
  r.add_get("/c/{channel}", lambda req: web.Response(text=PUBLIC_HTML, content_type="text/html"))
  r.add_get("/pub/{channel}", lambda req: web.json_response({"name": req.match_info["channel"], "live": False, "commands": store.data["commands"].get(req.match_info["channel"].lower(), {})}))
  r.add_get("/manifest.json", lambda req: web.json_response(MANIFEST))
  r.add_get("/icon.svg", lambda req: web.Response(text=ICON_SVG, content_type="image/svg+xml"))
  r.add_post("/eventsub", eventsub_hook)
  
  r.add_get("/auth/streamer", handle_streamer_auth)
  r.add_get("/auth/connect", handle_connect_auth)
  r.add_get("/auth/custom_bot", handle_custom_bot_auth)
  r.add_get("/auth/callback", auth_callback)
  
  r.add_post("/s/api/logout", handle_logout)
  r.add_get("/s/api/me", handle_me)
  
  async def s_channel(req):
    a, err = access(req)
    if err: return err
    _, ch, role = a
    game, title = None, None
    if twitch.enabled:
      try: game, title = await twitch.channel_info(ch)
      except: pass
    cb = store.data.get("custom_bots", {}).get(ch)
    return web.json_response({
        "name": ch, "role": role, "live": await bot.is_channel_live(ch),
        "game": game, "title": title, "twitch": twitch.enabled, "linked": ch in store.data["tokens"],
        "commands": store.data["commands"].get(ch, {}),
        "editors": store.data["editors"].get(ch, []) if role == "owner" else [],
        "usage": bot.usage.get(ch, {}), "lang": store.data["lang"].get(ch, "ar"),
        "reminders": bool(store.data["reminders"].get(ch, False)),
        "reminder_cfg": store.get_reminder_cfg(ch) if role == "owner" else {},
        "custom_timers": store.get_custom_timers(ch) if role == "owner" else {},
        "auto_replies": store.get_auto_replies(ch) if role == "owner" else {},
        "song_queue": store.data.get("song_requests", {}).get(ch, []),
        "points_timeout": store.get_points_timeout(ch),
        "custom_bot": cb.get("login") if isinstance(cb, dict) else None,
        "default_bot": BOT_LOGIN,
    })
  r.add_get("/s/api/channel/{channel}", s_channel)

  async def s_save_cmd(req):
    a, err = access(req)
    if err: return err
    _, ch, _ = a
    try: name, entry = build_command(await req.json())
    except ValueError as e: return web.json_response({"error": str(e)}, status=400)
    store.data["commands"].setdefault(ch, {})[name] = entry
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/commands", s_save_cmd)

  async def s_del_cmd(req):
    a, err = access(req)
    if err: return err
    _, ch, _ = a
    store.data["commands"].get(ch, {}).pop(req.match_info["name"].lower(), None)
    await store.save()
    return web.json_response({"ok": True})
  r.add_delete("/s/api/channel/{channel}/commands/{name}", s_del_cmd)

  async def s_title(req):
    a, err = access(req)
    if err: return err
    _, ch, _ = a
    await twitch.set_title(ch, (await req.json()).get("title", ""))
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/title", s_title)

  async def s_lang(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    store.data["lang"][ch] = (await req.json()).get("lang", "ar")
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/lang", s_lang)

  async def s_reminders(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    store.data["reminders"][ch] = bool((await req.json()).get("on"))
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/reminders", s_reminders)

  async def s_reminder_cfg(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    b = await req.json()
    store.data.setdefault("reminder_cfg", {})[ch] = {
        "interval": max(1, min(180, int(b.get("interval", 30)))),
        "saudi": bool(b.get("saudi", True)),
        "dhikr": bool(b.get("dhikr", True)),
        "water": bool(b.get("water", True)),
        "water_text": str(b.get("water_text", "")).strip()[:450] or "Drink water!",
    }
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/reminder_cfg", s_reminder_cfg)

  async def s_save_timer(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    b = await req.json()
    timers = store.data.setdefault("custom_timers", {}).setdefault(ch, [])
    tid = str(b.get("id") or "").strip()
    tm_data = {"id": tid or secrets.token_hex(4), "name": str(b.get("name",""))[:40], "interval": int(b.get("interval",5)), "text": str(b.get("text",""))[:450], "enabled": b.get("enabled") is not False}
    if tid:
      for i, t in enumerate(timers):
        if t.get("id") == tid: timers[i] = tm_data; break
      else: timers.append(tm_data)
    else: timers.append(tm_data)
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/timers", s_save_timer)

  async def s_del_timer(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    store.data["custom_timers"][ch] = [t for t in store.data.get("custom_timers", {}).get(ch, []) if t.get("id") != req.match_info["id"]]
    await store.save()
    return web.json_response({"ok": True})
  r.add_delete("/s/api/channel/{channel}/timers/{id}", s_del_timer)

  async def s_auto_replies(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    b = await req.json()
    ar_map = store.data.setdefault("auto_replies", {}).setdefault(ch, {})
    for k, dv in DEFAULT_AUTO_REPLIES.items():
      if k in b and isinstance(b[k], dict):
        ar_map[k] = {"enabled": bool(b[k].get("enabled", True)), "text": str(b[k].get("text",""))[:450] or dv["text"]}
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/auto_replies", s_auto_replies)

  async def s_points_timeout(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    b = await req.json()
    store.data.setdefault("points_timeout", {})[ch] = {
        "enabled": bool(b.get("enabled", False)),
        "duration": int(b.get("duration", 20)),
        "reward_title": str(b.get("reward_title", "1v1")).strip(),
    }
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/points_timeout", s_points_timeout)

  async def s_clearsr(req):
    a, err = access(req)
    if err: return err
    _, ch, _ = a
    store.data.setdefault("song_requests", {})[ch] = []
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/clearsr", s_clearsr)

  async def s_custom_bot_remove(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    store.data.get("custom_bots", {}).pop(ch, None)
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/custom_bot/remove", s_custom_bot_remove)

  async def s_leave(req):
    a, err = access(req, True)
    if err: return err
    _, ch, _ = a
    store.data["channels"].remove(ch)
    store.data["tokens"].pop(ch, None)
    store.data.get("custom_bots", {}).pop(ch, None)
    await store.save()
    return web.json_response({"ok": True})
  r.add_post("/s/api/channel/{channel}/leave", s_leave)

  return app


async def start_web_server(bot):
  runner = web.AppRunner(make_web_app(bot))
  await runner.setup()
  port = int(os.environ.get("PORT", 10000))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


class Bot:

  def __init__(self):
    self.store = Store()
    self.twitch = TwitchAPI(self.store)
    self.nick = BOT_LOGIN
    self.last_dhikr = None
    self.last_saudi_prayer = None
    self.live_cache = {}
    self.usage = {}
    self.seen = {}
    self.rem_state = {}
    self.timer_last = {}

  def run(self):
    loop = asyncio.get_event_loop()
    loop.create_task(self.start())
    loop.run_forever()

  async def start(self):
    await self.store.load()
    if OWNER not in self.store.data["channels"]:
      self.store.data["channels"].append(OWNER)
    asyncio.create_task(start_web_server(self))
    asyncio.create_task(self.periodic_reminders())

  async def join_channels(self, names):
    for n in names:
      await self.twitch.subscribe_chat(n)

  async def is_channel_live(self, channel_name):
    now = time.time()
    cached = self.live_cache.get(channel_name)
    if cached and now - cached[0] < LIVE_CACHE_SECONDS:
      return cached[1]
    live = await self.twitch.is_live(channel_name)
    self.live_cache[channel_name] = (now, live)
    return live

  def get_random_dhikr(self):
    return random.choice(DHIKR_LIST)

  def get_random_saudi_prayer(self):
    return random.choice(SAUDI_PRAYERS)

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
        channel = self.twitch
        if rem_on:
          cfg = self.store.get_reminder_cfg(channel_name)
          pool = []
          if cfg["saudi"]: pool.append(f"اللهم صلِّ وسلم على نبينا محمد، {self.get_random_saudi_prayer()}")
          if cfg["dhikr"]: pool.append(self.get_random_dhikr())
          if cfg["water"]: pool.append(cfg["water_text"])
          if pool:
            st = self.rem_state.setdefault(channel_name, {"last": now, "step": 0})
            if now - st["last"] >= cfg["interval"] * 60:
              msg_text = pool[st["step"] % len(pool)]
              st["step"] = (st["step"] + 1) % len(pool)
              st["last"] = now
              await channel.chat_send(channel_name, msg_text)
        for tm in timers:
          tid = tm.get("id")
          if not tid: continue
          key = (channel_name, tid)
          if key not in self.timer_last:
            self.timer_last[key] = now
            continue
          iv_sec = max(1, int(tm.get("interval", 5))) * 60
          if now - self.timer_last[key] >= iv_sec:
            self.timer_last[key] = now
            txt = format_response(tm.get("text", ""), channel_name, channel_name, channel_name)
            if txt:
              await channel.chat_send(channel_name, txt[:490])

  async def on_reward_redemption(self, event):
    ch = (event.get("broadcaster_user_login") or "").lower()
    user = (event.get("user_login") or "").lower()
    reward_title = (event.get("reward") or {}).get("title", "")
    pt = self.store.get_points_timeout(ch)
    if pt["enabled"] and reward_title.lower() == pt["reward_title"].lower():
      dur = pt["duration"]
      await self.twitch.timeout_user(ch, user, dur, f"Channel points redemption: {reward_title}")
      await self.twitch.chat_send(ch, f"@{user} lost the challenge ({reward_title}) and received a {dur}s timeout!")

  async def on_chat_event(self, mid, ev):
    who = (ev.get("chatter_user_login") or "").lower()
    chan = (ev.get("broadcaster_user_login") or "").lower()
    content = ((ev.get("message") or {}).get("text") or "").strip()
    if who == self.nick or who in KNOWN_BOTS:
      return

    # Nightbot song requests
    if content.startswith("!sr "):
      song = content[4:].strip()
      if song:
        queue = self.store.data.setdefault("song_requests", {}).setdefault(chan, [])
        queue.append(f"{song} ( requested by @{who} )")
        await self.twitch.chat_send(chan, f"@{who} Added to song queue: {song}")
      return
    elif content in ("!song", "!currentsong"):
      queue = self.store.data.get("song_requests", {}).get(chan, [])
      if queue:
        await self.twitch.chat_send(chan, f"Current song: {queue[0]}")
      else:
        await self.twitch.chat_send(chan, "No song currently playing in queue.")
      return
    elif content == "!skipsong":
      queue = self.store.data.get("song_requests", {}).get(chan, [])
      if queue:
        skipped = queue.pop(0)
        await self.twitch.chat_send(chan, f"Skipped: {skipped}")
      else:
        await self.twitch.chat_send(chan, "Song queue is empty.")
      return

    # Quotes
    if content == "!quote":
      quotes = self.store.data.get("quotes", {}).get(chan, [])
      if quotes:
        q = random.choice(quotes)
        await self.twitch.chat_send(chan, f"Quote: {q}")
      else:
        await self.twitch.chat_send(chan, "No quotes saved yet. Use !addquote [text]")
      return
    elif content.startswith("!addquote "):
      q_text = content[10:].strip()
      if q_text:
        quotes = self.store.data.setdefault("quotes", {}).setdefault(chan, [])
        quotes.append(q_text)
        await self.store.save()
        await self.twitch.chat_send(chan, f"Quote added successfully! (#{len(quotes)})")
      return

    # Custom / Standard commands
    channel_cmds = self.store.data["commands"].get(chan, {})
    if content.startswith("!"):
      parts = content.split(maxsplit=2)
      cmd = parts[0][1:].lower()
      entry = channel_cmds.get(cmd)
      if entry:
        target = parts[1].lstrip("@") if len(parts) > 1 else ""
        text = format_response(entry["reply"], who, chan, target)
        await self.twitch.chat_send(chan, text[:490])
        return

    # Auto replies for greetings (Salam / Back / BRB)
    if await self.is_live(chan):
      ars = self.store.get_auto_replies(chan)
      content_l = content.lower()
      has_evening = "مساء الخير" in content_l
      has_greeting = "السلام عليكم" in content_l or "سلام عليكم" in content_l or content_l.startswith("سلام")
      key_matched = None
      if has_greeting and has_evening: key_matched = "salam_evening"
      elif has_evening: key_matched = "evening"
      elif content_l == "باك": key_matched = "back"
      elif content_l in ("brb", "برب"): key_matched = "brb"
      elif has_greeting: key_matched = "salam"

      if key_matched:
        cfg = ars.get(key_matched)
        if cfg and cfg.get("enabled"):
          raw = cfg["text"]
          msg = format_response(raw, f"@{who}", chan, f"@{who}")
          await self.twitch.chat_send(chan, msg[:490])


if __name__ == "__main__":
  bot = Bot()
  bot.run()
