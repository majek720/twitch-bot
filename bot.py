import asyncio
import os
import random
import re
import time
from aiohttp import ClientSession, web
import streamlink
from twitchio.ext import commands

# تثبيت الـ Event Loop لبيئة Render
asyncio.set_event_loop(asyncio.new_event_loop())

ACCESS_TOKEN = "oauth:v4iyxh6mfgv2v9zqvnwdkfe125patj"

# القنوات المتابعة
CHANNELS = ["majek113", "teamiik", "iz0yi", "sh_2i", "vul1_"]

DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وحسن عبادتك",
]

# قاموس لتتبع وقت آخر رد بشكل مستقل لكل قناة
last_reply_time = {}


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


class Bot(commands.Bot):

  def __init__(self):
    super().__init__(token=ACCESS_TOKEN, prefix="", initial_channels=CHANNELS)
    self.last_dhikr = None
    self.active_viewers = {}

  async def event_ready(self):
    print(f"تم الاتصال بنجاح! ({self.nick}) يعمل كـ Bot و Viewer خفيف.")
    asyncio.create_task(start_web_server())
    asyncio.create_task(self.periodic_reminders())
    asyncio.create_task(self.watch_streams_loop())

  async def is_channel_live(self, channel_name):
    try:
      streams = await self.fetch_streams(user_logins=[channel_name])
      return len(streams) > 0
    except Exception:
      return False

  async def watch_stream_worker(self, channel_name):
    print(f"بدء احتساب المشاهدة للقناة: {channel_name}")
    try:
      session = ClientSession()
      while True:
        is_live = await self.is_channel_live(channel_name)
        if not is_live:
          break
        try:
          streams = await asyncio.to_thread(
              streamlink.streams, f"https://www.twitch.tv/{channel_name}"
          )
          if "worst" in streams or "audio_only" in streams:
            stream_url = streams.get("audio_only", streams.get("worst")).url
            async with session.get(stream_url) as resp:
              if resp.status == 200:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                  pass
        except Exception:
          pass
        await asyncio.sleep(5)
    except Exception:
      pass
    finally:
      await session.close()
      if channel_name in self.active_viewers:
        del self.active_viewers[channel_name]

  async def watch_streams_loop(self):
    while True:
      for ch in CHANNELS:
        is_live = await self.is_channel_live(ch)
        if is_live and ch not in self.active_viewers:
          task = asyncio.create_task(self.watch_stream_worker(ch))
          self.active_viewers[ch] = task
      await asyncio.sleep(60)

  def get_random_dhikr(self):
    available = [d for d in DHIKR_LIST if d != self.last_dhikr]
    selected = random.choice(available)
    self.last_dhikr = selected
    return selected

  async def periodic_reminders(self):
    step = 0
    while True:
      await asyncio.sleep(1800)
      if step == 0:
        message_text = "اللهم صلِّ وسلم على نبينا محمد"
      elif step == 1:
        message_text = self.get_random_dhikr()
      else:
        message_text = "اشربوا ماااااااي"

      for channel_name in CHANNELS:
        is_live = await self.is_channel_live(channel_name)
        if is_live:
          channel = self.get_channel(channel_name)
          if channel:
            await channel.send(message_text)

      step = (step + 1) % 3

  async def event_message(self, message):
    if message.echo or message.author.name.lower() == "majek113":
      return

    channel_name = message.channel.name
    current_time = time.time()

    # الـ Cooldown منفصل ومستقل تماماً لكل قناة
    if (
        channel_name in last_reply_time
        and current_time - last_reply_time[channel_name] < 5
    ):
      return

    is_live = await self.is_channel_live(channel_name)
    if not is_live:
      return

    content = message.content.strip().lower()
    author_mention = f"@{message.author.name}"
    clean_content = re.sub(r"[^\w\s]", "", content)
    words = clean_content.split()

    if not words:
      return

    has_evening = "مساء الخير" in content
    has_full_greeting = "السلام عليكم" in content or "سلام عليكم" in content
    has_single_greeting = words[0] in ["السلام", "سلام"]
    has_greeting = has_full_greeting or has_single_greeting

    # التحقق من منشن البوت أو اسم حسابه
    bot_name = self.nick.lower() if self.nick else ""
    is_mentioned = (
        f"@{bot_name}" in content
        or bot_name in words
        or any(w == bot_name for w in words)
    )

    # التحقق من كلمات ماجيك / مجك
    has_magic = any(w in ["ماجيك", "مجك", "ماجك"] for w in words)

    replied = False

    # 1. الرد عند المنشن
    if is_mentioned:
      await message.channel.send(
          f"{author_mention} لا تمنشن يا بشر قاعد اذاكر"
      )
      replied = True

    # 2. الرد عند ذكر ماجيك / مجك / ماجك
    elif has_magic:
      await message.channel.send(
          f"{author_mention} عيون ماجيك، امرني؟"
      )
      replied = True

    # 3. إذا جمع المتابع بين السلام ومساء الخير
    elif has_greeting and has_evening:
      await message.channel.send(
          f"{author_mention} وعليكم السلام ورحمة الله وبركاته، ومساء النور"
          " نورت البث"
      )
      replied = True

    # 4. الرد على "مساء الخير"
    elif has_evening:
      await message.channel.send(f"{author_mention} مساء النور")
      replied = True

    # 5. الرد على "باك"
    elif words[0] == "باك":
      await message.channel.send(f"{author_mention} ولكم باك")
      replied = True

    # 6. الرد على "برب" أو "brb"
    elif words[0] in ["brb", "برب"]:
      await message.channel.send(f"{author_mention} خذ راحتك بس لا تطول علينا")
      replied = True

    # 7. الرد على السلام المنفصل
    elif has_greeting:
      await message.channel.send(
          f"{author_mention} وعليكم السلام ورحمة الله وبركاته، نورت البث"
      )
      replied = True

    if replied:
      last_reply_time[channel_name] = current_time
      await self.handle_commands(message)


if __name__ == "__main__":
  bot = Bot()
  bot.run()
