import asyncio
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

OWNER = "majek113"
IGNORED_USERS = {"1s3don"}  # يتجاهل الردود التلقائية لهم
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
# خادم Keep-Alive
# ============================================================
async def handle_ping(request):
  return web.Response(text="Bot is alive!")


async def start_web_server():
  app = web.Application()
  app.router.add_get("/", handle_ping)
  runner = web.AppRunner(app)
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
    asyncio.create_task(start_web_server())
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
