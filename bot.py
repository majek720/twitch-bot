import asyncio
import os
from aiohttp import web
from twitchio.ext import commands

# 1. حل مشكلة Event Loop
asyncio.set_event_loop(asyncio.new_event_loop())

# 2. البيانات والتوكين
ACCESS_TOKEN = 'oauth:o0loluf3tnd57pdkio1o0q43e131ry'
CHANNELS = ['majek113']


# 3. سيرفر الويب المصغر
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
        asyncio.create_task(start_web_server())

    async def event_message(self, message):
        # تجاهل رسائل البوت نفسه
        if message.echo:
            return

        # طباعة الرسالة في السجلات للتأكد من قراءتها
        print(
            f'[{message.channel.name}] {message.author.name}: {message.content}'
        )

        content_lower = message.content.lower()

        # الرد التلقائي على التحية باستخدام message.send() مباشرة
        if any(
            word in content_lower
            for word in ['السلام عليكم', 'سلام', 'مرحبا', 'هلا', 'hi', 'hello']
        ):
            try:
                await message.send(
                    f'وعليكم السلام ورحمة الله وبركاته، أهلاً بك @{message.author.name}! ❤️'
                )
            except Exception as e:
                print(f'Error sending reply: {e}')

        await self.handle_commands(message)

    @commands.command(name='ping')
    async def ping_command(self, ctx: commands.Context):
        await ctx.send(f'Pong! @{ctx.author.name}')


if __name__ == '__main__':
    bot = Bot()
    bot.run()
