import asyncio
import os
from aiohttp import web
from twitchio.ext import commands

# تثبيت الـ Event Loop لبيئة Render
asyncio.set_event_loop(asyncio.new_event_loop())

ACCESS_TOKEN = "oauth:v4iyxh6mfgv2v9zqvnwdkfe125patj"

# القنوات المعنية
CHANNELS = ["majek113", "teamiik", "iz0yi", "mr_7sn__"]


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

    async def event_ready(self):
        print(
            f"تم الاتصال بنجاح! حسابك ({self.nick}) يعمل الآن كبوت رد تلقائي."
        )
        print(f'القنوات المتصل بها: {", ".join(CHANNELS)}')

        # تشغيل سيرفر الويب في الخلفية لـ Render
        asyncio.create_task(start_web_server())

        # بدء مهمة تذكير شرب الماء التلقائية كل 5 دقائق
        asyncio.create_task(self.water_reminder())

    async def is_channel_live(self, channel_name):
        """فحص ما إذا كانت القناة تبث حالياً (Online)"""
        try:
            streams = await self.fetch_streams(user_logins=[channel_name])
            return len(streams) > 0
        except Exception as e:
            print(f"خطأ أثناء التحقق من حالة القناة {channel_name}: {e}")
            return False

    async def water_reminder(self):
        """مهمة إرسال تذكير شرب الماء كل 5 دقائق فقط إذا كانت القناة اونلاين"""
        while True:
            await asyncio.sleep(300)  # الانتظار 5 دقائق
            for channel_name in CHANNELS:
                is_live = await self.is_channel_live(channel_name)
                if is_live:
                    channel = self.get_channel(channel_name)
                    if channel:
                        await channel.send("اشرب ماااااااي")

    async def event_message(self, message):
        # تجاهل الرسائل المرسلة من حساب البوت نفسه
        if message.echo:
            return

        # تجاهل الرسائل إذا كانت صادرة من حسابك الشخصي majek113
        if message.author.name.lower() == "majek113":
            return

        # التحقق مما إذا كانت القناة الحالية اونلاين (تبث الآن)
        is_live = await self.is_channel_live(message.channel.name)
        if not is_live:
            return

        content = message.content.strip().lower()
        author_mention = f"@{message.author.name}"

        # 1. الرد على "مساء الخير" في أي مكان في الجملة
        if "مساء الخير" in content:
            await message.channel.send(f"{author_mention} مساء النور")
            await self.handle_commands(message)
            return

        # 2. الرد على "باك" في بداية الجملة فقط
        if content.startswith("باك"):
            await message.channel.send(f"{author_mention} ولكم باك")
            await self.handle_commands(message)
            return

        # 3. الرد على "برب" أو "brb" في بداية الجملة فقط
        if content.startswith("برب") or content.startswith("brb"):
            await message.channel.send(
                f"{author_mention} خذ راحتك بس لا تطول علينا"
            )
            await self.handle_commands(message)
            return

        # 4. الرد على السلام الصريح فقط في بداية الجملة
        greetings = ("السلام عليكم", "سلام عليكم", "السلام", "سلام")
        if content.startswith(greetings):
            await message.channel.send(
                f"{author_mention} وعليكم السلام ورحمة الله وبركاته، نورت البث"
            )
            await self.handle_commands(message)
            return

        await self.handle_commands(message)


if __name__ == "__main__":
    bot = Bot()
    bot.run()
