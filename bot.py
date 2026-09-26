import asyncio
import os
from twitchio.ext import commands

# 1. حل مشكلة الـ Event Loop مع الإصدارات الحديثة
asyncio.set_event_loop(asyncio.new_event_loop())

# 2. البيانات والتوكين الخاص بك من الصورة
ACCESS_TOKEN = 'oauth:o0loluf3tnd57pdkio1o0q43e131ry'
CHANNELS = ['majek113']


class Bot(commands.Bot):

    def __init__(self):
        super().__init__(
            token=ACCESS_TOKEN,
            prefix='!',  # البادئة للأوامر
            initial_channels=CHANNELS,
        )

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')
        print('Bot is ready and running!')

    async def event_message(self, message):
        # تجاهل الرسائل الصادرة من البوت نفسه
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
