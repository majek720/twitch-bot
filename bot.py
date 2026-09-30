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

# القنوات المعنية (تمت إضافة vul1_)
CHANNELS = ["majek113", "teamiik", "iz0yi", "sh_2i", "vul1_"]

# قائمة الأذكار (بدون إيموجيات)
DHIKR_LIST = [
    "سبحان الله وبحمده، سبحان الله العظيم",
    "لا إله إلا أنت سبحانك إني كنت من الظالمين",
    "لا حول ولا قوة إلا بالله العلي العظيم",
    "أستغفر الله العظيم وأتوب إليه",
    "سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر",
    "اللهم أعنا على ذكرك وشكرك وحسن عبادتك",
]

# متغيّر لتتبع آخر وقت رد لتطبيق الـ Cooldown (5 ثوانٍ)
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
        super().__init__(
            token=ACCESS_TOKEN, prefix="", initial_channels=CHANNELS
        )
        self.last_dhikr = None

    async def event_ready(self):
        print(
            f"تم الاتصال بنجاح! حسابك ({self.nick}) يعمل الآن كبوت رد تلقائي."
        )
        print(f'القنوات المتصل بها: {", ".join(CHANNELS)}')

        # تشغيل سيرفر الويب في الخلفية لـ Render
        asyncio.create_task(start_web_server())

        # بدء التذكيرات التناوبية كل 30 دقيقة
        asyncio.create_task(self.periodic_reminders())

    async def is_channel_live(self, channel_name):
        """فحص ما إذا كانت القناة تبث حالياً (Online)"""
        try:
            streams = await self.fetch_streams(user_logins=[channel_name])
            return len(streams) > 0
        except Exception as e:
            print(f"خطأ أثناء التحقق من حالة القناة {channel_name}: {e}")
            return False

    def get_random_dhikr(self):
        """اختيار ذكر عشوائي دون تكرار نفس الذكر السابق مباشرة"""
        available = [d for d in DHIKR_LIST if d != self.last_dhikr]
        selected = random.choice(available)
        self.last_dhikr = selected
        return selected

    async def periodic_reminders(self):
        """مهمة تذكير دائرية كل 30 دقيقة: صلاة على النبي -> ذكر -> ماي"""
        step = 0  # 0: صلاة على النبي, 1: ذكر, 2: ماي

        while True:
            await asyncio.sleep(1800)  # الانتظار 30 دقيقة (1800 ثانية)

            # تجهيز الرسالة بناءً على الخطوة الحالية (بدون إيموجي)
            if step == 0:
                message_text = "اللهم صلِّ وسلم على نبينا محمد"
            elif step == 1:
                message_text = self.get_random_dhikr()
            else:
                message_text = "اشربوا ماااااااي"

            # إرسال الرسالة للقنوات الباثة حالياً
            for channel_name in CHANNELS:
                is_live = await self.is_channel_live(channel_name)
                if is_live:
                    channel = self.get_channel(channel_name)
                    if channel:
                        await channel.send(message_text)

            # للانتقال للخطوة التالية بالدور (0 -> 1 -> 2 -> 0)
            step = (step + 1) % 3

    async def event_message(self, message):
        # تجاهل الرسائل المرسلة من حساب البوت نفسه
        if message.echo:
            return

        # تجاهل الرسائل إذا كانت صادرة من حسابك الشخصي majek113
        if message.author.name.lower() == "majek113":
            return

        # تطبيق Cooldown لمدة 5 ثوانٍ على القناة لتفادي السبيام
        channel_name = message.channel.name
        current_time = time.time()
        if (
            channel_name in last_reply_time
            and current_time - last_reply_time[channel_name] < 5
        ):
            return

        # التحقق مما إذا كانت القناة الحالية اونلاين (تبث الآن)
        is_live = await self.is_channel_live(channel_name)
        if not is_live:
            return

        content = message.content.strip().lower()
        author_mention = f"@{message.author.name}"

        # تنظيف النص وتقسيمه إلى كلمات منفصلة
        clean_content = re.sub(r"[^\w\s]", "", content)
        words = clean_content.split()

        if not words:
            return

        has_evening = "مساء الخير" in content

        has_full_greeting = (
            "السلام عليكم" in content or "سلام عليكم" in content
        )
        has_single_greeting = words[0] in ["السلام", "سلام"]

        has_greeting = has_full_greeting or has_single_greeting

        replied = False

        # 1. إذا جمع المتابع بين السلام ومساء الخير في نفس الرسالة
        if has_greeting and has_evening:
            await message.channel.send(
                f"{author_mention} وعليكم السلام ورحمة الله وبركاته، ومساء النور نورت البث"
            )
            replied = True

        # 2. الرد على "مساء الخير" فقط
        elif has_evening:
            await message.channel.send(f"{author_mention} مساء النور")
            replied = True

        # 3. الرد على "باك" ككلمة منفصلة في البداية فقط
        elif words[0] == "باك":
            await message.channel.send(f"{author_mention} ولكم باك")
            replied = True

        # 4. الرد على "برب" أو "brb" ككلمة منفصلة في البداية فقط
        elif words[0] in ["برب", "brb"]:
            await message.channel.send(
                f"{author_mention} خذ راحتك بس لا تطول علينا"
            )
            replied = True

        # 5. الرد على السلام المنفصل فقط
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
