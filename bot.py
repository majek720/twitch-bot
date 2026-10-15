import asyncio
import os
import random
import re
import time
from aiohttp import web
from twitchio.ext import commands

# تثبيت الـ Event Loop لبيئة Render
asyncio.set_event_loop(asyncio.new_event_loop())

ACCESS_TOKEN = "oauth:v4iyxh6mfgv2v9zqvnwdkfe125patj"

# القنوات المتابعة
CHANNELS = ["majek113", "teamiik", "iz0yi", "sh_2i", "vul1_"]

# أذكار مأثورة وصحيحة من الأحاديث النبوية
DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وحسن عبادتك",
    "اللهم أنت ربي لا إله إلا أنت، خلقتني وأنا عبدك، وأنا على عهدك ووعدك ما استطعت",
    "رضيت بالله رباً، وبالإسلام ديناً، وبمحمد صلى الله عليه وسلم نبياً ورسولاً",
    "حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم",
]

# قائمة أدعية مخصصة للمملكة العربية السعودية
SAUDI_PRAYERS = [
    "اللهم احفظ المملكة العربية السعودية وبارك في أمنها ورخائها وولاة أمرها وشعبها",
    "اللهم أدِم على السعودية أمنها وأمانها واحفظها من كل شر وسوء",
    "اللهم اجعل هذا البلد آمناً مطمئناً وسائر بلاد المسلمين واحفظ وطننا السعودية",
    "اللهم احفظ خادم الحرمين الشريفين وولي عهده الأمين وبارك في جهودهما لخدمة الوطن",
    "اللهم إنا استودعناك السعودية أمنها وأرضها وسمائها وسلامة أهلها",
    "اللهم انصر قواتنا المرابطة واحفظ حدودنا وجد ليالينا بالأمن والأمان يا رب العالمين",
]

# قاموس لتتبع وقت آخر رد لكل مستخدم بشكل مستقل (Cooldown 15 ثانية لكل يوزر)
user_reply_time = {}


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
    self.last_saudi_prayer = None

  async def event_ready(self):
    print(f"تم الاتصال بنجاح! ({self.nick}) يعمل كـ Bot للردود والتذكيرات.")
    asyncio.create_task(start_web_server())
    asyncio.create_task(self.periodic_reminders())

  async def is_channel_live(self, channel_name):
    try:
      streams = await self.fetch_streams(user_logins=[channel_name])
      return len(streams) > 0
    except Exception:
      return False

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
        message_text = (
            f"صلوا على النبي واذكروا الله، {self.get_random_saudi_prayer()}"
        )
      elif step == 1:
        message_text = self.get_random_dhikr()
      else:
        message_text = "اشربوا مويا لا تنشفون"

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

    username = message.author.name.lower()
    current_time = time.time()

    # فحص الكول داون لكل يوزر (15 ثانية)
    if username in user_reply_time and current_time - user_reply_time[username] < 15:
      return

    channel_name = message.channel.name
    is_live = await self.is_channel_live(channel_name)
    if not is_live:
      return

    content = message.content.strip().lower()
    author_mention = f"@{message.author.name}"
    
    clean_content = re.sub(r"[^\w\s]", "", content)
    normalized_content = re.sub(r'(.)\1+', r'\1', clean_content)
    
    words = clean_content.split()
    norm_words = normalized_content.split()

    if not words:
      return

    # تجاهل تماماً إذا كانت الرسالة تحتوي على "وعليكم"
    has_already_replied_greeting = "وعليكم" in normalized_content or "وعليكم" in clean_content

    # فحص أن الرسالة هي إلقاء سلام (وليس رد سلام)
    has_greeting = False
    if not has_already_replied_greeting:
      if norm_words[0] in ["سلام", "السلام"] or "السلام عليكم" in content or "سلام عليكم" in content:
        has_greeting = True

    has_evening = "مساء" in normalized_content
    has_morning = "صباح" in normalized_content
    has_back = norm_words[0] in ["باك", "bak", "back"] if norm_words else False
    has_brb = norm_words[0] in ["برب", "brb"] if norm_words else False

    replied = False

    if has_greeting:
      await message.channel.send(
          f"{author_mention} وعليكم السلام ورحمة الله وبركاته، نورت البث"
      )
      replied = True
    elif has_evening:
      await message.channel.send(f"{author_mention} مساء النور والسرور")
      replied = True
    elif has_morning:
      await message.channel.send(f"{author_mention} صباح النور")
      replied = True
    elif has_back:
      await message.channel.send(f"{author_mention} ولكم باك")
      replied = True
    elif has_brb:
      await message.channel.send(f"{author_mention} خذ راحتك")
      replied = True

    if replied:
      user_reply_time[username] = current_time
      await self.handle_commands(message)


if __name__ == "__main__":
  bot = Bot()
  bot.run()
