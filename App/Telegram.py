# -*- coding: utf-8 -*-
# @Time    : 9/22/22 11:04 PM
# @FileName: Controller.py.py
# @Software: PyCharm
# @Github: sudoskys

import asyncio
import pathlib
import time
from collections import deque

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from telebot import util, types
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_storage import StateMemoryStorage

from App import Event
from utils import Setting, budgetSet
from utils.Chat import Utils
from utils.Data import DefaultData, User_Message, create_message, PublicReturn, Service_Data
from utils.Frequency import Vitality
from utils.Base import Tool

LOGIC = ''

time_interval = 60
# 使用 deque 存储请求时间戳
request_timestamps = deque()
ProfileManager = Setting.ProfileManager()


async def set_cron(funcs, second: int):
    """
    启动一个异步定时器
    :param funcs: 回调函数
    :param second: 秒数
    :return:
    """
    tick_scheduler = AsyncIOScheduler()
    tick_scheduler.add_job(funcs, trigger='interval', max_instances=10, seconds=second)
    tick_scheduler.start()


def get_message(message: types.Message):
    # 自动获取名字
    first_name = message.from_user.first_name if message.from_user.first_name else ""
    last_name = message.from_user.last_name if message.from_user.last_name else ""
    _name = f"{first_name}{last_name}"
    if len(_name) > 12 and len(f"{last_name}") < 6:
        _name = f"{last_name}"
    group_name = message.chat.title if message.chat.title else message.chat.last_name
    group_name = group_name if group_name else "Group"
    return create_message(
        state=100,
        user_id=message.from_user.id,
        user_name=_name,
        group_id=message.chat.id,
        text=message.text,
        group_name=group_name
    )


class BotRunner(object):
    def __init__(self, config):
        self.bot = config
        self.proxy = Tool().dictToObj(Service_Data.get_key()['proxy'])

    def botCreate(self):
        if not self.bot.botToken:
            return None, None
        bot = AsyncTeleBot(self.bot.botToken, state_storage=StateMemoryStorage())
        return bot, self.bot

    def run(self, pLock=None):
        # print(self.bot)
        bot, _config = self.botCreate()
        if not bot:
            logger.info("APP:Telegram Bot Close")
            return
        logger.success("APP:Telegram Bot Start")
        if self.proxy.status:
            from telebot import asyncio_helper
            asyncio_helper.proxy = self.proxy.url
            logger.info("Telegram Bot Using proxy!")

        # 管理员权限
        async def is_admin(message: types.Message):
            _got = await bot.get_chat_member(message.chat.id, message.from_user.id)
            return _got.status in ['administrator', 'creator']

        # 私聊起动机
        @bot.message_handler(commands=["start", 'about', "help"], chat_types=['private'])
        async def handle_command(message):
            _hand = get_message(message)
            _hand: User_Message
            if "/start" in _hand.text:
                await bot.reply_to(message, await Event.Start(_config))
            elif "/about" in _hand.text:
                await bot.reply_to(message, await Event.About(_config))
            elif "/help" in _hand.text:
                await bot.reply_to(message, await Event.Help(_config))

        # 群聊
        @bot.message_handler(content_types=['text'], chat_types=['supergroup', 'group'])
        async def group_msg(message):
            _hand = get_message(message)
            _hand: User_Message
            started = False
            
            #############
            if budgetSet.doorman(_hand.from_user.id) == False:              # Clear context
                await Event.Forget(_hand.from_user.id, _hand.from_chat.id)
            await Event.RemindSet(_hand.from_user.id, LOGIC, bypass=True)   # Brainwashing
            #############

            # 命令解析
            if _hand.text.startswith(("/chat", "/voice", "/write", "/forgetme","/style", "/remind")):
                started = True
            elif _hand.text.startswith("/"):
                _is_admin = await is_admin(message)
                if _is_admin:
                    _reply = await Event.GroupAdminCommand(Message=_hand, config=_config, pLock=pLock)
                    if _reply:
                        await bot.reply_to(message, "".join(_reply))

            # 回复逻辑判定
            if message.reply_to_message:
                if f"{message.reply_to_message.from_user.id}" == f"{Setting.ProfileManager().access_telegram(init=False).bot_id}":
                    if str(Utils.checkMsg(
                            f"{_hand.from_chat.id}{message.reply_to_message.id}")) == f"{_hand.from_user.id}":
                        if not _hand.text.startswith("/"):
                            _hand.text = f"/chat {_hand.text}"
                        started = True

            # 分发指令
            if _hand.text.startswith("/help"):
                await bot.reply_to(message, await Event.Help(_config))

            # 热力扳机
            if not started:
                _trigger_message = await Event.Trigger(_hand, _config)
                if _trigger_message.status:
                    _GroupTrigger = Vitality(group_id=_hand.from_chat.id)
                    _GroupTrigger.trigger(Message=_hand, config=_config)
                    _check = _GroupTrigger.check(Message=_hand)
                    if _check:
                        _hand.text = f"/catch {_hand.text}"
                        started = True

            # 触发
            if started:
                request_timestamps.append(time.time())
                _friends_message = await Event.Group(Message=_hand,
                                                     config=_config,
                                                     bot_profile=ProfileManager.access_telegram(init=False)
                                                     )
                _friends_message: PublicReturn
                if _friends_message.status:
                    if _friends_message.voice:
                        _caption = f"{_friends_message.reply}\n{_config.INTRO}"
                        msg = await bot.send_voice(chat_id=message.chat.id,
                                                   reply_to_message_id=message.id,
                                                   voice=_friends_message.voice,
                                                   caption=_caption
                                                   )
                    elif _friends_message.reply:
                        _caption = f"{_friends_message.reply}\n{_config.INTRO}"
                        msg = await bot.reply_to(message, _caption)
                    else:
                        msg = await bot.reply_to(message, _friends_message.msg)
                    Utils.trackMsg(f"{_hand.from_chat.id}{msg.id}", user_id=_hand.from_user.id)

        # 私聊
        @bot.message_handler(content_types=['text'], chat_types=['private'])
        async def handle_private_msg(message):
            _hand = get_message(message)
            # 检查管理员指令
            _real_id = message.from_user.id
            _hand: User_Message
            request_timestamps.append(time.time())
            if not _hand.text.startswith("/"):
                _hand.text = f"/chat {_hand.text}"
            # 交谈
            if _hand.text.startswith(
                    ("/chat", "/voice", "/write", "/forgetme", "/style","/remind")):
                _friends_message = await Event.Friends(Message=_hand,
                                                       config=_config,
                                                       bot_profile=ProfileManager.access_telegram(init=False)
                                                       )
                _friends_message: PublicReturn
                if _friends_message.status:
                    if _friends_message.voice:
                        _caption = f"{_friends_message.reply}\n{_config.INTRO}"
                        await bot.send_voice(chat_id=message.chat.id,
                                             reply_to_message_id=message.id,
                                             voice=_friends_message.voice,
                                             caption=_caption
                                             )
                    elif _friends_message.reply:
                        _caption = f"{_friends_message.reply}\n{_config.INTRO}"
                        await bot.reply_to(message, _caption)
                    else:
                        await bot.reply_to(message, _friends_message.msg)
            if _real_id in _config.master:
                _reply = await Event.MasterCommand(user_id=_real_id, Message=_hand, config=_config, pLock=pLock)
                # 检查管理员指令
                if _hand.text == "/config":
                    path = str(pathlib.Path().cwd()) + "/" + "Config/config.json"
                    if pathlib.Path(path).exists():
                        doc = open(path, 'rb')
                        await bot.send_document(message.chat.id, doc)
                    else:
                        _reply.append("没有找到配置文件")
                if _reply:
                    await bot.reply_to(message, "".join(_reply))

        from telebot import asyncio_filters
        bot.add_custom_filter(asyncio_filters.IsAdminFilter(bot))
        bot.add_custom_filter(asyncio_filters.ChatFilter())
        bot.add_custom_filter(asyncio_filters.StateFilter(bot))

        def get_request_frequency():
            # 检查队列头部是否过期
            while request_timestamps and request_timestamps[0] < time.time() - time_interval:
                request_timestamps.popleft()
            # 计算请求频率
            request_frequency = len(request_timestamps)
            DefaultData().setAnalysis(telegram=request_frequency)
            return request_frequency

        async def main():
            _me = await bot.get_me()
            _first_name = _me.first_name if _me.first_name else ""
            _last_name = _me.last_name if _me.last_name else ""
            _bot_id = _me.id
            _bot_name = f"{_first_name}{_last_name}"
            ProfileManager.access_telegram(bot_name=_bot_name[:6], bot_id=_bot_id, init=True)
            await asyncio.gather(
                bot.polling(non_stop=True, allowed_updates=util.update_types),
                set_cron(get_request_frequency, second=4)
            )

        asyncio.run(main())
