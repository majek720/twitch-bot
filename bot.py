import asyncio
import os
from twitchio.ext import commands

# 1. حل مشكلة Event Loop مع الإصدارات الحديثة على Render
asyncio.set_event_loop(asyncio.new_event_loop())

# 2. إعدادات البوت والاتصال
# ضع التوكين الخاص بك واسم القنوات التي تريد للبوت الانضمام لها
ACCESS_TOKEN = 'oauth:your_oauth_token_here'
CHANNELS = ['majek113']  # أضف بقية القنوات هنا مثل: ['channel1', 'channel2']


class Bot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=ACCESS_TOKEN,
            prefix='!',  # البادئة الخاصة بالأوامر (مثال: !ping)
            initial_channels=CHANNELS,
        )

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')

    async def event_message(self, message):
        # تجاهل الرسائل التي يرسلها البوت نفسه
        if message.echo:
            return

        # طباعة الرسائل في سجل التشغيل (Logs)
        print(f'[{message.channel.name}] {message.author.name}: {message.content}')

        # السماح بمعالجة الأوامر المكتوبة
        await self.handle_commands(message)

    @commands.command(name='ping')
    async def ping_command(self, ctx: commands.Context):
        await ctx.send(f'Pong! @{ctx.author.name}')


if __name__ == '__main__':
    bot = Bot()
    bot.run()
