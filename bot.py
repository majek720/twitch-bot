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
from datetime import datetime, timezone
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

# موقع الستريمرز (تسجيل دخول بتويتش + تغيير اللعبة) + EventSub (كلها مطلوبة الحين)
CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "")
SITE_URL = (os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
SELF_JOIN = os.environ.get("SELF_JOIN", "1") != "0"  # الستريمر يفعّل البوت بنفسه (ضع 0 لإيقافه)
SECRET = (os.environ.get("SESSION_SECRET") or CLIENT_SECRET or "").encode()

OWNER = "majek113"
IGNORED_USERS = set()
DEFAULT_CHANNELS = ["majek113", "teamiik", "iz0yi", "vul1_", "lyorll"]

# بوتات معروفة: البوت ما يرد عليها أبداً (يمنع حلقات الردود بين البوتات)
KNOWN_BOTS = {
    "nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "wizebot",
    "soundalerts", "pretzelrocks", "commanderroot", "anotherttvviewer",
    "blerp", "botrix", "sery_bot", "coebot", "deepbot", "ankhbot", "stay_hydrated_bot",
}

DATA_FILE = "bot_data.json"
USER_COOLDOWN = 15
COMMAND_COOLDOWN = 5
LIVE_CACHE_SECONDS = 60

# الرسائل المجدولة (الأدعية والتذكيرات): أقل مدة وأكثر مدة بالدقائق، وأقصى عدد لكل قناة
MIN_TIMER_MINUTES = 5
MAX_TIMER_MINUTES = 1440
MAX_TIMERS = 20

# حدود الإرسال (تويتش: 20 رسالة كل 30 ثانية لكل قناة، نبقى تحتها بمسافة أمان)
SEND_MIN_GAP = 1.2  # أقل فاصل بين رسالتين في نفس القناة (ثواني)
SEND_WINDOW = 30
SEND_MAX_PER_WINDOW = 15
SEND_QUEUE_MAX = 15  # لو تكدست أكثر من كذا، الرسائل الجديدة تنتجاهل
SEND_STALE = 45  # رسالة علقت في الطابور أكثر من كذا ما تنرسل (قديمة)

# احتياطي IRC: للقنوات اللي ما أعطت البوت صلاحية (بدون شارة بوت). اختياري: ضع TWITCH_TOKEN في Render
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

# الصلاحيات حسب نوع الدخول: s/c = ستريمر، b = حساب البوت نفسه
FOLLOWERS_SCOPE = "moderator:read:followers"  # لكوماند !followage
BOT_MOD_SCOPES = "moderator:manage:chat_messages moderator:manage:banned_users"  # للحماية من السبام
BOT_SCOPES = "user:bot user:read:chat user:write:chat " + BOT_MOD_SCOPES
SCOPES = {
    "s": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE} {FOLLOWERS_SCOPE}",
    "c": f"{GAME_SCOPE} {MOD_SCOPE} {CHANNEL_BOT_SCOPE} {FOLLOWERS_SCOPE}",
    "b": BOT_SCOPES,  # حساب البوت الافتراضي
    "m": BOT_SCOPES,  # حساب بوت يختاره الستريمر لقناته
}

# مستويات الصلاحيات: كل مستوى يشمل اللي فوقه
PERMS = {"everyone": 0, "sub": 1, "vip": 2, "mod": 3, "broadcaster": 4}

# كوماندات البوت الأساسية (ما تنفع كأسماء لكوماندات مخصصة)
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

# الردود التلقائية الافتراضية: المفتاح -> (الاسم، النص الافتراضي، متى يشتغل)
# الستريمر يقدر يعدل النص أو يحذف الرد (تعطيله) من موقع الستريمر
AUTO_DEFAULTS = {
    "salam": ("رد السلام", "وعليكم السلام ورحمة الله وبركاته، نورت البث",
              "لما أحد يكتب: السلام عليكم"),
    "evening": ("رد مساء الخير", "مساء النور",
                "لما أحد يكتب: مساء الخير"),
    "both": ("رد السلام ومساء الخير معاً", "وعليكم السلام ورحمة الله وبركاته، ومساء النور نورت البث",
             "لما أحد يكتب السلام عليكم ومساء الخير في نفس الرسالة"),
    "back": ("رد باك", "ولكم باك", "لما أحد يبدأ رسالته بكلمة: باك"),
    "brb": ("رد برب", "خذ راحتك بس لا تطول علينا", "لما أحد يبدأ رسالته بكلمة: برب أو brb"),
}


def default_timers():
  """الرسائل المجدولة الافتراضية (نفس سلوك البوت القديم: كل 90 دقيقة لكل نوع، بفاصل نصف ساعة بينها)."""
  return [
      {"id": "saudi", "kind": "saudi", "text": "", "every": 90, "on": True, "delay": 30},
      {"id": "dhikr", "kind": "dhikr", "text": "", "every": 90, "on": True, "delay": 60},
      {"id": "water", "kind": "text", "text": "اشربوا ماااااااي", "every": 90, "on": True, "delay": 90},
  ]


# إعدادات طلبات الأغاني والفلاتر الافتراضية (لكل قناة)
SR_DEFAULT = {"on": False, "per_user": 3, "max_queue": 30, "max_minutes": 10, "perm": "everyone"}
FILTER_DEFAULT = {
    "links": False, "caps": False, "symbols": False, "repeat": False, "long": False,
    "words": [], "allowed": [], "timeout": 10, "warn": True, "exempt_sub": True, "exempt_vip": True,
}

user_reply_time = {}

# ============================================================
# رسائل الكوماندات الأساسية: (عربي، إنجليزي) والستريمر يختار من الموقع
# ============================================================
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
    # followage / accountage / uptime / game / title
    "fa": ("تتابع {c} من {d}", "You've been following {c} for {d}"),
    "fa_other": ("{u} يتابع {c} من {d}", "{u} has been following {c} for {d}"),
    "fa_none": ("ما تتابع القناة", "You don't follow this channel"),
    "fa_none_other": ("{u} ما يتابع القناة", "{u} doesn't follow this channel"),
    "fa_streamer": ("هذا صاحب القناة 😄", "That's the channel owner 😄"),
    "aa": ("عمر حسابك في تويتش {d}", "Your Twitch account is {d} old"),
    "aa_other": ("عمر حساب {u} في تويتش {d}", "{u}'s Twitch account is {d} old"),
    "up": ("البث شغال من {d}", "The stream has been live for {d}"),
    "up_off": ("القناة أوفلاين الحين", "The channel is offline right now"),
    "game_now": ("اللعبة الحالية: {g}", "Current game: {g}"),
    "game_none": ("ما قدرت أعرف المعلومة الحين", "I couldn't get that right now"),
    "title_now": ("عنوان البث: {t}", "Stream title: {t}"),
    "no_user": ("ما لقيت مستخدم باسم {u}", "I couldn't find a user named {u}"),
    # طلبات الأغاني
    "sr_off": ("طلبات الأغاني مو مفعّلة في هذي القناة", "Song requests aren't enabled in this channel"),
    "sr_usage": ("الصيغة: !sr رابط يوتيوب أو سبوتيفاي أو اسم الأغنية", "Usage: !sr YouTube/Spotify link or song name"),
    "sr_need_link": ("اكتب رابط أغنية من يوتيوب أو سبوتيفاي", "Please send a YouTube or Spotify song link"),
    "sr_sp_type": ("أرسل رابط أغنية وحدة من سبوتيفاي (مو ألبوم ولا بلايليست)",
                   "Please send a single Spotify track link (not an album or playlist)"),
    "sr_nf": ("ما لقيت الأغنية أو ما تنفع", "I couldn't find that song or it can't be played"),
    "sr_full": ("الطابور ممتلئ", "The queue is full"),
    "sr_user_max": ("وصلت الحد الأقصى من الطلبات ({n})", "You've reached the request limit ({n})"),
    "sr_long": ("الأغنية طويلة، الحد الأقصى {n} دقيقة", "That song is too long, the max is {n} minutes"),
    "sr_dup": ("الأغنية موجودة بالطابور", "That song is already in the queue"),
    "sr_added": ("تمت إضافة {s} للطابور (رقم {p})", "{s} was added to the queue (#{p})"),
    "sr_noperm": ("ما عندك صلاحية تطلب أغاني", "You can't request songs here"),
    "song_now": ("الأغنية الحالية: {s} (طلب {u})", "Now playing: {s} (requested by {u})"),
    "song_none": ("ما فيه أغنية تشتغل الحين", "Nothing is playing right now"),
    "queue_list": ("القادم: {l} | الطابور كامل: {u}", "Up next: {l} | Full queue: {u}"),
    "queue_empty": ("الطابور فاضي", "The queue is empty"),
    "skipped": ("تم تخطي الأغنية ⏭", "Song skipped ⏭"),
    "wrong_ok": ("شلت أغنيتك {s}", "Removed your song {s}"),
    "wrong_none": ("ما عندك أغاني بالطابور", "You have no songs in the queue"),
    "sr_cleared": ("تم مسح الطابور ✅", "The queue has been cleared"),
    # الحماية من السبام
    "permit_ok": ("{u} يقدر ينشر روابط لمدة دقيقة", "{u} can post links for one minute"),
    "permit_usage": ("الصيغة: !permit اسم_المشاهد", "Usage: !permit username"),
    "f_links": ("ممنوع نشر الروابط", "Links aren't allowed"),
    "f_caps": ("خفّف الحروف الكبيرة", "Please ease up on caps"),
    "f_symbols": ("خفّف الرموز", "Too many symbols"),
    "f_repeat": ("لا تكرر الحروف", "Don't repeat characters"),
    "f_long": ("الرسالة طويلة", "Message too long"),
    "f_words": ("كلمة ممنوعة في هذي القناة", "That word isn't allowed here"),
}


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
        "lang": {},  # قناة -> "ar" أو "en" للغة ردود الكوماندات الأساسية
        "reminders": {c: True for c in DEFAULT_CHANNELS},  # قناة -> الرسائل الدورية شغالة؟
        "timers": {},  # قناة -> قائمة الرسائل المجدولة (أدعية، تذكيرات...)
        "autos": {},  # قناة -> تعديلات الردود التلقائية (السلام، باك، برب...)
        "botacct": {},  # قناة -> حساب بوت اختاره الستريمر {login, id, refresh}
        "bot_auth": {},  # توكن حساب البوت الافتراضي (لحذف الرسائل والكتم)
        "reports": [],  # البلاغات اللي توصل من الموقع
        "report_bans": {},  # ممنوعين من إرسال البلاغات: هوية -> اسم
        "sr": {},  # قناة -> إعدادات طلبات الأغاني
        "filters": {},  # قناة -> إعدادات الحماية من السبام
        "counts": {},  # قناة -> عدادات $(count)
    }

  @property
  def use_gist(self):
    return bool(GITHUB_TOKEN and GIST_ID)

  def timers(self, ch):
    """الرسائل المجدولة للقناة. أول مرة تنبني من الرسائل الافتراضية."""
    d = self.data["timers"]
    if ch not in d:
      d[ch] = default_timers()
    return d[ch]

  def autos(self, ch):
    return self.data["autos"].setdefault(ch, {})

  def sr(self, ch):
    d = self.data["sr"].setdefault(ch, {})
    for k, v in SR_DEFAULT.items():
      d.setdefault(k, v)
    return d

  def filters(self, ch):
    d = self.data["filters"].setdefault(ch, {})
    for k, v in FILTER_DEFAULT.items():
      d.setdefault(k, list(v) if isinstance(v, list) else v)
    return d

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
      self.data["lang"] = loaded.get("lang", {})
      self.data["timers"] = loaded.get("timers", {})
      self.data["autos"] = loaded.get("autos", {})
      for k in ("botacct", "bot_auth", "report_bans", "sr", "filters", "counts"):
        self.data[k] = loaded.get(k, {})
      self.data["reports"] = loaded.get("reports", [])
      if "reminders" in loaded:
        self.data["reminders"] = loaded["reminders"]
      else:
        # أول تشغيل بعد الترقية: القنوات الحالية تبقى على وضعها (شغالة)، والجديدة تبدأ متوقفة
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
# Twitch API (تغيير اللعبة + تسجيل دخول الستريمرز + الشات عبر EventSub)
# ============================================================
class TwitchAPI:

  def __init__(self, store):
    self.store = store
    self.app_token = None
    self.app_exp = 0
    self.user_access = {}  # قناة -> (access_token, وقت الانتهاء)
    self.user_ids = {}
    self.lock = asyncio.Lock()
    self.sent_ids = {}  # معرفات رسائل البوت اللي أرسلها (عشان ما يرد على نفسه)

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
    """يرجع (اللعبة الحالية، عنوان البث)."""
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
    """يرجع (نجح؟، كود الخطأ): disabled / not_linked / expired / refused"""
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
    """يرجع (نجح؟، اسم اللعبة أو كود الخطأ)."""
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
    """يرجع (نجح؟، العنوان الجديد أو كود الخطأ)."""
    title = title.strip()[:140]
    ok, err = await self._patch_channel(channel, {"title": title})
    return (True, title) if ok else (False, err)

  # ---------- الشات عبر EventSub + Send Chat Message API ----------
  async def is_live(self, login):
    if not self.enabled:
      return False
    st, d = await self.call("GET", "streams", await self.get_app_token(),
                            params={"user_login": login})
    return st == 200 and bool(d.get("data"))

  async def chat_send(self, channel, text):
    """يرسل رسالة بالـ API (بتوكن التطبيق) عشان تظهر شارة البوت."""
    if not self.enabled:
      return False, "disabled"
    token = await self.get_app_token()
    bid = await self.user_id(channel)
    _, sid = await self.bot_ident(channel)
    if not (token and bid and sid):
      return False, "ids"
    st, d = await self.call("POST", "chat/messages", token, body={
        "broadcaster_id": bid, "sender_id": sid, "message": text[:490]})
    if st == 401:
      self.app_token = None
    if st == 200 and d.get("data") and d["data"][0].get("is_sent"):
      if d["data"][0].get("message_id"):
        self.sent_ids[d["data"][0]["message_id"]] = time.time()
      return True, ""
    drop = ""
    if st == 200 and d.get("data"):
      drop = str((d["data"][0].get("drop_reason") or {}).get("message", ""))
    return False, f"{st} {d.get('message') or drop or d.get('data')}"

  async def subscribe_chat(self, channel):
    """يشترك في رسائل شات القناة (EventSub) باسم البوت."""
    if not self.enabled:
      return False, "disabled"
    token = await self.get_app_token()
    bid = await self.user_id(channel)
    _, sid = await self.bot_ident(channel)
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
    """يخلي البوت مود في القناة (400 = مود أو VIP من قبل)."""
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

  # ---------- حساب البوت لكل قناة (الافتراضي أو حساب اختاره الستريمر) ----------
  def bot_login(self, channel):
    a = self.store.data["botacct"].get(channel)
    return a["login"] if a else BOT_LOGIN

  async def bot_ident(self, channel):
    """يرجع (يوزر البوت، آيدي البوت) للقناة."""
    a = self.store.data["botacct"].get(channel)
    if a:
      return a["login"], a["id"]
    return BOT_LOGIN, await self.user_id(BOT_LOGIN)

  async def bot_user_token(self, channel):
    """توكن حساب البوت نفسه (لحذف الرسائل والكتم). يحتاج ربط حساب البوت بالصلاحيات الجديدة."""
    a = self.store.data["botacct"].get(channel)
    info = a if a else self.store.data["bot_auth"]
    refresh = (info or {}).get("refresh")
    if not refresh:
      return None
    key = "bot:" + (a["login"] if a else BOT_LOGIN)
    cached = self.user_access.get(key)
    if cached and time.time() < cached[1] - 60:
      return cached[0]
    async with self.lock:
      cached = self.user_access.get(key)
      if cached and time.time() < cached[1] - 60:
        return cached[0]
      st, d = await self.form(TOKEN_URL, {
          "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
          "grant_type": "refresh_token", "refresh_token": refresh,
      })
      if st != 200 or "access_token" not in d:
        return None
      self.user_access[key] = (d["access_token"], time.time() + d.get("expires_in", 3600))
      if d.get("refresh_token") and d["refresh_token"] != refresh:
        info["refresh"] = d["refresh_token"]
        await self.store.save()
      return d["access_token"]

  async def user_info(self, login):
    st, d = await self.call("GET", "users", await self.get_app_token(), params={"login": login})
    if st == 200 and d.get("data"):
      return d["data"][0]
    return None

  async def stream_info(self, login):
    st, d = await self.call("GET", "streams", await self.get_app_token(), params={"user_login": login})
    if st == 200 and d.get("data"):
      return d["data"][0]
    return None

  async def followed_at(self, channel, user_id):
    """يرجع (تاريخ المتابعة، كود الخطأ): not_linked / expired / refused / not_following"""
    info = self.store.data["tokens"].get(channel)
    if not info:
      return None, "not_linked"
    token = await self.user_token(channel)
    if not token:
      return None, "expired"
    st, d = await self.call("GET", "channels/followers", token, params={
        "broadcaster_id": info["user_id"], "user_id": user_id})
    if st == 200:
      if d.get("data"):
        return d["data"][0].get("followed_at"), ""
      return None, "not_following"
    if st in (401, 403):
      return None, "expired"
    return None, "refused"

  async def delete_message(self, channel, message_id):
    token = await self.bot_user_token(channel)
    bid = await self.user_id(channel)
    _, sid = await self.bot_ident(channel)
    if not (token and bid and sid and message_id):
      return False
    st, _ = await self.call("DELETE", "moderation/chat", token, params={
        "broadcaster_id": bid, "moderator_id": sid, "message_id": message_id})
    return st == 204

  async def timeout_user(self, channel, user_id, seconds, reason):
    token = await self.bot_user_token(channel)
    bid = await self.user_id(channel)
    _, sid = await self.bot_ident(channel)
    if not (token and bid and sid and user_id):
      return False
    st, _ = await self.call("POST", "moderation/bans", token,
                            params={"broadcaster_id": bid, "moderator_id": sid},
                            body={"data": {"user_id": user_id, "duration": int(seconds),
                                           "reason": reason[:100]}})
    return st == 200


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
.tabs button.on{background:var(--c,var(--acc));color:#fff}
.tabs button{white-space:nowrap}
.tabs{overflow-x:auto}
.cnt{background:#ef4444;color:#fff;border-radius:20px;font-size:11px;padding:1px 7px;margin-inline-start:4px}
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
#toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);background:var(--ok);color:#000;padding:11px 20px;border-radius:12px;font-weight:700;transition:.25s;opacity:0}
#toast.show{transform:translate(-50%,0);opacity:1}#toast.bad{background:var(--bad);color:#fff}
#login{min-height:80vh;display:grid;place-items:center}
#login .card{width:100%;max-width:360px;text-align:center}
"""

COMMON_JS = r"""
const $=s=>document.querySelector(s);
const PERMS={everyone:"الكل",sub:"المشتركين وفوق",vip:"VIP وفوق",mod:"المودات فقط",broadcaster:"الستريمر فقط"};
const BASIC=[
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
const t=s=>{if(LANG!=="en")return s;if(EN[s])return EN[s];const m=/^المدة لازم تكون من (\d+) إلى (\d+) دقيقة$/.exec(s);return m?"The interval must be between "+m[1]+" and "+m[2]+" minutes":s};
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
  <div class="chips" id="chips"><span>$(user)</span><span>$(touser)</span><span>$(channel)</span><span>$(game)</span><span>$(count)</span><span>$(uptime)</span></div>
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
    <button class="on" data-t="ch" style="--c:#9146ff">القنوات</button>
    <button data-t="cmd" style="--c:#3b82f6">الكوماندات</button>
    <button data-t="msg" style="--c:#14b8a6">إرسال رسالة</button>
    <button data-t="basic" style="--c:#f59e0b">الأساسية</button>
    <button data-t="rep" style="--c:#ef4444">🚩 البلاغات<span class="cnt" id="repn" hidden></span></button>
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

  <section id="t-rep" hidden>
    <div class="card" style="border-top:3px solid #ef4444">
      <h2>البلاغات</h2>
      <div id="replist"></div>
    </div>
    <div class="card" style="border-top:3px solid #f59e0b">
      <h2>ممنوعين من إرسال البلاغات</h2>
      <input id="repban" dir="ltr" placeholder="يوزر تويتش">
      <button class="btn red" id="repbanbtn">منع من البلاغات</button>
      <div id="repbanlist" style="margin-top:10px"></div>
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
Object.assign(EN,{"البلاغات":"Reports","ممنوعين من إرسال البلاغات":"Blocked from sending reports","يوزر تويتش":"Twitch username",
"منع من البلاغات":"Block from reports","ما فيه بلاغات":"No reports","ما فيه ممنوعين":"Nobody is blocked","رفع المنع":"Unblock",
"تم منع المُبلّغ":"Reporter blocked","تم رفع الحظر":"Ban lifted","تمنع هذا المُبلّغ من إرسال البلاغات؟":"Block this reporter from sending reports?",
"🚩 البلاغات":"🚩 Reports"});
for(const k in EN)AR[EN[k]]=k;
let S={channels:[],commands:{},bot:"",banned:[],reports:[],report_bans:[]};
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
  renderBasic($("#basiclist"));
  renderReports();
}
function renderReports(){
  const open=S.reports.filter(r=>!r.done).length,n=$("#repn");
  n.hidden=!open;n.textContent=open;
  const box=$("#replist");box.innerHTML="";
  if(!S.reports.length)box.innerHTML='<p class="empty">'+t("ما فيه بلاغات")+'</p>';
  S.reports.forEach(r=>{
    const d=document.createElement("div");d.className="row col";
    if(r.done)d.style.opacity=".5";
    d.innerHTML='<div class="top"><b dir="auto" data-nt></b><span><button class="ic dn">✅</button><button class="ic bn">🚫</button><button class="ic del">🗑</button></span></div><div class="meta" data-nt></div><p data-nt></p>';
    d.querySelector("b").textContent=r.by+(r.channel?" • "+r.channel:"");
    d.querySelector(".meta").textContent=new Date(r.ts*1000).toLocaleString()+(r.page?" • "+r.page:"");
    d.querySelector("p").textContent=r.text;
    d.querySelector(".dn").onclick=()=>act(()=>api("POST","/api/reports/"+r.id+"/done"));
    d.querySelector(".bn").onclick=()=>{if(confirm(t("تمنع هذا المُبلّغ من إرسال البلاغات؟")))act(()=>api("POST","/api/report-ban",{report_id:r.id}),"تم منع المُبلّغ")};
    d.querySelector(".del").onclick=()=>act(()=>api("DELETE","/api/reports/"+r.id));
    box.appendChild(d);
  });
  const bl=$("#repbanlist");bl.innerHTML="";
  if(!S.report_bans.length)bl.innerHTML='<p class="empty">'+t("ما فيه ممنوعين")+'</p>';
  S.report_bans.forEach(x=>{
    const d=document.createElement("div");d.className="row";
    d.innerHTML='<b dir="ltr" data-nt></b><button class="btn ghost">'+t("رفع المنع")+'</button>';
    d.querySelector("b").textContent=x.label+" ("+x.id+")";
    d.querySelector("button").onclick=()=>act(()=>api("DELETE","/api/report-ban/"+encodeURIComponent(x.id)),"تم رفع الحظر");
    bl.appendChild(d);
  });
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
$("#repbanbtn").onclick=()=>act(async()=>{await api("POST","/api/report-ban",{name:$("#repban").value});$("#repban").value=""},"تم منع المُبلّغ");
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST","/api/commands",Object.assign({channel:$("#cmdch").value},cmdFormGet()));
  cmdFormClear();
},"تم حفظ الكوماند");
$("#sendmsg").onclick=()=>act(async()=>{
  await api("POST","/api/send",{channel:$("#msgch").value,text:$("#msgtxt").value});$("#msgtxt").value="";
},"تم الإرسال");
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("on",x===b));
  for(const t of ["ch","cmd","msg","basic","rep"])$("#t-"+t).hidden=t!==b.dataset.t;
});
setInterval(()=>{if(!$("#app").hidden)load()},60000);
initLang();
load();
</script>
</body>
</html>
"""

# ---------------- زر البلاغات (يظهر في موقع الستريمر وصفحة الكوماندات العامة) ----------------
REPORT_HTML = r"""
<style>
#repbtn{position:fixed;bottom:18px;inset-inline-end:18px;z-index:60;background:#ef4444;color:#fff;border:0;border-radius:30px;padding:11px 16px;font:inherit;font-weight:700;cursor:pointer;box-shadow:0 6px 20px rgba(239,68,68,.35)}
#repmodal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:grid;place-items:center;z-index:70;padding:16px}
#repmodal .rsheet{background:#111827;border:1px solid #1c2438;border-top:3px solid #ef4444;border-radius:18px;padding:20px;width:100%;max-width:460px}
#repmodal h3{margin:0 0 6px}
#repmodal textarea{min-height:120px}
#repmodal .rr{display:flex;gap:8px}
#repmodal .rr .btn{flex:1}
#repmodal .btn.sendr{background:#ef4444}
</style>
<button id="repbtn">🚩 بلاغ</button>
<div id="repmodal" hidden>
  <div class="rsheet">
    <h3>إرسال بلاغ عن مشكلة</h3>
    <p class="hint" style="margin:0 0 10px">اكتب المشكلة اللي صارت مع البوت وتوصل مباشرة للمطوّر.</p>
    <textarea id="reptxt" maxlength="800" placeholder="وصف المشكلة"></textarea>
    <div class="rr"><button class="btn sendr" id="repsend">إرسال البلاغ</button><button class="btn ghost" id="repcancel">إلغاء</button></div>
  </div>
</div>
"""

REPORT_JS = r"""
Object.assign(EN,{"🚩 بلاغ":"🚩 Report","إرسال بلاغ عن مشكلة":"Report a problem",
"اكتب المشكلة اللي صارت مع البوت وتوصل مباشرة للمطوّر.":"Describe the problem you had with the bot. It goes straight to the developer.",
"وصف المشكلة":"Problem description","إرسال البلاغ":"Send report","إلغاء":"Cancel",
"اكتب وصف المشكلة":"Describe the problem","وصل بلاغك، شكراً لك ✅":"Report sent, thank you ✅",
"تم منعك من إرسال البلاغات":"You've been blocked from sending reports",
"أرسلت بلاغات كثيرة، حاول بعد شوي":"Too many reports, try again later"});
for(const k in EN)AR[EN[k]]=k;
(function(){
  const b=document.getElementById("repbtn"),m=document.getElementById("repmodal");
  if(!b)return;
  const ctx=()=>{try{if(typeof CH!=="undefined"&&CH)return CH.name}catch(e){}try{if(typeof CHN!=="undefined")return CHN}catch(e){}return ""};
  b.onclick=()=>{m.hidden=false;document.getElementById("reptxt").focus()};
  document.getElementById("repcancel").onclick=()=>{m.hidden=true};
  m.onclick=e=>{if(e.target===m)m.hidden=true};
  document.getElementById("repsend").onclick=async()=>{
    const txt=document.getElementById("reptxt").value.trim();
    if(!txt){toast("اكتب وصف المشكلة",1);return}
    try{
      await api("POST","/report",{text:txt,channel:ctx(),page:location.pathname});
      document.getElementById("reptxt").value="";m.hidden=true;toast("وصل بلاغك، شكراً لك ✅");
    }catch(e){toast(e.message,1)}
  };
})();
"""

# ---------------- موقع الستريمر ----------------
STREAMER_HTML = HEAD.replace("{{TITLE}}", "موقع الستريمر") + r"""
<style>
body{background:#0a0e17}
#app{--pc:#9146ff;--acc:var(--pc)}
.shell{display:flex;min-height:100vh}
aside{width:260px;background:#0d1220;border-inline-end:1px solid #1c2438;display:flex;flex-direction:column;padding:16px 12px;position:sticky;top:0;height:100vh;flex-shrink:0;overflow-y:auto}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;padding:4px 8px 14px}
.brand .logo{width:36px;height:36px;font-size:18px}
aside select{margin:0 0 14px}
.sec{font-size:11px;color:#5d6785;letter-spacing:.08em;padding:12px 12px 6px}
.nav a{--c:#9146ff;display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:12px;color:var(--mut);cursor:pointer;font-weight:500;margin-bottom:3px;border-inline-start:3px solid transparent;transition:.15s}
.nav a:hover{background:color-mix(in srgb,var(--c) 12%,transparent);color:var(--tx)}
.nav a.on{background:linear-gradient(90deg,color-mix(in srgb,var(--c) 32%,transparent),color-mix(in srgb,var(--c) 4%,transparent));color:#fff;border-inline-start-color:var(--c)}
.nav i{font-style:normal;width:30px;height:30px;border-radius:9px;display:grid;place-items:center;background:color-mix(in srgb,var(--c) 24%,transparent);font-size:16px;flex-shrink:0}
.nav a.on i{background:var(--c)}
.me{margin-top:auto;border-top:1px solid #1c2438;padding-top:12px}
.meinfo{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.mav{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#9146ff,#5b21b6);display:grid;place-items:center;font-weight:700}
.meinfo b{display:block;font-size:14px}
.mebtns{display:flex;gap:8px}
.mebtns .btn{flex:1;text-align:center}
main{flex:1;min-width:0}
.top{display:flex;align-items:center;gap:12px;padding:14px 24px;border-bottom:1px solid #1c2438;position:sticky;top:0;background:rgba(10,14,23,.88);backdrop-filter:blur(8px);z-index:5}
.top h1{font-size:18px;margin:0;flex:1;border-inline-start:4px solid var(--pc);padding-inline-start:10px}
.burger{display:none;width:auto!important;padding:8px 12px!important}
.content{max-width:1080px;margin:0 auto;padding:24px}
.panel,.stat,.hero,.cmd{background:#111827;border:1px solid #1c2438;border-radius:16px}
.panel{padding:18px;border-top:3px solid var(--pc)}
.panel h3{margin:0 0 4px;font-size:15px}
.hero{padding:28px 20px;text-align:center;margin-bottom:14px;background:radial-gradient(circle at 50% 0,color-mix(in srgb,var(--pc) 32%,transparent),transparent 65%),#111827}
.av{width:84px;height:84px;border-radius:50%;background:linear-gradient(135deg,var(--pc),#5b21b6);display:grid;place-items:center;font-size:36px;font-weight:700;margin:0 auto 12px;box-shadow:0 0 0 5px color-mix(in srgb,var(--pc) 25%,transparent)}
.hero h2{font-size:26px;margin:0 0 8px;color:var(--tx)}
.pill{display:inline-block;font-size:12px;padding:4px 12px;border-radius:20px;background:#1c2438;color:var(--mut);font-weight:700}
.pill.live{background:rgba(46,204,113,.15);color:#2ecc71}
.acts{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:18px}
.acts .btn,.acts a.btn{width:auto;padding:10px 18px}
.btn.line{background:none;border:1px solid #2a3350;color:var(--tx)}
.btn.sm{width:auto;padding:8px 14px;font-size:13px}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:14px}
.stat{padding:18px;border-top:3px solid var(--sc,#9146ff)}
.stat:nth-child(1){--sc:#3b82f6}.stat:nth-child(2){--sc:#ec4899}.stat:nth-child(3){--sc:#22c55e}.stat:nth-child(4){--sc:#f59e0b}
.stat small{font-size:12px;color:var(--mut)}
.stat b{display:block;font-size:28px;margin-top:6px}
.stat b.ok{color:var(--ok)}.stat b.bad{color:var(--bad);font-size:20px;margin-top:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.bar{display:flex;align-items:center;gap:10px;margin:12px 0;font-size:14px}
.bar b{min-width:70px}
.bar i{flex:1;height:10px;background:#1c2438;border-radius:6px;overflow:hidden}
.bar s{display:block;height:100%;background:linear-gradient(90deg,var(--pc),#f0abfc);border-radius:6px}
.bar em{font-style:normal;color:var(--mut);min-width:24px;text-align:end}
.bubble{background:#0a0e17;border:1px solid #1c2438;border-radius:12px;padding:12px 14px;min-height:56px;white-space:pre-wrap;word-break:break-word;font-size:14px}
.bubble:before{content:"🤖 ";}
.simrow{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tool{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.tool input{flex:1;min-width:160px;margin:0}
.tool .btn{width:auto}
.chip,.lchip,.rchip,.srchip{background:#111827;border:1px solid #1c2438;color:var(--mut);padding:8px 14px;border-radius:20px;font:inherit;cursor:pointer;font-size:13px}
.chip.on,.lchip.on,.rchip.on,.srchip.on{background:var(--pc);border-color:var(--pc);color:#fff}
.cmd{display:flex;gap:12px;padding:14px;margin-bottom:10px;align-items:flex-start;border-inline-start:4px solid var(--pc)}
.cmd.off{opacity:.55}
.cmd.col{flex-direction:column;align-items:stretch}
.cbody{flex:1;min-width:0}
.chead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.chead b{font-size:16px;color:#e9ddff}
.cbody p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.bd{font-size:11px;padding:3px 10px;border-radius:20px;background:#1c2438;color:var(--mut)}
.bd.g{background:color-mix(in srgb,var(--pc) 22%,transparent);color:#fff}
.bd.warn{background:rgba(245,158,11,.18);color:#f5a623}
.chk{display:flex;align-items:center;gap:10px;margin:9px 0;color:var(--tx);font-size:14px;cursor:pointer}
.chk input{width:auto;margin:0;accent-color:var(--pc)}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.sub{font-size:13px;color:var(--mut);margin:12px 0 6px}
.song{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid #1c2438}
.song:last-child{border:0}
.song b{flex:1;font-size:14px;word-break:break-word;font-weight:500}
.song small{color:var(--mut)}
.song.now b{color:#f9a8d4}
.copyrow{display:flex;gap:8px}
.copyrow input{margin:0;direction:ltr}
.copyrow .btn{width:auto}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:grid;place-items:center;z-index:50;padding:16px}
.sheet{background:#111827;border:1px solid #1c2438;border-radius:18px;padding:20px;width:100%;max-width:520px;max-height:92vh;overflow:auto}
.sheet .card{background:none;border:0;padding:0;margin:0}
#bd{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:30}
@media(max-width:860px){
 aside{display:none}
 aside.open{display:flex;position:fixed;inset-block:0;inset-inline-start:0;z-index:40;width:280px}
 .burger{display:block}
 .grid2,.simrow{grid-template-columns:1fr}
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
      <a data-p="ov" class="on" style="--c:#9146ff"><i>🏠</i><span>الرئيسية</span></a>
      <a data-p="cmd" style="--c:#3b82f6"><i>⌨️</i><span>الكوماندات</span></a>
      <a data-p="auto" class="own" style="--c:#f59e0b"><i>⏰</i><span>الرسائل التلقائية</span></a>
      <a data-p="songs" class="own" style="--c:#ec4899"><i>🎵</i><span>طلبات الأغاني</span></a>
      <a data-p="spam" class="own" style="--c:#ef4444"><i>🛡️</i><span>الحماية من السبام</span></a>
      <a data-p="bot" class="own" style="--c:#14b8a6"><i>🤖</i><span>حساب البوت</span></a>
      <a data-p="mods" class="own" style="--c:#22c55e"><i>👥</i><span>المودات</span></a>
      <a data-p="set" class="own" style="--c:#94a3b8"><i>⚙️</i><span>الإعدادات</span></a>
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
          <div class="panel" style="margin-top:14px">
            <h3>كوماندات جاهزة في البوت</h3>
            <p class="hint" style="margin:0 0 6px">تشتغل مباشرة بدون إضافة. وإذا سوّيت كوماند بنفس الاسم يشتغل كوماندك بدلها</p>
            <div id="builtinlist"></div>
          </div>
        </section>

        <section class="pg own" id="p-auto" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>الرسائل الدورية</h3>
            <p class="mut">تشتغل أثناء البث فقط. هذا المفتاح يشغّل أو يوقف كل الرسائل المجدولة اللي تحته</p>
            <div class="tool" style="margin:12px 0 0">
              <button class="rchip" data-rm="on">مفعّلة</button>
              <button class="rchip" data-rm="off">متوقفة</button>
            </div>
          </div>
          <div class="panel" style="margin-bottom:14px">
            <h3>الرسائل المجدولة</h3>
            <p class="mut">أدعية وأذكار وتذكيرات تنكتب تلقائياً بالفاصل اللي تحدده. تقدر تعدل الافتراضية أو تحذفها وتضيف رسائلك.</p>
            <div id="tmlist" style="margin-top:12px"></div>
            <div class="cmd col" id="tmform" hidden>
              <label>نص الرسالة</label>
              <textarea id="tmtext" placeholder="مثال: اللهم صلِّ وسلم على نبينا محمد"></textarea>
              <p class="hint" id="tmhint" hidden>اتركه فاضي وتبقى الرسالة تختار عشوائي من القائمة الجاهزة، أو اكتب نص خاص فيه عشان يستبدلها.</p>
              <label>كل كم دقيقة؟</label>
              <input id="tmevery" type="number" min="5" max="1440" value="30" dir="ltr">
              <p class="hint" id="tmmin"></p>
              <div class="tool" style="margin:0">
                <button class="btn" id="tmsave">حفظ</button>
                <button class="btn ghost" id="tmcancel">إلغاء</button>
              </div>
            </div>
            <div class="acts" style="justify-content:flex-start">
              <button class="btn" id="tmnew">رسالة جديدة</button>
              <button class="btn line" id="tmreset">استرجاع الرسائل الافتراضية</button>
            </div>
          </div>
          <div class="panel">
            <h3>الردود التلقائية</h3>
            <p class="mut">ردود البوت على السلام ومساء الخير وباك وبرب. تقدر تعدل النص أو تحذف الرد. الرد يبدأ دائماً بمنشن للمشاهد، وتقدر تستخدم $(user).</p>
            <div id="aulist" style="margin-top:12px"></div>
          </div>
        </section>

        <section class="pg own" id="p-songs" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>طلبات الأغاني</h3>
            <p class="mut">المشاهدين يطلبون أغاني من يوتيوب أو سبوتيفاي بالشات: !sr رابط أو اسم الأغنية</p>
            <div class="tool" style="margin:12px 0">
              <button class="srchip" data-sr="on">مفعّلة</button>
              <button class="srchip" data-sr="off">متوقفة</button>
            </div>
            <div class="grid3">
              <div><label>أقصى طلبات لكل مشاهد</label><input id="sr-user" type="number" min="1" max="20" dir="ltr"></div>
              <div><label>أقصى طول للطابور</label><input id="sr-queue" type="number" min="1" max="100" dir="ltr"></div>
              <div><label>أقصى مدة للأغنية (دقائق)</label><input id="sr-min" type="number" min="1" max="60" dir="ltr"></div>
            </div>
            <label>مين يقدر يطلب؟</label>
            <select id="sr-perm">
              <option value="everyone">الكل</option>
              <option value="sub">المشتركين وفوق</option>
              <option value="vip">VIP وفوق</option>
              <option value="mod">المودات فقط</option>
            </select>
            <button class="btn" id="sr-save">حفظ الإعدادات</button>
            <p class="hint" id="sr-nokey" style="margin:10px 0 0" hidden>البحث بالاسم والحد الأقصى للمدة يحتاجون SPOTIFY_CLIENT_ID وSPOTIFY_CLIENT_SECRET (لسبوتيفاي) أو YOUTUBE_API_KEY (ليوتيوب) في Render. بدونها تشتغل الروابط فقط.</p>
          </div>
          <div class="panel" style="margin-bottom:14px">
            <h3>مشغّل الأغاني</h3>
            <p class="mut">افتح الرابط في تبويب، أو حطه Browser Source في OBS. لا تشاركه مع أحد.</p>
            <div class="copyrow" style="margin-top:10px">
              <input id="sr-playerurl" readonly>
              <button class="btn sm" id="sr-copy">نسخ</button>
              <a class="btn sm" id="sr-open" target="_blank">فتح</a>
            </div>
            <div class="tool" style="margin-top:12px"><button class="btn sm" id="sr-play">▶ تشغيل الأغاني من الموقع</button></div>
            <p class="hint" style="margin:6px 0 0">يشغّل الأغاني هنا داخل الموقع نفسه. لا تشغّل مشغّل ثاني (مثل OBS) بنفس الوقت وإلا بيشتغلون مرتين.</p>
            <p class="hint" style="margin:6px 0 0">أغاني سبوتيفاي تشتغل كاملة بس في متصفح كمبيوتر مسجّل فيه حساب Spotify Premium. غير كذا (جوال أو OBS أو بدون تسجيل دخول) تشتغل مقاطع 30 ثانية.</p>
            <div id="srplayer" hidden style="margin-top:12px;border:1px solid #1c2438;border-radius:12px;overflow:hidden"></div>
          </div>
          <div class="panel">
            <h3>الطابور</h3>
            <div class="tool" style="margin:10px 0">
              <button class="btn sm" id="sr-skip">⏭ تخطي الأغنية</button>
              <button class="btn sm line" id="sr-clear">مسح الطابور</button>
            </div>
            <div id="srlist"></div>
          </div>
        </section>

        <section class="pg own" id="p-spam" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>الحماية من السبام</h3>
            <p class="mut" id="spamstate"></p>
            <label class="chk"><input type="checkbox" id="f-links"><span>🔗 منع الروابط</span></label>
            <label class="chk"><input type="checkbox" id="f-caps"><span>🔠 منع الحروف الكبيرة الكثيرة (إنجليزي)</span></label>
            <label class="chk"><input type="checkbox" id="f-symbols"><span>⚠️ منع الرموز الكثيرة</span></label>
            <label class="chk"><input type="checkbox" id="f-repeat"><span>🔁 منع تكرار الحرف الواحد (مثل: هههههههههه)</span></label>
            <label class="chk"><input type="checkbox" id="f-long"><span>📏 منع الرسائل الطويلة (فوق 300 حرف)</span></label>
            <div class="sub">كلمات ممنوعة (كلمة أو جملة في كل سطر)</div>
            <textarea id="f-words" style="min-height:80px" dir="auto"></textarea>
            <div class="sub">روابط مسموحة (دومين في كل سطر، مثل: youtube.com)</div>
            <textarea id="f-allowed" style="min-height:70px" dir="ltr"></textarea>
            <div class="grid3" style="margin-top:6px">
              <div><label>مدة الكتم بالثواني (0 = حذف الرسالة فقط)</label><input id="f-timeout" type="number" min="0" max="600" dir="ltr"></div>
            </div>
            <label class="chk"><input type="checkbox" id="f-warn"><span>أرسل تنبيه للمشاهد المخالف</span></label>
            <label class="chk"><input type="checkbox" id="f-sub"><span>استثناء المشتركين من الفلاتر</span></label>
            <label class="chk"><input type="checkbox" id="f-vip"><span>استثناء الـ VIP من الفلاتر</span></label>
            <button class="btn" id="savespam">حفظ</button>
            <p class="hint" style="margin:10px 0 0">المودات والستريمر مستثنون دائماً. والمود يقدر يسمح لشخص بروابط لمدة دقيقة بـ !permit اسم_المشاهد</p>
          </div>
        </section>

        <section class="pg own" id="p-bot" hidden>
          <div class="panel" style="margin-bottom:14px">
            <h3>حساب البوت في قناتك</h3>
            <p class="mut">الحساب اللي يكتب فيه البوت بقناتك: <b id="botlogin" dir="ltr" data-nt></b> <span class="bd g" id="botmode"></span></p>
            <div class="acts" style="justify-content:flex-start">
              <a class="btn" href="/auth/mybot?m=self">استخدم حسابي أنا كبوت</a>
              <a class="btn line" href="/auth/mybot?m=other">اربط حساب ثاني كبوت</a>
              <button class="btn line" id="botreset" hidden>رجّع للبوت الافتراضي</button>
            </div>
            <p class="hint" style="margin:12px 0 0">«حسابي أنا»: البوت يكتب باسمك. «حساب ثاني»: سجّل دخول بحساب البوت اللي تبيه (حساب جديد تسوّيه للبوت أحسن) ووافق على الصلاحيات. بعدها يستقبل ويرد البوت بهذا الحساب بقناتك فقط.</p>
          </div>
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
<!--REPORT_HTML-->
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
"فتح صفحة الكوماندات العامة":"Open public commands page",
"إلغاء":"Cancel","ستريمر":"Streamer","مود":"Mod",
"الرسائل الدورية":"Periodic messages","مفعّلة":"On","متوقفة":"Off","تم الحفظ":"Saved",
"الرسائل التلقائية":"Auto messages","طلبات الأغاني":"Song requests","الحماية من السبام":"Spam protection",
"حساب البوت":"Bot account","الإعدادات":"Settings",
"تشتغل أثناء البث فقط. هذا المفتاح يشغّل أو يوقف كل الرسائل المجدولة اللي تحته":"Runs only while live. This switch turns all the scheduled messages below on or off",
"الرسائل المجدولة":"Scheduled messages","رسالة جديدة":"New message","استرجاع الرسائل الافتراضية":"Restore default messages",
"كل كم دقيقة؟":"Every how many minutes?","حفظ":"Save","الردود التلقائية":"Auto replies",
"تعطيل":"Disable","تفعيل":"Enable","استرجاع الافتراضي":"Restore default","محذوف":"Deleted",
"ما فيه رسائل مجدولة":"No scheduled messages","تحذف هذي الرسالة؟":"Delete this message?",
"حفظ الإعدادات":"Save settings","نسخ":"Copy","فتح":"Open","مشغّل الأغاني":"Song player","الطابور":"Queue",
"⏭ تخطي الأغنية":"⏭ Skip song","مسح الطابور":"Clear queue","ما فيه أغاني بالطابور":"The queue is empty",
"الحماية من السبام":"Spam protection","حفظ":"Save",
"حساب البوت في قناتك":"Your channel's bot account","استخدم حسابي أنا كبوت":"Use my own account as the bot",
"اربط حساب ثاني كبوت":"Link another account as the bot","رجّع للبوت الافتراضي":"Back to the default bot",
"بوت مخصص":"Custom bot","البوت الافتراضي":"Default bot",
"كوماندات جاهزة في البوت":"Built-in bot commands",
"الحروف الكبيرة":"Caps","تم الحفظ":"Saved"
});
for(const k in EN)AR[EN[k]]=k;
let ME=null,CH=null,PG="ov",FILT="all",Q="";
Object.assign(EN,{"تشتغل مباشرة بدون إضافة. وإذا سوّيت كوماند بنفس الاسم يشتغل كوماندك بدلها": "These work out of the box. If you create a command with the same name, yours replaces the built-in one", "أدعية وأذكار وتذكيرات تنكتب تلقائياً بالفاصل اللي تحدده. تقدر تعدل الافتراضية أو تحذفها وتضيف رسائلك.": "Prayers, adhkar and reminders are posted automatically at the interval you set. You can edit the defaults or delete them and add your own messages.", "مثال: اللهم صلِّ وسلم على نبينا محمد": "Example: Peace and blessings upon our Prophet Muhammad", "اتركه فاضي وتبقى الرسالة تختار عشوائي من القائمة الجاهزة، أو اكتب نص خاص فيه عشان يستبدلها.": "Leave it empty and the message picks at random from the ready-made list, or write your own text to replace it.", "ردود البوت على السلام ومساء الخير وباك وبرب. تقدر تعدل النص أو تحذف الرد. الرد يبدأ دائماً بمنشن للمشاهد، وتقدر تستخدم $(user).": "Bot replies to salam, good evening, back and brb. You can edit the text or delete the reply. The reply always starts by mentioning the viewer, and you can use $(user).", "المشاهدين يطلبون أغاني من يوتيوب أو سبوتيفاي بالشات: !sr رابط أو اسم الأغنية": "Viewers request songs from YouTube or Spotify in chat: !sr link or song name", "أقصى طلبات لكل مشاهد": "Max requests per viewer", "أقصى طول للطابور": "Max queue length", "أقصى مدة للأغنية (دقائق)": "Max song length (minutes)", "مين يقدر يطلب؟": "Who can request?", "البحث بالاسم والحد الأقصى للمدة يحتاجون SPOTIFY_CLIENT_ID وSPOTIFY_CLIENT_SECRET (لسبوتيفاي) أو YOUTUBE_API_KEY (ليوتيوب) في Render. بدونها تشتغل الروابط فقط.": "Searching by name and the max length limit need SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (for Spotify) or YOUTUBE_API_KEY (for YouTube) in Render. Without them only links work.", "افتح الرابط في تبويب، أو حطه Browser Source في OBS. لا تشاركه مع أحد.": "Open the link in a tab, or use it as a Browser Source in OBS. Don't share it with anyone.", "🔗 منع الروابط": "🔗 Block links", "🔠 منع الحروف الكبيرة الكثيرة (إنجليزي)": "🔠 Block excessive capital letters (English)", "⚠️ منع الرموز الكثيرة": "⚠️ Block excessive symbols", "🔁 منع تكرار الحرف الواحد (مثل: هههههههههه)": "🔁 Block repeated characters (e.g. hahahahaha)", "📏 منع الرسائل الطويلة (فوق 300 حرف)": "📏 Block long messages (over 300 characters)", "كلمات ممنوعة (كلمة أو جملة في كل سطر)": "Banned words (a word or phrase per line)", "روابط مسموحة (دومين في كل سطر، مثل: youtube.com)": "Allowed links (one domain per line, e.g. youtube.com)", "مدة الكتم بالثواني (0 = حذف الرسالة فقط)": "Timeout duration in seconds (0 = delete the message only)", "أرسل تنبيه للمشاهد المخالف": "Send a warning to the offending viewer", "استثناء المشتركين من الفلاتر": "Exempt subscribers from the filters", "استثناء الـ VIP من الفلاتر": "Exempt VIPs from the filters", "المودات والستريمر مستثنون دائماً. والمود يقدر يسمح لشخص بروابط لمدة دقيقة بـ !permit اسم_المشاهد": "Mods and the streamer are always exempt. A mod can allow someone to post links for a minute with !permit viewer_name", "الحساب اللي يكتب فيه البوت بقناتك:": "The account the bot writes with in your channel:", "«حسابي أنا»: البوت يكتب باسمك. «حساب ثاني»: سجّل دخول بحساب البوت اللي تبيه (حساب جديد تسوّيه للبوت أحسن) ووافق على الصلاحيات. بعدها يستقبل ويرد البوت بهذا الحساب بقناتك فقط.": "“My account”: the bot writes under your name. “Another account”: log in with the bot account you want (a new account made for the bot is better) and approve the permissions. After that the bot reads and replies with this account in your channel only.", "ترجع الرسائل المجدولة الافتراضية؟ الرسائل اللي أضفتها تنحذف.": "Reset the default scheduled messages? The messages you added will be deleted.", "تم ربط حساب البوت ✅": "Bot account linked ✅", "لازم تدخل بنفس حسابك": "You need to log in with your own account", "اكتب المدة بالدقائق": "Enter the duration in minutes", "اكتب نص الرسالة": "Enter the message text", "الرسالة ما تبدأ بـ / أو .": "The message can't start with / or .", "وصلت الحد الأقصى للرسائل المجدولة": "You've reached the maximum number of scheduled messages", "▶ تشغيل الأغاني من الموقع": "▶ Play songs on the site", "⏹ إيقاف المشغّل": "⏹ Stop the player", "تشغيل الآن": "Play now", "يشغّل الأغاني هنا داخل الموقع نفسه. لا تشغّل مشغّل ثاني (مثل OBS) بنفس الوقت وإلا بيشتغلون مرتين.": "Plays the songs right here on the site. Don't run another player (like OBS) at the same time or songs will play twice."});
Object.assign(EN,{"أغاني سبوتيفاي تشتغل كاملة بس في متصفح كمبيوتر مسجّل فيه حساب Spotify Premium. غير كذا (جوال أو OBS أو بدون تسجيل دخول) تشتغل مقاطع 30 ثانية.":"Spotify songs play in full only in a desktop browser where a Spotify Premium account is logged in. Otherwise (mobile, OBS, or not logged in) only 30-second previews play."});
for(const k in EN)AR[EN[k]]=k;
const TITLES={ov:"الرئيسية",cmd:"الكوماندات",auto:"الرسائل التلقائية",songs:"طلبات الأغاني",spam:"الحماية من السبام",bot:"حساب البوت",mods:"المودات",set:"الإعدادات"};
const COLORS={ov:"#9146ff",cmd:"#3b82f6",auto:"#f59e0b",songs:"#ec4899",spam:"#ef4444",bot:"#14b8a6",mods:"#22c55e",set:"#94a3b8"};
const OWNPG=["auto","songs","spam","bot","mods","set"];
const BUILTIN_CMDS=[
 ["!followage","من متى يتابع المشاهد القناة","How long a viewer has followed"],
 ["!accountage","عمر حساب المشاهد في تويتش","How old a viewer's account is"],
 ["!uptime","كم صار البث شغال","How long the stream has been live"],
 ["!game","اللعبة الحالية","The current game"],
 ["!title","عنوان البث الحالي","The current stream title"],
 ["!sr رابط أو اسم","طلب أغنية","Request a song"],
 ["!song","الأغنية الحالية","The current song"],
 ["!queue","الأغاني اللي بالطابور","The songs in the queue"],
 ["!wrongsong","يشيل آخر أغنية طلبتها","Removes your last requested song"],
 ["!skip","تخطي الأغنية (مود)","Skip the song (mod)"],
 ["!permit اسم","يسمح لشخص بروابط دقيقة (مود)","Lets a viewer post links for a minute (mod)"]
];
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
  if(OWNPG.includes(p)&&(!CH||CH.role!=="owner"))p="ov";
  PG=p;
  document.querySelectorAll(".pg").forEach(x=>x.hidden=x.id!=="p-"+p);
  document.querySelectorAll("#nav a").forEach(x=>x.classList.toggle("on",x.dataset.p===p));
  $("#app").style.setProperty("--pc",COLORS[p]||"#9146ff");
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
  if(!own&&OWNPG.includes(PG))go("ov");
  renderTop();renderSim();renderCmds();renderBuiltin();
  if(own){renderOwn();renderAuto();renderSongs();renderSpam();renderBot()}
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
  const r0=(LANG==="en"&&c.reply==="تم تغيير اللعبة إلى $(game) 🎮")?"Game changed to $(game) 🎮":(c.reply||""),rep=r0.split("$(user)").join(user).split("$(touser)").join(arg||user).split("$(channel)").join(CH.name).split("$(game)").join(c.game||"");
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
function renderBuiltin(){
  const box=$("#builtinlist");box.innerHTML="";
  BUILTIN_CMDS.forEach(b=>{
    const d=document.createElement("div");d.className="bc";
    d.innerHTML='<code data-nt></code><span class="d" data-nt></span><button class="ic" data-nt>📋</button>';
    d.querySelector("code").textContent=b[0];
    d.querySelector(".d").textContent=LANG==="en"?b[2]:b[1];
    d.querySelector("button").onclick=()=>copyText(b[0].split(" ")[0]);
    box.appendChild(d);
  });
}
function renderOwn(){
  const c=CH;
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
/* ---------- الرسائل التلقائية ---------- */
let TM_ID="";
const KINDN={saudi:"🤲 دعاء للسعودية (عشوائي من قائمة جاهزة)",dhikr:"📿 ذكر (عشوائي من قائمة جاهزة)"};
Object.assign(EN,{"🤲 دعاء للسعودية (عشوائي من قائمة جاهزة)":"🤲 Prayer for Saudi Arabia (random from a ready list)","📿 ذكر (عشوائي من قائمة جاهزة)":"📿 Dhikr (random from a ready list)",
"رد السلام":"Reply to salam","رد مساء الخير":"Reply to good evening","رد السلام ومساء الخير معاً":"Reply to salam + good evening","رد باك":"Reply to back","رد برب":"Reply to brb"});
for(const k in EN)AR[EN[k]]=k;
const fmtEvery=n=>LANG==="en"?(n%60===0?"every "+n/60+" h":"every "+n+" min"):(n%60===0?"كل "+n/60+(n/60===1?" ساعة":" ساعات"):"كل "+n+" دقيقة");
function tmOpen(m){
  TM_ID=m?m.id:"";
  $("#tmform").hidden=false;
  $("#tmtext").value=m&&m.kind==="text"?m.text:"";
  $("#tmevery").value=m?m.every:30;
  $("#tmevery").min=CH.min_every;
  $("#tmmin").textContent=(LANG==="en"?"Minimum ":"أقل مدة ")+CH.min_every+(LANG==="en"?" minutes":" دقايق");
  $("#tmhint").hidden=!(m&&m.kind!=="text");
  $("#tmform").scrollIntoView({behavior:"smooth",block:"center"});
}
function renderAuto(){
  const c=CH,box=$("#tmlist");box.innerHTML="";
  if(!c.timers.length)box.innerHTML='<p class="empty">'+t("ما فيه رسائل مجدولة")+'</p>';
  c.timers.forEach(m=>{
    const d=document.createElement("div");d.className="cmd"+(m.on?"":" off");
    d.innerHTML='<div class="cbody"><div class="chead"><span class="bd g" data-nt></span><span class="bd" data-nt></span></div><p data-nt></p></div><div><button class="ic tg">'+(m.on?"⏸":"▶️")+'</button><button class="ic ed">✏️</button><button class="ic del">🗑</button></div>';
    const bs=d.querySelectorAll(".bd");
    bs[0].textContent=fmtEvery(m.every);
    bs[1].textContent=m.kind==="text"?t("💬 رد عادي"):t(KINDN[m.kind]);
    d.querySelector("p").textContent=m.kind==="text"?m.text:"";
    if(m.kind!=="text")d.querySelector("p").hidden=true;
    d.querySelector(".tg").title=t(m.on?"تعطيل":"تفعيل");
    d.querySelector(".tg").onclick=()=>act(()=>api("POST",base()+"/timers",{id:m.id,text:m.kind==="text"?m.text:"",every:m.every,on:!m.on}),"تم الحفظ");
    d.querySelector(".ed").onclick=()=>tmOpen(m);
    d.querySelector(".del").onclick=()=>{if(ask("تحذف هذي الرسالة؟"))act(()=>api("DELETE",base()+"/timers/"+encodeURIComponent(m.id)),"تم الحفظ")};
    box.appendChild(d);
  });
  const ab=$("#aulist");ab.innerHTML="";
  c.autos.forEach(a=>{
    const d=document.createElement("div");d.className="cmd col"+(a.on?"":" off");
    d.innerHTML='<div class="chead"><b data-nt></b><span class="bd warn" data-nt></span></div><p class="hint" style="margin:0 0 8px" data-nt></p><textarea style="min-height:60px;margin:0" data-nt></textarea><div class="tool" style="margin:10px 0 0"><button class="btn sm sv"></button><button class="btn sm line tg"></button><button class="btn sm line rs"></button></div>';
    d.querySelector("b").textContent=t(a.label);
    const bw=d.querySelector(".bd");bw.textContent=t("محذوف");bw.hidden=a.on;
    d.querySelector(".hint").textContent=a.hint;
    const ta=d.querySelector("textarea");ta.value=a.text;
    d.querySelector(".sv").textContent=t("حفظ");
    d.querySelector(".tg").textContent=a.on?"🗑 "+t("تعطيل"):t("تفعيل");
    d.querySelector(".rs").textContent=t("استرجاع الافتراضي");
    d.querySelector(".sv").onclick=()=>act(()=>api("POST",base()+"/autos",{key:a.key,text:ta.value,on:a.on}),"تم الحفظ");
    d.querySelector(".tg").onclick=()=>act(()=>api("POST",base()+"/autos",{key:a.key,text:ta.value,on:!a.on}),"تم الحفظ");
    d.querySelector(".rs").onclick=()=>act(()=>api("POST",base()+"/autos",{key:a.key,text:"",on:true}),"تم الحفظ");
    ab.appendChild(d);
  });
}
/* ---------- طلبات الأغاني ---------- */
function renderSongs(){
  const c=CH,s=c.sr,q=c.songs;
  document.querySelectorAll(".srchip").forEach(x=>x.classList.toggle("on",x.dataset.sr===(s.on?"on":"off")));
  $("#sr-user").value=s.per_user;$("#sr-queue").value=s.max_queue;$("#sr-min").value=s.max_minutes;$("#sr-perm").value=s.perm;
  $("#sr-nokey").hidden=!!(c.yt_key||c.sp_key);
  const url=location.origin+c.player_path;
  $("#sr-playerurl").value=url;$("#sr-open").href=url;
  renderQueue();
  if(SRP&&SRC!==c.player_path)srPlayer(true);
  $("#sr-play").textContent=t(SRP?"⏹ إيقاف المشغّل":"▶ تشغيل الأغاني من الموقع");
}
let SRP=false,SRT=null,SRC="";
function renderQueue(){
  const q=CH.songs,box=$("#srlist");box.innerHTML="";
  const add=(m,now)=>{
    const d=document.createElement("div");d.className="song"+(now?" now":"");
    d.innerHTML='<span>'+(now?"▶️":"🎵")+'</span><b data-nt></b><small data-nt></small>'+(now?"":'<button class="ic pl" title="'+t("تشغيل الآن")+'">▶</button><button class="ic dl">✖</button>');
    d.querySelector("b").textContent=m.title;d.querySelector("small").textContent=m.by;
    const dl=d.querySelector(".dl");if(dl)dl.onclick=()=>act(()=>api("DELETE",base()+"/sr/"+encodeURIComponent(m.qid)),"تمت الإزالة");
    const pl=d.querySelector(".pl");if(pl)pl.onclick=()=>act(()=>api("POST",base()+"/sr/"+encodeURIComponent(m.qid)+"/play"),"تم الحفظ");
    box.appendChild(d);
  };
  if(q.current)add(q.current,true);
  q.queue.forEach(m=>add(m,false));
  if(!q.current&&!q.queue.length)box.innerHTML='<p class="empty">'+t("ما فيه أغاني بالطابور")+'</p>';
}
async function srRefresh(){try{const c=await api("GET",base2());CH.songs=c.songs;renderQueue()}catch(e){}}
function srPlayer(on){
  SRP=on;clearInterval(SRT);
  const box=$("#srplayer");box.innerHTML="";box.hidden=!on;
  if(on){
    SRC=CH.player_path;
    const f=document.createElement("iframe");f.src=location.origin+SRC;
    f.allow="autoplay; encrypted-media; fullscreen";f.style.cssText="width:100%;height:380px;border:0;display:block";
    box.appendChild(f);
    SRT=setInterval(()=>{if(PG==="songs")srRefresh()},4000);
  }
  $("#sr-play").textContent=t(on?"⏹ إيقاف المشغّل":"▶ تشغيل الأغاني من الموقع");
}
/* ---------- الحماية ---------- */
function renderSpam(){
  const f=CH.filters;
  for(const k of ["links","caps","symbols","repeat","long"])$("#f-"+k).checked=!!f[k];
  $("#f-words").value=(f.words||[]).join("\n");$("#f-allowed").value=(f.allowed||[]).join("\n");
  $("#f-timeout").value=f.timeout;$("#f-warn").checked=!!f.warn;$("#f-sub").checked=!!f.exempt_sub;$("#f-vip").checked=!!f.exempt_vip;
  Object.assign(EN,{"✅ الحماية جاهزة: البوت يقدر يحذف الرسائل ويكتم.":"✅ Protection is ready: the bot can delete messages and time users out.",
  "⚠️ الحماية ما تشتغل لسه: لازم صاحب البوت يربط حساب البوت (/auth/bot) من جديد، والبوت يكون مود في قناتك.":"⚠️ Protection isn't active yet: the bot owner must relink the bot account (/auth/bot) and the bot must be a mod in your channel."});
  for(const k in EN)AR[EN[k]]=k;
  $("#spamstate").textContent=t(CH.mod_ready?"✅ الحماية جاهزة: البوت يقدر يحذف الرسائل ويكتم.":"⚠️ الحماية ما تشتغل لسه: لازم صاحب البوت يربط حساب البوت (/auth/bot) من جديد، والبوت يكون مود في قناتك.");
}
/* ---------- حساب البوت ---------- */
function renderBot(){
  $("#botlogin").textContent=CH.bot.login;
  $("#botmode").textContent=t(CH.bot.custom?"بوت مخصص":"البوت الافتراضي");
  $("#botreset").hidden=!CH.bot.custom;
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
$("#tmnew").onclick=()=>tmOpen(null);
$("#tmcancel").onclick=()=>{$("#tmform").hidden=true};
$("#tmsave").onclick=()=>act(async()=>{
  const cur=CH.timers.find(x=>x.id===TM_ID);
  await api("POST",base()+"/timers",{id:TM_ID,text:$("#tmtext").value,every:parseInt($("#tmevery").value,10),on:cur?cur.on:true});
  $("#tmform").hidden=true;
},"تم الحفظ");
$("#tmreset").onclick=()=>{if(ask("ترجع الرسائل المجدولة الافتراضية؟ الرسائل اللي أضفتها تنحذف."))act(()=>api("POST",base()+"/timers/reset"),"تم الحفظ")};
document.querySelectorAll(".srchip").forEach(b=>b.onclick=()=>act(()=>api("POST",base()+"/sr/settings",{on:b.dataset.sr==="on"}),"تم الحفظ"));
$("#sr-save").onclick=()=>act(()=>api("POST",base()+"/sr/settings",{per_user:parseInt($("#sr-user").value,10),max_queue:parseInt($("#sr-queue").value,10),max_minutes:parseInt($("#sr-min").value,10),perm:$("#sr-perm").value}),"تم الحفظ");
$("#sr-copy").onclick=()=>copyText($("#sr-playerurl").value);
$("#sr-skip").onclick=()=>act(()=>api("POST",base()+"/sr/skip"),"تم الحفظ");
$("#sr-clear").onclick=()=>act(()=>api("POST",base()+"/sr/clear"),"تم الحفظ");
$("#sr-play").onclick=()=>srPlayer(!SRP);
$("#savespam").onclick=()=>act(()=>api("POST",base()+"/filters",{
  links:$("#f-links").checked,caps:$("#f-caps").checked,symbols:$("#f-symbols").checked,repeat:$("#f-repeat").checked,long:$("#f-long").checked,
  words:$("#f-words").value,allowed:$("#f-allowed").value,timeout:parseInt($("#f-timeout").value,10)||0,
  warn:$("#f-warn").checked,exempt_sub:$("#f-sub").checked,exempt_vip:$("#f-vip").checked}),"تم الحفظ");
$("#botreset").onclick=()=>act(()=>api("POST",base()+"/botacct/reset"),"تم الحفظ");
$("#cancelcmd").onclick=closeModal;
$("#modal").onclick=e=>{if(e.target.id==="modal")closeModal()};
$("#savecmd").onclick=()=>act(async()=>{
  await api("POST",base()+"/commands",cmdFormGet());cmdFormClear();closeModal();
},"تم حفظ الكوماند");
$("#added").onclick=()=>act(async()=>{
  await api("POST",base()+"/editors",{name:$("#newed").value});$("#newed").value="";
},"تمت إضافة المود");
$("#unlink").onclick=()=>{if(ask("تلغي الربط مع تويتش؟"))act(()=>api("POST",base()+"/unlink"),"تم إلغاء الربط")};
$("#leave").onclick=()=>{
  if(ask("متأكد تبي تشيل البوت من قناتك؟"))act(()=>api("POST",base()+"/leave"),"تم إزالة البوت",true);
};
$("#logout").onclick=async()=>{await api("POST","/s/api/logout");onAuth({enabled:true})};
const qp=new URLSearchParams(location.search);
if(qp.get("msg")==="ready")toast("تم تفعيل البوت وربط تويتش ✅");
if(qp.get("msg")==="botset")toast("تم ربط حساب البوت ✅");
const ERR={cancel:"تم إلغاء الدخول",fail:"فشل الدخول مع تويتش، حاول مرة ثانية",not_joined:"التفعيل الذاتي مقفل، كلم المطوّر",scope:"ما وافقت على الصلاحية المطلوبة",wrong:"لازم تدخل بنفس حسابك"};
if(qp.get("err"))toast(ERR[qp.get("err")]||"صار خطأ",1);
const goto=qp.get("go");
if(location.search)history.replaceState(null,"","/s");
//REPORT_JS
initLang();
init().then(()=>{if(goto&&CH)go(goto)});
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
.cc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0;border-top:3px solid var(--k,#3b82f6)}
.cc.game{--k:#ec4899}
.cc .h{display:flex;align-items:center;justify-content:space-between;gap:8px}
.cc b{font-size:16px;color:#e9ddff;cursor:pointer;word-break:break-all}
.cc b:hover{color:#fff}
.cc p{margin:0;color:var(--mut);font-size:14px;word-break:break-word}
.bd.p-sub{background:rgba(59,130,246,.18);color:#7db4ff}
.bd.p-vip{background:rgba(236,72,153,.18);color:#f59ac8}
.bd.p-mod{background:rgba(46,204,113,.15);color:#2ecc71}
.bd.p-broadcaster{background:rgba(245,166,35,.18);color:#f5a623}
.sec{margin-top:22px;border-top:3px solid #f59e0b}
.sec.sr{border-top-color:#ec4899}
.song{display:flex;align-items:center;gap:10px;padding:9px 2px;border-bottom:1px solid var(--line);font-size:14px}
.song:last-child{border:0}
.song b{flex:1;font-weight:500;word-break:break-word}
.song small{color:var(--mut)}
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
    <div class="card sec sr" id="srbox" hidden>
      <h2>🎵 طلبات الأغاني</h2>
      <div id="srlist"></div>
    </div>
    <div class="tool" style="margin-top:16px">
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
<!--REPORT_HTML-->
<div id="toast"></div>
<script>
//COMMON_JS
Object.assign(EN,{"🎵 طلبات الأغاني":"🎵 Song requests","ما فيه أغاني بالطابور":"The queue is empty"});
for(const k in EN)AR[EN[k]]=k;
const CHN=decodeURIComponent(location.pathname.split("/").pop()).toLowerCase();
let D=null,BAD=false,FILT="all",Q="";
function render(){
  $("#chname").textContent=CHN;$("#av").textContent=CHN.charAt(0).toUpperCase();
  $("#nf").hidden=!BAD;$("#box").hidden=BAD;
  if(BAD||!D)return;
  const lp=$("#live");lp.hidden=false;lp.className="pill"+(D.live?" live":"");lp.textContent=t(D.live?"لايف":"أوفلاين");
  const all=Object.keys(D.commands).sort(),q=Q.toLowerCase();
  $("#cnt").textContent=all.length+" "+t("كوماند");
  const sb=$("#srbox"),sl=$("#srlist");sb.hidden=!(D.songs&&D.songs.on);sl.innerHTML="";
  if(D.songs&&D.songs.on){
    const add=(m,now)=>{const d=document.createElement("div");d.className="song";d.innerHTML='<span>'+(now?"▶️":"🎵")+'</span><b data-nt></b><small data-nt></small>';d.querySelector("b").textContent=m.title;d.querySelector("small").textContent=m.by;sl.appendChild(d)};
    if(D.songs.current)add(D.songs.current,true);
    D.songs.queue.forEach(m=>add(m,false));
    if(!D.songs.current&&!D.songs.queue.length)sl.innerHTML='<p class="empty">'+t("ما فيه أغاني بالطابور")+'</p>';
  }
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
    const c=D.commands[n],d=document.createElement("div");d.className="cc"+(c.type==="game"?" game":"");
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
//REPORT_JS
initLang();
fetch("/pub/"+encodeURIComponent(CHN)).then(r=>r.ok?r.json():Promise.reject()).then(d=>{D=d;render()}).catch(()=>{BAD=true;render()});
</script>
</body>
</html>
"""

# ---------------- مشغّل الأغاني (رابط خاص بالستريمر يُحط في OBS) ----------------
PLAYER_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>مشغّل الأغاني</title>
<style>
[hidden]{display:none!important}
html,body{margin:0;height:100%;background:#0b0b10;color:#f1f1f5;font-family:Tajawal,system-ui,sans-serif}
#wrap{display:flex;flex-direction:column;height:100%}
#stage{flex:1;min-height:0;position:relative;background:#000}
#ytwrap,#spwrap{position:absolute;inset:0}
#ytwrap iframe{width:100%;height:100%;border:0;display:block}
#spwrap{display:flex;align-items:center;justify-content:center;background:#121212}
#spslot{width:100%;max-width:640px;padding:0 8px;box-sizing:border-box}
#spslot iframe{width:100%;border:0;display:block}
#msg{position:absolute;inset:0;z-index:5;display:grid;place-items:center;background:rgba(0,0,0,.72);color:#fff;font-size:18px;text-align:center;padding:16px;cursor:pointer}
#note{padding:6px 14px;background:#3a2a05;color:#fcd34d;font-size:13px}
#bar{padding:10px 14px;background:#18181f;border-top:3px solid #ec4899;font-size:15px;display:flex;gap:10px;align-items:center}
#bar b{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#bar small{color:#9a9aab}
button{background:#ec4899;color:#fff;border:0;border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}
</style></head><body>
<div id="wrap">
  <div id="stage">
    <div id="ytwrap"><div id="ytbox"></div></div>
    <div id="spwrap" hidden><div id="spslot"><div id="spbox"></div></div></div>
    <div id="msg" hidden></div>
  </div>
  <div id="note" hidden></div>
  <div id="bar"><span>🎵</span><b id="ttl">...</b><small id="by"></small><button id="sk">⏭</button></div>
</div>
<script>
const CH=__CH__,K=__KEY__;
const $=id=>document.getElementById(id);
const url=p=>"/player/api/"+encodeURIComponent(CH)+"/"+p+"?k="+encodeURIComponent(K);
let cur="",want=null,busy=false,tapT=null,errT=null;
let yt=null,ytReady=false,ytLoading=false;
let spc=null,spReady=false,spLoading=false,spLoaded="",spStarted=false,lastPos=0;
function note(t){const n=$("note");n.textContent=t||"";n.hidden=!t}
function showMsg(t,fn){const m=$("msg");m.textContent=t;m.hidden=false;m.onclick=fn||null}
function hideMsg(){$("msg").hidden=true}
function loadScript(src,onerr){
  const s=document.createElement("script");s.src=src;s.async=true;s.onerror=onerr;document.head.appendChild(s);
}
async function next(){
  if(busy)return;busy=true;
  try{const r=await fetch(url("next"),{method:"POST"});apply(await r.json())}catch(e){}
  busy=false;
}
function retry(){
  if(!want)return;
  try{want.src==="sp"?spc.play():yt.playVideo()}catch(e){}
}
function tapMsg(){showMsg("▶ اضغط هنا لتشغيل الصوت",()=>{hideMsg();retry()})}
function checkStarted(){
  if(!want)return;
  let ok=false;
  try{ok=want.src==="sp"?spStarted:(ytReady&&[1,3].indexOf(yt.getPlayerState())>=0)}catch(e){}
  if(!ok)tapMsg();
}
function stopAll(){
  try{if(ytReady)yt.stopVideo()}catch(e){}
  try{if(spReady)spc.pause()}catch(e){}
}
function flush(){
  const w=want;if(!w)return;
  if(w.src==="sp"){
    if(!spReady)return;
    if(spLoaded!==w.vid){spLoaded=w.vid;spc.loadUri("spotify:track:"+w.vid)}
    setTimeout(()=>{if(want===w)try{spc.play()}catch(e){}},800);
  }else{
    if(!ytReady)return;
    yt.loadVideoById(w.vid);
  }
}
function ytErr(code){
  const why={2:"رابط غير صالح",5:"خطأ في المشغّل",100:"الفيديو محذوف أو خاص",101:"صاحب الفيديو منع تشغيله خارج يوتيوب",150:"صاحب الفيديو منع تشغيله خارج يوتيوب",153:"يوتيوب رفض التضمين"}[code]||"خطأ";
  showMsg("⚠️ "+why+" ("+code+") — بنتخطى الأغنية");
  clearTimeout(errT);errT=setTimeout(next,2500);
}
function ensureApi(src,first){
  if(src==="sp"){
    if(spLoading)return;spLoading=true;
    window.onSpotifyIframeApiReady=A=>{
      A.createController($("spbox"),{width:"100%",height:152,uri:"spotify:track:"+first},c=>{
        spc=c;spReady=true;spLoaded=first;
        c.addListener("playback_update",onSp);
        flush();
      });
    };
    loadScript("https://open.spotify.com/embed/iframe-api/v1",()=>showMsg("تعذر تحميل مشغّل سبوتيفاي"));
  }else{
    if(ytLoading)return;ytLoading=true;
    window.onYouTubeIframeAPIReady=()=>{
      yt=new YT.Player("ytbox",{width:"100%",height:"100%",playerVars:{autoplay:1,rel:0,playsinline:1,origin:location.origin},events:{
        onReady:()=>{ytReady=true;flush()},
        onStateChange:e=>{if(e.data===0)next()},
        onError:e=>ytErr(e.data),
        onAutoplayBlocked:tapMsg
      }});
    };
    loadScript("https://www.youtube.com/iframe_api",()=>showMsg("تعذر تحميل مشغّل يوتيوب"));
  }
}
function onSp(e){
  const d=e.data||{},pos=d.position||0,dur=d.duration||0;
  if(!d.isPaused&&!d.isBuffering&&pos>0&&!spStarted){
    spStarted=true;clearTimeout(tapT);hideMsg();
    if(want&&dur>0&&dur<=31000&&(!want.dur||want.dur>45))note("⚠️ مقطع 30 ثانية فقط: سجّل دخول Spotify Premium في نفس المتصفح (كمبيوتر) عشان تشتغل كاملة");
  }
  if(spStarted&&d.isPaused&&dur>0&&(pos>=dur-1500||(pos===0&&lastPos>=dur-3000))){spStarted=false;next()}
  lastPos=pos;
}
function apply(s){
  const c=s.current;
  $("ttl").textContent=c?c.title:"ما فيه أغنية الحين";
  $("by").textContent=c?c.by:"";
  const id=c?c.qid:"";
  if(id===cur)return;
  cur=id;clearTimeout(tapT);clearTimeout(errT);hideMsg();note("");spStarted=false;lastPos=0;
  if(!c){want=null;stopAll();return}
  want={src:c.src||"yt",vid:c.vid,dur:c.dur||0};
  $("ytwrap").hidden=want.src==="sp";$("spwrap").hidden=want.src!=="sp";
  ensureApi(want.src,want.vid);
  flush();
  tapT=setTimeout(checkStarted,7000);
}
async function poll(){
  try{
    const s=await (await fetch(url("state"))).json();
    if(!s.current&&s.queue.length)await next();else apply(s);
  }catch(e){}
}
$("sk").onclick=next;
poll();
setInterval(poll,3000);
</script></body></html>
"""

OWNER_HTML = (OWNER_HTML.replace("{{FORM}}", CMD_FORM.replace("{{TOP}}", '<select id="cmdch"></select>'))
              .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))
STREAMER_HTML = (STREAMER_HTML.replace("{{FORM}}", CMD_FORM.replace("{{TOP}}", ""))
                 .replace("<!--REPORT_HTML-->", REPORT_HTML).replace("//REPORT_JS", REPORT_JS)
                 .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))
PUBLIC_HTML = (PUBLIC_HTML.replace("<!--REPORT_HTML-->", REPORT_HTML).replace("//REPORT_JS", REPORT_JS)
               .replace("/*COMMON_CSS*/", COMMON_CSS).replace("//COMMON_JS", COMMON_JS))

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


# ============================================================
# أدوات: مدد زمنية + يوتيوب
# ============================================================
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()  # اختياري: للبحث بالاسم وحد مدة الأغنية
YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^\s]*&)?v=|shorts/|embed/|live/)"
    r"|music\.youtube\.com/watch\?(?:[^\s]*&)?v=)([A-Za-z0-9_-]{11})")
URL_RE = re.compile(
    r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|io|gg|tv|me|co|ly|xyz|info|sa|ae|app|dev|gl|be)\b(?:/\S*)?",
    re.I)
NEW_CMDS = {
    "followage", "accountage", "uptime", "game", "title", "sr", "songrequest", "song",
    "queue", "playlist", "skip", "wrongsong", "srclear", "permit",
}


def fmt_dur(sec, lang="ar"):
  sec = int(max(0, sec))
  y, sec = divmod(sec, 31536000)
  mo, sec = divmod(sec, 2592000)
  d, sec = divmod(sec, 86400)
  h, sec = divmod(sec, 3600)
  m = sec // 60
  ar = lang != "en"
  parts = []

  def add(n, a1, a2, e1, e2):
    if n:
      parts.append(f"{n} {a1 if n == 1 else a2}" if ar else f"{n} {e1 if n == 1 else e2}")

  add(y, "سنة", "سنوات", "year", "years")
  add(mo, "شهر", "أشهر", "month", "months")
  add(d, "يوم", "أيام", "day", "days")
  add(h, "ساعة", "ساعات", "hour", "hours")
  add(m, "دقيقة", "دقايق", "minute", "minutes")
  if not parts:
    return "أقل من دقيقة" if ar else "less than a minute"
  parts = parts[:3]
  return " و ".join(parts) if ar else ", ".join(parts)


def parse_ts(s):
  try:
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
  except Exception:
    return time.time()


def yt_id(text):
  m = YT_ID_RE.search(text)
  return m.group(1) if m else None


def iso_dur(s):
  m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s or "")
  if not m:
    return None
  d, h, mi, se = [int(x or 0) for x in m.groups()]
  return d * 86400 + h * 3600 + mi * 60 + se


async def yt_lookup(vid):
  """يرجع (العنوان، المدة بالثواني أو None) أو None لو الفيديو ما ينفع."""
  try:
    async with aiohttp.ClientSession() as s:
      if YOUTUBE_API_KEY:
        async with s.get("https://www.googleapis.com/youtube/v3/videos", params={
            "part": "snippet,contentDetails,status", "id": vid, "key": YOUTUBE_API_KEY}) as r:
          d = await r.json()
        items = d.get("items") or []
        if not items:
          return None
        it = items[0]
        if not (it.get("status") or {}).get("embeddable", True):
          return None
        return it["snippet"]["title"], iso_dur(it["contentDetails"].get("duration"))
      async with s.get("https://www.youtube.com/oembed", params={
          "url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}) as r:
        if r.status != 200:
          return None
        d = await r.json()
        return (d.get("title") or vid), None
  except Exception as e:
    print(f"خطأ يوتيوب: {e}")
    return None


async def yt_search(q):
  if not YOUTUBE_API_KEY:
    return None
  try:
    async with aiohttp.ClientSession() as s:
      async with s.get("https://www.googleapis.com/youtube/v3/search", params={
          "part": "snippet", "type": "video", "maxResults": 1, "q": q,
          "videoEmbeddable": "true", "key": YOUTUBE_API_KEY}) as r:
        d = await r.json()
    items = d.get("items") or []
    return items[0]["id"]["videoId"] if items else None
  except Exception as e:
    print(f"خطأ بحث يوتيوب: {e}")
    return None


SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
SPOTIFY_ENABLED = bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)  # اختياري: للبحث بالاسم ومدة الأغنية
_INTL = r"(?:intl-[a-z]{2}(?:-[a-z]{2,4})?/)?"
SP_TRACK_RE = re.compile(
    r"(?:open\.spotify\.com/" + _INTL + r"(?:embed/)?track/|spotify:track:)([A-Za-z0-9]{22})")
SP_OTHER_RE = re.compile(
    r"open\.spotify\.com/" + _INTL + r"(?:album|playlist|artist|show|episode)/"
    r"|spotify:(?:album|playlist|artist|show|episode):")
SP_SHORT_RE = re.compile(r"https?://(?:spotify\.link|spotify\.app\.link)/[A-Za-z0-9_-]+")
_sp_tok = {"t": None, "exp": 0}
_SP_TIMEOUT = aiohttp.ClientTimeout(total=8)


async def sp_token():
  """توكن التطبيق (Client Credentials) للبحث وتفاصيل الأغنية. None لو ما فيه مفاتيح."""
  if not SPOTIFY_ENABLED:
    return None
  if _sp_tok["t"] and time.time() < _sp_tok["exp"] - 60:
    return _sp_tok["t"]
  try:
    async with aiohttp.ClientSession(timeout=_SP_TIMEOUT) as s:
      async with s.post("https://accounts.spotify.com/api/token",
                        data={"grant_type": "client_credentials"},
                        auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)) as r:
        d = await r.json()
    if d.get("access_token"):
      _sp_tok["t"] = d["access_token"]
      _sp_tok["exp"] = time.time() + d.get("expires_in", 3600)
      return _sp_tok["t"]
    print(f"سبوتيفاي رفض المفاتيح: {d}")
  except Exception as e:
    print(f"خطأ توكن سبوتيفاي: {e}")
  return None


async def sp_follow_short(link):
  """يفتح روابط spotify.link القصيرة ويرجع (الرابط النهائي، نص الصفحة)."""
  try:
    async with aiohttp.ClientSession(timeout=_SP_TIMEOUT) as s:
      async with s.get(link, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as r:
        body = (await r.text())[:300000]
        return str(r.url), body
  except Exception as e:
    print(f"خطأ رابط سبوتيفاي القصير: {e}")
    return "", ""


async def sp_parse(text):
  """يرجع معرّف الأغنية، أو "other" لو الرابط مو أغنية (ألبوم/بلايليست...)، أو None لو مو رابط سبوتيفاي."""
  m = SP_TRACK_RE.search(text)
  if m:
    return m.group(1)
  sh = SP_SHORT_RE.search(text)
  if sh:
    final, body = await sp_follow_short(sh.group(0))
    m = SP_TRACK_RE.search(final) or SP_TRACK_RE.search(body)
    return m.group(1) if m else "other"
  if SP_OTHER_RE.search(text):
    return "other"
  return None


async def sp_lookup(tid):
  """يرجع (العنوان، المدة بالثواني أو None) أو None لو الأغنية ما تنفع."""
  tok = await sp_token()
  try:
    async with aiohttp.ClientSession(timeout=_SP_TIMEOUT) as s:
      if tok:
        async with s.get(f"https://api.spotify.com/v1/tracks/{tid}",
                         headers={"Authorization": f"Bearer {tok}"}) as r:
          if r.status == 200:
            d = await r.json()
            name = d.get("name") or tid
            artists = ", ".join(a.get("name", "") for a in (d.get("artists") or []) if a.get("name"))
            ms = d.get("duration_ms")
            return (f"{artists} - {name}" if artists else name), (int(ms // 1000) if ms else None)
          if r.status == 404:
            return None
      async with s.get("https://open.spotify.com/oembed",
                       params={"url": f"https://open.spotify.com/track/{tid}"}) as r:
        if r.status != 200:
          return None
        d = await r.json()
        return (d.get("title") or tid), None
  except Exception as e:
    print(f"خطأ تفاصيل سبوتيفاي: {e}")
    return None


async def sp_search(q):
  """يبحث بالاسم في سبوتيفاي ويرجع معرّف أول أغنية (يحتاج SPOTIFY_CLIENT_ID/SECRET)."""
  tok = await sp_token()
  if not tok:
    return None
  try:
    async with aiohttp.ClientSession(timeout=_SP_TIMEOUT) as s:
      async with s.get("https://api.spotify.com/v1/search",
                       params={"q": q[:100], "type": "track", "limit": 5},
                       headers={"Authorization": f"Bearer {tok}"}) as r:
        if r.status != 200:
          print(f"بحث سبوتيفاي رجّع {r.status}")
          return None
        d = await r.json()
    items = (d.get("tracks") or {}).get("items") or []
    return items[0]["id"] if items else None
  except Exception as e:
    print(f"خطأ بحث سبوتيفاي: {e}")
    return None


def player_key(ch):
  return sign("player:" + ch)[:24]


def make_web_app(bot):
  store = bot.store
  twitch = bot.twitch
  redirect_uri = SITE_URL + "/auth/callback"
  report_times = {}  # بصمة المرسل -> أوقات آخر بلاغات

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
        "reports": store.data["reports"],
        "report_bans": [{"id": k, "label": v} for k, v in store.data["report_bans"].items()],
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

  # ---------------- البلاغات ----------------
  def client_ids(request):
    """هوية المرسل: يوزر تويتش (لو مسجل دخول) + بصمة مشفّرة من الـ IP."""
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.remote or "")
    ipid = "ip:" + hashlib.sha256((ip + "|" + SECRET.decode(errors="ignore")).encode()).hexdigest()[:12]
    login_name = read_session(request.cookies.get("ssess", ""))
    ids = [ipid]
    if login_name:
      ids.insert(0, "u:" + login_name)
    return ids, (login_name or ipid)

  async def send_report(request):
    b = await jbody(request)
    text = str(b.get("text", "")).strip()[:800]
    if not text:
      return jerr("اكتب وصف المشكلة")
    ids, label = client_ids(request)
    bans = store.data["report_bans"]
    if any(i in bans for i in ids):
      return jerr("تم منعك من إرسال البلاغات", 403)
    now = time.time()
    ts = [x for x in report_times.get(ids[0], []) if now - x < 3600]
    if len(ts) >= 5:
      return jerr("أرسلت بلاغات كثيرة، حاول بعد شوي", 429)
    ts.append(now)
    report_times[ids[0]] = ts
    rep = {
        "id": secrets.token_hex(4), "ts": int(now), "by": label, "ids": ids,
        "channel": str(b.get("channel", "")).strip().lower()[:25],
        "page": str(b.get("page", ""))[:100], "text": text, "done": False,
    }
    reports = store.data["reports"]
    reports.insert(0, rep)
    del reports[300:]
    await store.save()
    return web.json_response({"ok": True})

  def find_report(rid):
    return next((r for r in store.data["reports"] if r["id"] == rid), None)

  async def report_done(request):
    rep = find_report(request.match_info["id"])
    if not rep:
      return jerr("الكوماند مو موجود", 404)
    rep["done"] = not rep.get("done")
    await store.save()
    return web.json_response({"ok": True})

  async def report_del(request):
    rid = request.match_info["id"]
    store.data["reports"] = [r for r in store.data["reports"] if r["id"] != rid]
    await store.save()
    return web.json_response({"ok": True})

  async def report_ban(request):
    b = await jbody(request)
    if b.get("report_id"):
      rep = find_report(str(b["report_id"]))
      if not rep:
        return jerr("الكوماند مو موجود", 404)
      for i in rep.get("ids", []):
        store.data["report_bans"][i] = rep.get("by", i)
    else:
      name = str(b.get("name", "")).strip().lstrip("@").lower()
      if not valid_channel(name):
        return jerr("اليوزر غير صحيح")
      store.data["report_bans"]["u:" + name] = name
    await store.save()
    return web.json_response({"ok": True})

  async def report_unban(request):
    store.data["report_bans"].pop(request.match_info["ident"], None)
    await store.save()
    return web.json_response({"ok": True})

  # ---------------- موقع الستريمر ----------------
  def role_of(login_name, ch):
    if ch not in store.data["channels"]:
      return None
    if login_name == ch:
      return "owner"
    if login_name in store.data["editors"].get(ch, []):
      return "editor"
    return None

  def channels_for(login_name):
    out = []
    for ch in store.data["channels"]:
      r = role_of(login_name, ch)
      if r:
        out.append({"name": ch, "role": r})
    return out

  def access(request, owner_only=False):
    login_name = read_session(request.cookies.get("ssess", ""))
    if not login_name:
      return None, web.json_response({"error": "unauthorized", "enabled": twitch.enabled}, status=401)
    ch = request.match_info["channel"].lower()
    r = role_of(login_name, ch)
    if not r or (owner_only and r != "owner"):
      return None, jerr("ما عندك صلاحية", 403)
    return (login_name, ch, r), None

  def timers_view(ch):
    return [{
        "id": t["id"], "kind": t.get("kind", "text"), "text": t.get("text", ""),
        "every": int(t.get("every", 30)), "on": bool(t.get("on", True)),
    } for t in store.timers(ch)]

  def autos_view(ch):
    cfg = store.autos(ch)
    out = []
    for k, (label, default, hint) in AUTO_DEFAULTS.items():
      c = cfg.get(k) or {}
      out.append({
          "key": k, "label": label, "hint": hint, "default": default,
          "text": c.get("text") or default, "custom": bool(c.get("text")),
          "on": c.get("on", True) is not False,
      })
    return out

  async def s_index(request):
    return web.Response(text=STREAMER_HTML, content_type="text/html")

  async def auth_start(mode, extra="", force=False):
    if not twitch.enabled:
      raise web.HTTPFound("/s")
    state_val = mode + extra + secrets.token_urlsafe(16)
    q = {
        "client_id": CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "state": state_val,
        "scope": SCOPES.get(mode, ""),
    }
    if force:
      q["force_verify"] = "true"
    return state_val, AUTH_URL + "?" + urlencode(q)

  def go_auth(request, state_val, url):
    resp = web.HTTPFound(url)
    resp.set_cookie("ostate", state_val, max_age=600, httponly=True,
                    samesite="Lax", secure=is_https(request))
    raise resp

  async def auth_login(request):
    state_val, url = await auth_start("l")
    go_auth(request, state_val, url)

  async def auth_streamer(request):
    state_val, url = await auth_start("s")
    go_auth(request, state_val, url)

  async def auth_connect(request):
    state_val, url = await auth_start("c")
    go_auth(request, state_val, url)

  async def auth_bot(request):
    """ربط حساب البوت نفسه (مرة وحدة): افتحه من نافذة خاصة بحساب majek_bot."""
    state_val, url = await auth_start("b")
    go_auth(request, state_val, url)

  async def auth_mybot(request):
    """الستريمر يختار حساب البوت لقناته: حسابه هو (m=self) أو حساب ثاني (m=other)."""
    sess = read_session(request.cookies.get("ssess", ""))
    if not sess or role_of(sess, sess) != "owner":
      raise web.HTTPFound("/s")
    self_mode = request.query.get("m") == "self"
    state_val, url = await auth_start("m", "s" if self_mode else "o", force=True)
    go_auth(request, state_val, url)

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
    scopes = set(tok.get("scope") or [])

    if state_val[0] == "b":
      if login_name != BOT_LOGIN:
        resp = web.Response(
            text=f"دخلت بحساب {login_name}، لازم تدخل بحساب {BOT_LOGIN}", status=400)
        resp.del_cookie("ostate")
        return resp
      note = ""
      if tok.get("refresh_token") and "moderator:manage:banned_users" in scopes:
        store.data["bot_auth"] = {"refresh": tok["refresh_token"]}
        twitch.user_access.pop("bot:" + BOT_LOGIN, None)
        await store.save()
        note = " (الحماية من السبام جاهزة)"
      resp = web.Response(text="تم ربط حساب البوت بنجاح ✅" + note + " تقدر تقفل الصفحة")
      resp.del_cookie("ostate")
      return resp

    if state_val[0] == "m":
      # حساب البوت لقناة الستريمر: ما نغيّر جلسة الستريمر أبداً
      sess = read_session(request.cookies.get("ssess", ""))
      if not sess or role_of(sess, sess) != "owner":
        raise web.HTTPFound("/s?err=fail")
      if not {"user:bot", "user:read:chat", "user:write:chat"} <= scopes:
        raise web.HTTPFound("/s?go=bot&err=scope")
      if state_val[1] == "s" and login_name != sess:
        raise web.HTTPFound("/s?go=bot&err=wrong")
      try:
        await bot.set_custom_bot(sess, login_name, user["id"], tok.get("refresh_token", ""))
      except Exception as e:
        print(f"تعذر ضبط حساب البوت لـ {sess}: {e}")
        raise web.HTTPFound("/s?go=bot&err=fail")
      resp = web.HTTPFound("/s?go=bot&msg=botset")
      resp.del_cookie("ostate")
      raise resp

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
      elif GAME_SCOPE not in scopes or not tok.get("refresh_token"):
        dest = "/s?err=scope"
      else:
        store.data["tokens"][login_name] = {"refresh": tok["refresh_token"], "user_id": user["id"]}
        twitch.user_access[login_name] = (tok["access_token"], time.time() + tok.get("expires_in", 3600))
        await store.save()
        try:
          await twitch.make_bot_mod(login_name, twitch.bot_login(login_name))
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
    sr = store.sr(ch)
    view = bot.sr_view(ch)
    return web.json_response({
        "name": ch,
        "live": await bot.is_channel_live(ch),
        "commands": store.data["commands"].get(ch, {}),
        "songs": {"on": bool(sr["on"]), "current": view["current"], "queue": view["queue"]},
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
    own = role == "owner"
    acct = store.data["botacct"].get(ch)
    sr = store.sr(ch)
    f = store.filters(ch)
    return web.json_response({
        "name": ch, "role": role,
        "live": await bot.is_channel_live(ch),
        "game": game,
        "title": title,
        "twitch": twitch.enabled,
        "linked": ch in store.data["tokens"],
        "commands": store.data["commands"].get(ch, {}),
        "editors": store.data["editors"].get(ch, []) if own else [],
        "usage": bot.usage.get(ch, {}),
        "lang": store.data["lang"].get(ch, "ar"),
        "reminders": bool(store.data["reminders"].get(ch, False)),
        "timers": timers_view(ch) if own else [],
        "autos": autos_view(ch) if own else [],
        "min_every": MIN_TIMER_MINUTES,
        "sr": {k: sr[k] for k in SR_DEFAULT},
        "songs": bot.sr_view(ch),
        "yt_key": bool(YOUTUBE_API_KEY),
        "sp_key": SPOTIFY_ENABLED,
        "player_path": f"/player/{ch}?k={player_key(ch)}" if own else "",
        "filters": {k: f[k] for k in FILTER_DEFAULT},
        "mod_ready": bool((acct or store.data["bot_auth"]).get("refresh")),
        "bot": {"login": twitch.bot_login(ch), "custom": bool(acct)},
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
    store.data["botacct"].pop(ch, None)
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

  # ---------- الرسائل المجدولة ----------
  async def s_timer_save(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    timers = store.timers(ch)
    tid = str(b.get("id") or "")
    cur = next((x for x in timers if x["id"] == tid), None) if tid else None
    text = str(b.get("text", "")).strip()[:450]
    try:
      every = int(b.get("every"))
    except (TypeError, ValueError):
      return jerr("اكتب المدة بالدقائق")
    if every < MIN_TIMER_MINUTES or every > MAX_TIMER_MINUTES:
      return jerr(f"المدة لازم تكون من {MIN_TIMER_MINUTES} إلى {MAX_TIMER_MINUTES} دقيقة")
    if text.startswith(("/", ".")):
      return jerr("الرسالة ما تبدأ بـ / أو .")
    if text:
      kind = "text"
    elif cur and cur.get("kind") in ("saudi", "dhikr"):
      kind = cur["kind"]
    else:
      return jerr("اكتب نص الرسالة")
    if cur is None:
      if len(timers) >= MAX_TIMERS:
        return jerr("وصلت الحد الأقصى للرسائل المجدولة")
      cur = {"id": secrets.token_hex(3)}
      timers.append(cur)
      store.data["reminders"][ch] = True  # الستريمر أضاف رسالة بنفسه، فنشغّل المفتاح العام
    cur.update({"kind": kind, "text": text if kind == "text" else "",
                "every": every, "on": bool(b.get("on", True))})
    cur.pop("delay", None)
    bot.timer_next.pop((ch, cur["id"]), None)
    await store.save()
    return web.json_response({"ok": True})

  async def s_timer_del(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    tid = request.match_info["id"]
    timers = store.timers(ch)
    timers[:] = [x for x in timers if x["id"] != tid]
    bot.timer_next.pop((ch, tid), None)
    await store.save()
    return web.json_response({"ok": True})

  async def s_timer_reset(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    store.data["timers"][ch] = default_timers()
    for k in [k for k in bot.timer_next if k[0] == ch]:
      del bot.timer_next[k]
    await store.save()
    return web.json_response({"ok": True})

  async def s_auto_save(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    key = b.get("key")
    if key not in AUTO_DEFAULTS:
      return jerr("صار خطأ")
    text = str(b.get("text", "")).strip()[:300]
    if text.startswith(("/", ".")):
      return jerr("الرسالة ما تبدأ بـ / أو .")
    if text == AUTO_DEFAULTS[key][1]:
      text = ""
    on = bool(b.get("on", True))
    cfg = store.autos(ch)
    if on and not text:
      cfg.pop(key, None)
    else:
      cfg[key] = {"on": on, "text": text}
    await store.save()
    return web.json_response({"ok": True})

  # ---------- طلبات الأغاني ----------
  async def s_sr_settings(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    s = store.sr(ch)
    if "on" in b:
      s["on"] = bool(b["on"])
    for k, lo, hi in (("per_user", 1, 20), ("max_queue", 1, 100), ("max_minutes", 1, 60)):
      if k in b:
        try:
          s[k] = max(lo, min(hi, int(b[k])))
        except (TypeError, ValueError):
          return jerr("صار خطأ")
    if b.get("perm") in ("everyone", "sub", "vip", "mod"):
      s["perm"] = b["perm"]
    await store.save()
    return web.json_response({"ok": True})

  async def s_sr_skip(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    bot.sr_next(a[1])
    return web.json_response({"ok": True})

  async def s_sr_clear(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    bot.songs_of(a[1])["queue"].clear()
    return web.json_response({"ok": True})

  async def s_sr_del(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    s = bot.songs_of(a[1])
    qid = request.match_info["qid"]
    s["queue"][:] = [x for x in s["queue"] if x["qid"] != qid]
    return web.json_response({"ok": True})

  async def s_sr_play(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    s = bot.songs_of(a[1])
    qid = request.match_info["qid"]
    for i, x in enumerate(s["queue"]):
      if x["qid"] == qid:
        s["current"] = s["queue"].pop(i)
        break
    return web.json_response({"ok": True})

  def player_ok(request, ch):
    k = request.query.get("k", "")
    return ch in store.data["channels"] and hmac.compare_digest(k.encode(), player_key(ch).encode())

  async def player_page(request):
    ch = request.match_info["channel"].lower()
    if not player_ok(request, ch):
      return web.Response(text="403", status=403)
    html = PLAYER_HTML.replace("__CH__", json.dumps(ch)).replace("__KEY__", json.dumps(player_key(ch)))
    return web.Response(text=html, content_type="text/html")

  async def player_state(request):
    ch = request.match_info["channel"].lower()
    if not player_ok(request, ch):
      return jerr("forbidden", 403)
    return web.json_response(bot.sr_view(ch))

  async def player_next(request):
    ch = request.match_info["channel"].lower()
    if not player_ok(request, ch):
      return jerr("forbidden", 403)
    bot.sr_next(ch)
    return web.json_response(bot.sr_view(ch))

  # ---------- الحماية + حساب البوت ----------
  async def s_filters(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    _, ch, _ = a
    b = await jbody(request)
    f = store.filters(ch)
    for k in ("links", "caps", "symbols", "repeat", "long", "warn", "exempt_sub", "exempt_vip"):
      if k in b:
        f[k] = bool(b[k])
    if "words" in b:
      f["words"] = [w.strip().lower()[:60] for w in str(b["words"]).splitlines() if w.strip()][:100]
    if "allowed" in b:
      f["allowed"] = [d.strip().lower()[:60] for d in str(b["allowed"]).splitlines() if d.strip()][:50]
    if "timeout" in b:
      try:
        f["timeout"] = max(0, min(600, int(b["timeout"])))
      except (TypeError, ValueError):
        return jerr("صار خطأ")
    await store.save()
    return web.json_response({"ok": True})

  async def s_botacct_reset(request):
    a, err = access(request, owner_only=True)
    if err:
      return err
    await bot.reset_bot(a[1])
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
  # البلاغات
  r.add_post("/report", send_report)
  r.add_post("/api/reports/{id}/done", report_done)
  r.add_delete("/api/reports/{id}", report_del)
  r.add_post("/api/report-ban", report_ban)
  r.add_delete("/api/report-ban/{ident}", report_unban)
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
  r.add_get("/auth/mybot", auth_mybot)
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
  r.add_post("/s/api/channel/{channel}/title", s_title)
  r.add_post("/s/api/channel/{channel}/timers", s_timer_save)
  r.add_post("/s/api/channel/{channel}/timers/reset", s_timer_reset)
  r.add_delete("/s/api/channel/{channel}/timers/{id}", s_timer_del)
  r.add_post("/s/api/channel/{channel}/autos", s_auto_save)
  r.add_post("/s/api/channel/{channel}/sr/settings", s_sr_settings)
  r.add_post("/s/api/channel/{channel}/sr/skip", s_sr_skip)
  r.add_post("/s/api/channel/{channel}/sr/clear", s_sr_clear)
  r.add_delete("/s/api/channel/{channel}/sr/{qid}", s_sr_del)
  r.add_post("/s/api/channel/{channel}/sr/{qid}/play", s_sr_play)
  r.add_post("/s/api/channel/{channel}/filters", s_filters)
  r.add_post("/s/api/channel/{channel}/botacct/reset", s_botacct_reset)
  # مشغّل الأغاني
  r.add_get("/player/{channel}", player_page)
  r.add_get("/player/api/{channel}/state", player_state)
  r.add_post("/player/api/{channel}/next", player_next)
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
  """اتصال IRC بسيط بحساب البوت: يخدم القنوات اللي ما أعطت صلاحية EventSub (بدون شارة بوت)."""

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
          delay = 300  # التوكن غلط: لا نكرر المحاولة بسرعة
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
      await asyncio.sleep(0.6)  # حد تويتش: 20 دخول كل 10 ثواني

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
          "message_id": tags.get("id", ""),
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
  """مرسل الرسالة (مبني من حدث EventSub)."""

  def __init__(self, ev):
    self.name = (ev.get("chatter_user_login") or "").lower()
    self.uid = ev.get("chatter_user_id") or ""
    ids = {b.get("set_id") for b in ev.get("badges") or []}
    same_id = bool(self.uid) and self.uid == ev.get("broadcaster_user_id")
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
    self.id = ev.get("message_id") or ""
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
    self.usage = {}  # قناة -> {كوماند: عدد الاستخدام} من آخر تشغيل
    self.seen = {}  # معرفات أحداث EventSub لمنع التكرار
    self.queues = {}  # قناة -> طابور الإرسال
    self.paused = set()  # قنوات الستريمر سحب منها الصلاحية: ما نعيد الاشتراك لين يعيد الربط
    self.irc = IRCClient(self, IRC_TOKEN) if IRC_TOKEN else None
    self.irc_channels = set()  # قنوات تشتغل بالـ IRC لأن ما فيها صلاحية EventSub
    self.timer_next = {}  # (قناة، رقم الرسالة) -> وقت الإرسال القادم
    self.songs = {}  # قناة -> {"queue": [...], "current": {...}} (في الذاكرة)
    self.permits = {}  # (قناة، يوزر) -> وقت انتهاء السماح بالروابط
    self.sent_texts = {}  # (قناة، نص) -> وقت الإرسال: يمنع البوت يتعامل مع رسائله إذا كان بحساب الستريمر
    self.warned = {}  # (قناة، يوزر) -> آخر تنبيه من الفلاتر

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

  # ---------- طلبات الأغاني ----------
  def songs_of(self, ch):
    return self.songs.setdefault(ch, {"queue": [], "current": None})

  def sr_view(self, ch):
    s = self.songs_of(ch)
    return {"current": s["current"], "queue": list(s["queue"])}

  def sr_next(self, ch):
    s = self.songs_of(ch)
    s["current"] = s["queue"].pop(0) if s["queue"] else None
    return s["current"]

  # ---------- حساب البوت المخصص لكل قناة ----------
  async def set_custom_bot(self, ch, login, uid, refresh):
    if login == BOT_LOGIN:
      await self.reset_bot(ch)
      return
    self.store.data["botacct"][ch] = {"login": login, "id": uid, "refresh": refresh}
    self.twitch.user_access.pop("bot:" + login, None)
    await self.store.save()
    await self.switch_bot(ch)

  async def reset_bot(self, ch):
    if self.store.data["botacct"].pop(ch, None) is not None:
      await self.store.save()
    await self.switch_bot(ch)

  async def switch_bot(self, ch):
    """يغيّر الحساب اللي يقرأ ويكتب في القناة: يلغي الاشتراك القديم ويشترك من جديد."""
    try:
      await self.twitch.unsubscribe_chat(ch)
    except Exception as e:
      print(f"تعذر إلغاء الاشتراك القديم في {ch}: {e}")
    if ch in self.irc_channels:
      self.irc_channels.discard(ch)
      if self.irc:
        self.irc.part(ch)
    login = self.twitch.bot_login(ch)
    if login != ch:
      try:
        await self.twitch.make_bot_mod(ch, login)
      except Exception as e:
        print(f"تعذر جعل {login} مود في {ch}: {e}")
    await self.join_channels([ch])

  # ---------- الاشتراك في شات القنوات ----------
  async def resub_all(self):
    # احذف الاشتراكات المعطلة (تويتش يعطلها لو السيرفر نام) وأعد الاشتراك
    for s in await self.twitch.list_subs():
      if s.get("status") not in ("enabled", "webhook_callback_verification_pending"):
        await self.twitch.drop_sub(s["id"])
    await self.join_channels([
        c for c in self.store.data["channels"]
        if c not in self.store.data["banned"] and c not in self.paused
    ])

  async def resub_loop(self):
    await asyncio.sleep(10)  # لين يشتغل السيرفر ويقدر يرد على تحقق تويتش
    while True:
      try:
        await self.resub_all()
      except Exception as e:
        print(f"خطأ في الاشتراك: {e}")
      await asyncio.sleep(3600)

  async def join_channels(self, names):
    for n in names:
      self.paused.discard(n)  # الاستدعاء الصريح (إضافة أو إعادة ربط) يرفع الإيقاف
      ok, why = await self.twitch.subscribe_chat(n)
      if ok:
        print(f"اشتراك الشات {n}: ✅")
        if n in self.irc_channels:  # صارت تشتغل بـ EventSub، نطلع من IRC عشان ما يتكرر الرد
          self.irc_channels.discard(n)
          if self.irc:
            self.irc.part(n)
      elif self.irc and n not in self.store.data["botacct"]:
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
        q.put_nowait(None)  # يوقف عامل الإرسال

  async def on_revocation(self, sub):
    """تويتش ألغى الاشتراك: لو الستريمر سحب الصلاحية نوقف المحاولات لين يعيد الربط."""
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

  # ---------- الإرسال: طابور لكل قناة مع حدود تحمي الحساب من السبام ----------
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
        continue  # رسالة قديمة، ما لها فايدة
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
      times.append(time.time())
      self.sent_texts[(ch, text[:490])] = time.time()
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
      for k in [k for k, v in self.sent_texts.items() if now - v > 120]:
        del self.sent_texts[k]
      for k in [k for k, v in self.twitch.sent_ids.items() if now - v > 300]:
        del self.twitch.sent_ids[k]
      if mid in self.seen:
        return
      self.seen[mid] = now
      who = (ev.get("chatter_user_login") or "").lower()
      ch = (ev.get("broadcaster_user_login") or "").lower()
      if who == self.nick or who in KNOWN_BOTS:
        return
      if ev.get("message_id") and ev["message_id"] in self.twitch.sent_ids:
        return  # رسالة البوت نفسه
      mine = self.twitch.bot_login(ch)
      if who == mine:
        # لو البوت بحساب الستريمر نفسه، رسائل الستريمر اليدوية لازم تمر: نتجاهل بس اللي أرسلها البوت
        if who != ch:
          return
        if (ch, ((ev.get("message") or {}).get("text") or "")[:490]) in self.sent_texts:
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

  # ---------- الرسائل المجدولة (أدعية، أذكار، تذكيرات) ----------
  def timer_text(self, t):
    if t.get("text"):
      return t["text"]
    if t.get("kind") == "saudi":
      return f"اللهم صلِّ وسلم على نبينا محمد، {self.get_random_saudi_prayer()}"
    if t.get("kind") == "dhikr":
      return self.get_random_dhikr()
    return ""

  async def periodic_reminders(self):
    while True:
      await asyncio.sleep(20)
      try:
        now = time.time()
        seen_keys = set()
        for ch in list(self.store.data["channels"]):
          for t in list(self.store.timers(ch)):
            key = (ch, t["id"])
            seen_keys.add(key)
            try:
              every = max(MIN_TIMER_MINUTES, int(t.get("every", 30))) * 60
            except (TypeError, ValueError):
              every = 30 * 60
            if key not in self.timer_next:
              self.timer_next[key] = now + (t.get("delay") or every / 60) * 60
              continue
            if now < self.timer_next[key]:
              continue
            self.timer_next[key] = now + every
            if not t.get("on", True) or not self.store.data["reminders"].get(ch, False):
              continue
            if not await self.is_channel_live(ch):
              continue
            text = self.timer_text(t)
            channel = self.get_channel(ch)
            if text and channel:
              try:
                await channel.send(text[:490])
              except Exception as e:
                print(f"تعذر إرسال الرسالة المجدولة في {ch}: {e}")
        for k in [k for k in self.timer_next if k not in seen_keys]:
          del self.timer_next[k]
      except Exception as e:
        print(f"خطأ في الرسائل المجدولة: {e}")

  # ----------------------------------------------------------
  # الكوماندات (إدارة + مخصصة)
  # ----------------------------------------------------------
  def lang_of(self, ch):
    return "en" if self.store.data["lang"].get(ch) == "en" else "ar"

  def tr(self, ch, key, **kw):
    ar, en = MSG[key]
    return (en if self.lang_of(ch) == "en" else ar).format(**kw)

  async def say(self, message, ch, key, extra="", **kw):
    """يرد على المستخدم بلغة القناة: عربي «@user نص» أو إنجليزي «@user -> text»."""
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

  async def expand(self, text, ch, cmd):
    """متغيرات إضافية: $(count) عدد مرات استخدام الكوماند، $(uptime) مدة البث."""
    if "$(count)" in text:
      d = self.store.data["counts"].setdefault(ch, {})
      d[cmd] = d.get(cmd, 0) + 1
      text = text.replace("$(count)", str(d[cmd]))
      await self.store.save()
    if "$(uptime)" in text:
      si = await self.twitch.stream_info(ch)
      up = fmt_dur(time.time() - parse_ts(si["started_at"]), self.lang_of(ch)) if si else "—"
      text = text.replace("$(uptime)", up)
    return text

  # ---------- كوماندات جاهزة: followage / uptime / أغاني ... ----------
  async def run_builtin(self, message, cmd, content, ch, level):
    user = message.author.name
    lang = self.lang_of(ch)
    now = time.time()

    async def say(key, extra="", **kw):
      await self.say(message, ch, key, extra, **kw)

    if cmd not in ("skip", "srclear", "permit"):
      ck = (ch, cmd, user)
      if now - self.cmd_cooldown.get(ck, 0) < 8:
        return True
      self.cmd_cooldown[ck] = now

    toks = content.split(None, 1)
    arg = toks[1].strip() if len(toks) > 1 else ""
    target = arg.split()[0].lstrip("@").lower() if arg else user.lower()
    me = target == user.lower()

    if cmd == "followage":
      if target == ch:
        await say("fa_streamer")
        return True
      if me and message.author.uid:
        uid = message.author.uid
      else:
        info = await self.twitch.user_info(target)
        if not info:
          await say("no_user", u=target)
          return True
        uid = info["id"]
      at, err = await self.twitch.followed_at(ch, uid)
      if err == "not_following":
        await say("fa_none" if me else "fa_none_other", u=target)
      elif err:
        await say({"not_linked": "e_not_linked", "refused": "e_refused"}.get(err, "e_expired"))
      else:
        d = fmt_dur(now - parse_ts(at), lang)
        await say("fa" if me else "fa_other", c=ch, d=d, u=target)
      return True

    if cmd == "accountage":
      info = await self.twitch.user_info(target)
      if not info:
        await say("no_user", u=target)
        return True
      d = fmt_dur(now - parse_ts(info.get("created_at", "")), lang)
      await say("aa" if me else "aa_other", d=d, u=target)
      return True

    if cmd == "uptime":
      si = await self.twitch.stream_info(ch)
      if not si:
        await say("up_off")
      else:
        await say("up", d=fmt_dur(now - parse_ts(si["started_at"]), lang))
      return True

    if cmd == "game":
      g, _ = await self.twitch.channel_info(ch)
      await say("game_now", g=g) if g else await say("game_none")
      return True

    if cmd == "title":
      _, t = await self.twitch.channel_info(ch)
      await say("title_now", t=t) if t else await say("game_none")
      return True

    if cmd == "permit":
      if level < PERMS["mod"]:
        return True
      who = arg.split()[0].lstrip("@").lower() if arg else ""
      if not who:
        await say("permit_usage")
        return True
      self.permits[(ch, who)] = now + 60
      await say("permit_ok", u=who)
      return True

    # ---------- طلبات الأغاني ----------
    sr = self.store.sr(ch)
    if not sr["on"]:
      await say("sr_off")
      return True
    s = self.songs_of(ch)

    if cmd in ("sr", "songrequest"):
      need = {"everyone": 0, "sub": 1, "vip": 2, "mod": 3}.get(sr["perm"], 0)
      if level < need:
        await say("sr_noperm")
        return True
      if not arg:
        await say("sr_usage")
        return True
      if len(s["queue"]) >= sr["max_queue"]:
        await say("sr_full")
        return True
      mine = sum(1 for x in s["queue"] if x["by"] == user.lower())
      if mine >= sr["per_user"] and level < PERMS["mod"]:
        await say("sr_user_max", n=sr["per_user"])
        return True
      src, vid = None, None
      sp = await sp_parse(arg)
      if sp == "other":
        await say("sr_sp_type")
        return True
      if sp:
        src, vid = "sp", sp
      else:
        vid = yt_id(arg)
        if vid:
          src = "yt"
        elif re.match(r"https?://", arg.strip(), re.I):
          await say("sr_need_link")
          return True
        elif SPOTIFY_ENABLED:
          src, vid = "sp", await sp_search(arg)
          if not vid and YOUTUBE_API_KEY:
            src, vid = "yt", await yt_search(arg)
        elif YOUTUBE_API_KEY:
          src, vid = "yt", await yt_search(arg)
        else:
          await say("sr_need_link")
          return True
        if not vid:
          await say("sr_nf")
          return True

      def same(x):
        return x.get("vid") == vid and x.get("src", "yt") == src

      if any(same(x) for x in s["queue"]) or (s["current"] and same(s["current"])):
        await say("sr_dup")
        return True
      info = await (sp_lookup(vid) if src == "sp" else yt_lookup(vid))
      if not info:
        await say("sr_nf")
        return True
      title, dur = info
      if dur and sr["max_minutes"] and dur > sr["max_minutes"] * 60:
        await say("sr_long", n=sr["max_minutes"])
        return True
      if len(s["queue"]) >= sr["max_queue"]:
        await say("sr_full")
        return True
      s["queue"].append({"qid": secrets.token_hex(4), "src": src, "vid": vid, "title": title[:100],
                         "by": user.lower(), "dur": dur})
      await say("sr_added", s=title[:80], p=len(s["queue"]))
      return True

    if cmd == "song":
      cur = s["current"]
      await say("song_now", s=cur["title"][:80], u=cur["by"]) if cur else await say("song_none")
      return True

    if cmd in ("queue", "playlist"):
      if not s["queue"]:
        await say("queue_empty")
      else:
        nxt = " • ".join(x["title"][:40] for x in s["queue"][:3])
        await say("queue_list", l=nxt, u=f"{SITE_URL}/c/{ch}" if SITE_URL else "")
      return True

    if cmd == "skip":
      if level < PERMS["mod"]:
        return True
      self.sr_next(ch)
      await say("skipped")
      return True

    if cmd == "srclear":
      if level < PERMS["mod"]:
        return True
      s["queue"].clear()
      await say("sr_cleared")
      return True

    if cmd == "wrongsong":
      for i in range(len(s["queue"]) - 1, -1, -1):
        if s["queue"][i]["by"] == user.lower():
          gone = s["queue"].pop(i)
          await say("wrong_ok", s=gone["title"][:80])
          return True
      await say("wrong_none")
      return True

    return False

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

    # ---------- !commands: رابط صفحة الكوماندات للجميع ----------
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

    # ---------- !bot: تعريف بالبوت (يرد بس لما أحد يسأل، وإذا الستريمر ما سوّى كوماند بنفس الاسم) ----------
    if cmd == "bot" and "bot" not in channel_cmds:
      bkey = (channel_name, "!bot")
      now = time.time()
      if now - self.cmd_cooldown.get(bkey, 0) < 30:
        return True
      self.cmd_cooldown[bkey] = now
      if SITE_URL:
        await say("bot_info", u=f"{SITE_URL}/s")
      return True

    # ---------- !reminders on/off: الرسائل الدورية ----------
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

    # ---------- كوماندات المودرز ----------
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

      # addcmd / editcmd
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

    # ---------- !addgame: اختصار يغيّر كاتيقوري البث ----------
    # مثال: !addgame !f fortnite  ← بعدها !f يغيّر الكاتيقوري إلى Fortnite
    # أي لعبة أو كاتيقوري موجود في تويتش تنفع (Just Chatting, Valorant, ...)
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

    # ---------- !settitle: تغيير عنوان البث ----------
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

    # ---------- كوماندات جاهزة (followage, sr, ...): كوماندات القناة المخصصة تغلب عليها ----------
    if cmd in NEW_CMDS and cmd not in channel_cmds:
      return await self.run_builtin(message, cmd, content, channel_name, level)

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

  def count_use(self, channel_name, cmd):
    d = self.usage.setdefault(channel_name, {})
    d[cmd] = d.get(cmd, 0) + 1

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
      self.count_use(channel_name, cmd)
      ok, result = await self.twitch.set_game(channel_name, entry["game"])
      if ok:
        text = format_response(entry["reply"], message.author.name, channel_name, target, result)
        await send(text[:490])
      else:
        await self.say(message, channel_name, "e_" + result, q=entry["game"])
      return True

    # الكوماندات العادية ما ترد إلا إذا القناة لايف
    if not await self.is_channel_live(channel_name):
      return True

    if now - self.cmd_cooldown.get(key, 0) < COMMAND_COOLDOWN:
      return True
    self.cmd_cooldown[key] = now
    self.count_use(channel_name, cmd)

    text = format_response(entry["reply"], message.author.name, channel_name, target)
    text = await self.expand(text, channel_name, cmd)
    await send(text[:490])
    return True

  # ----------------------------------------------------------
  # الحماية من السبام (فلاتر): تحذف الرسالة وتكتم عن طريق حساب البوت
  # ----------------------------------------------------------
  async def check_filters(self, message, content, username, ch, level):
    f = self.store.data["filters"].get(ch)
    if not f:
      return False
    if level >= PERMS["mod"]:
      return False
    if level == PERMS["vip"] and f.get("exempt_vip", True):
      return False
    if level == PERMS["sub"] and f.get("exempt_sub", True):
      return False

    now = time.time()
    low = content.lower()
    reason = None
    words = f.get("words") or []
    if words and any(w in low for w in words):
      reason = "f_words"
    elif f.get("links"):
      urls = URL_RE.findall(content)
      if urls and self.permits.get((ch, username), 0) < now:
        allowed = f.get("allowed") or []
        if not all(any(a in u.lower() for a in allowed) for u in urls):
          reason = "f_links"
    if not reason and f.get("repeat") and re.search(r"(\S)\1{9,}", content):
      reason = "f_repeat"
    if not reason and f.get("caps"):
      letters = [c for c in content if c.isascii() and c.isalpha()]
      if len(letters) >= 10 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        reason = "f_caps"
    if not reason and f.get("symbols"):
      compact = content.replace(" ", "")
      if len(compact) >= 12:
        sym = sum(1 for c in compact if not c.isalnum())
        if sym / len(compact) > 0.5:
          reason = "f_symbols"
    if not reason and f.get("long") and len(content) > 300:
      reason = "f_long"
    if not reason:
      return False

    acted = False
    if message.id and await self.twitch.delete_message(ch, message.id):
      acted = True
    secs = int(f.get("timeout", 10) or 0)
    if secs > 0 and message.author.uid and await self.twitch.timeout_user(
        ch, message.author.uid, secs, "spam filter"):
      acted = True
    if not acted:
      return False  # ما عندنا صلاحية نتصرف، نخلي الرسالة تكمل عادي
    if f.get("warn", True) and now - self.warned.get((ch, username), 0) > 15:
      self.warned[(ch, username)] = now
      await message.channel.send(f"@{message.author.name} {self.tr(ch, reason)}")
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

    # الفلاتر أول شي: لو الرسالة مخالفة ما نكمل
    if await self.check_filters(message, content, username, channel_name, level):
      return

    # الكوماندات تشتغل حتى للأونر
    if content.startswith("!"):
      if await self.handle_command(
          message, content, username, channel_name, is_owner, level
      ):
        return
    elif await self.handle_plain(message, content, channel_name, level):
      return

    # الردود التلقائية: تجاهل المستخدمين المتجاهلين فقط (الأونر يُرد عليه عادي)
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

    if has_greeting and has_evening:
      key = "both"
    elif has_evening:
      key = "evening"
    elif words[0] == "باك":
      key = "back"
    elif words[0] in ["brb", "برب"]:
      key = "brb"
    elif has_greeting:
      key = "salam"
    else:
      return

    # الستريمر يقدر يعدل نص الرد أو يحذفه (تعطيله) من موقع الستريمر
    cfg = self.store.data["autos"].get(channel_name, {}).get(key) or {}
    if cfg.get("on", True) is False:
      return
    text = cfg.get("text") or AUTO_DEFAULTS[key][1]
    text = format_response(text, message.author.name, channel_name, "")
    await send(f"{author_mention} {text}"[:490])
    user_reply_time[username] = current_time


if __name__ == "__main__":
  bot = Bot()
  bot.run()
