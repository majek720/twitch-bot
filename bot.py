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

# القنوات المطلوب التواجد بها كـ Viewer
CHANNELS = ["majek113", "teamiik", "iz0yi", "sh_2i", "vul1_"]

DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وحسن عبادتك",
]

last_reply_time = {}


# سيرفر الويب المصغر لإبقاء Render مستيقظاً عبر UptimeRobot
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
    # تشغيل حلقة فحص واستهلاك البث لزيادة المشاهدات
    asyncio.create_task(self.watch_streams_loop())

  async def is_channel_live(self, channel_name):
    try:
      streams = await self.fetch_streams(user_logins=[channel_name])
      return len(streams) > 0
    except Exception as e:
      return False

  async def watch_stream_worker(self, channel_name):
    """قراءة بيانات البث بأقل استهلاك ذاكرة ممكن لمنع إغلاق Render"""
    print(f"بدء احتساب المشاهدة للقناة: {channel_name}")
    try:
      session = ClientSession()
      while True:
        is_live = await self.is_channel_live(channel_name)
        if not is_live:
          print(f"توقف البث في قناة {channel_name}")
          break

        # جلب رابط البث بأدنى جودة لتوفير الذاكرة والشبكة
        try:
          streams = await asyncio.to_thread(
              streamlink.streams, f"https://www.twitch.tv/{channel_name}"
          )
          if "worst" in streams or "audio_only" in streams:
            stream_url = streams.get("audio_only", streams.get("worst")).url
            async with session.get(stream_url) as resp:
              if resp.status == 200:
                # قراءة البيانات وتجاهلها فوراً من الذاكرة
                async for chunk in resp.content.iter_chunked(1024 * 64):
                  pass
        except Exception:
          pass

        await asyncio.sleep(5)
    except Exception as e:
      print(f"خطأ في جلسة مشاهدة {channel_name}: {e}")
    finally:
      await session.close()
      if channel_name in self.active_viewers:
        del self.active_viewers[channel_name]

  async def watch_streams_loop(self):
    """مراقبة القنوات وتفعيل احتساب المشاهدة عند فتح البث"""
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
    elif words[0] in ["برب", "brb"]:
      await message.channel.send(f"{author_mention} خذ راحتك بس لا تطول علينا")
      replied = True
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
