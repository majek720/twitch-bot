import asyncio
import os
from aiohttp import web
from twitchio.ext import commands

# 1. حل مشكلة Event Loop
asyncio.set_event_loop(asyncio.new_event_loop())

# 2. البيانات الخاصة بك
ACCESS_TOKEN = 'oauth:o0loluf3tnd57pdkio1o0q43e131ry'
CHANNELS = ['majek113']


# 3. سيرفر الويب المصغر لإبقاء Render مستيقظاً عبر UptimeRobot
async def handle_ping(request):
    return web.Response(text="Bot is alive!")


async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server running on port {port}")


class Bot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=ACCESS_TOKEN,
            prefix='!',
            initial_channels=CHANNELS,
        )

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')
        # تشغيل سيرفر الويب في الخلفية
        asyncio.create_task(start_web_server())
        # تشغيل مهمة إرسال الرسائل التلقائية الدورية
        asyncio.create_task(self.auto_messages())

    async def event_message(self, message):
        # تجاهل الرسائل الصادرة من البوت نفسه
        if message.echo:
            return

        # 1. الرد التلقائي عند دخول شخص وإلقاء التحية (السلام عليكم / هلا / مرحبا)
        content_lower = message.content.lower()
        if any(
            word in content_lower
            for word in ['السلام عليكم', 'سلام', 'مرحبا', 'هلا', 'hi', 'hello']
        ):
            await message.channel.send(
                f'وعليكم السلام ورحمة الله وبركاته، أهلاً بك @{message.author.name}! ❤️'
            )

        # 2. الرد التلقائي على أي شخص يكتب في الشات (ترحيب آلي)
        # يمكنك تفعيل السطر التالي إذا أردت أن يرد البوت على كل رسالة تكتب:
        # await message.channel.send(f"أهلاً بك يا @{message.author.name} في البث!")

        await self.handle_commands(message)

    # 4. إرسال رسائل دورية تلقائية كل فترة زمنية (مثلاً كل 15 دقيقة)
    async def auto_messages(self):
        await self.wait_for_ready()
        channel = self.get_channel(CHANNELS[0])

        while True:
            # انتظر 15 دقيقة (900 ثانية)
            await asyncio.sleep(900)
            if channel:
                await channel.send(
                    '🤖 أهلاً بكم في القناة! لا تنسوا المتابعة وتفعيل التنبيهات!'
                )


if __name__ == '__main__':
    bot = Bot()
    bot.run()
