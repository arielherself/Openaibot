# -*- coding: utf-8 -*-
# @Time    : 9/22/22 11:04 PM
# @FileName: Event.py
# @Software: PyCharm
# @Github    ：sudoskys
import asyncio
# 事件，完全隔离的

import json
import pathlib
import random
import re
import time
# from io import BytesIO
from typing import Union
from loguru import logger
import openai_kira
from openai_kira.Chat import Optimizer
from openai_kira.utils.chat import Cut

# from App.chatGPT import PrivateChat
from utils.Chat import Utils, Usage, rqParser, GroupManger, UserManger, Header, Style
from utils.Data import DictUpdate, DefaultData, Api_keys, Service_Data, User_Message, PublicReturn, ProxyConfig
from utils.Setting import ProfileReturn
from utils.TTS import TTS_Clint, TTS_REQ
from utils.Detect import DFA, Censor, get_start_name
from utils import budgetSet

#

# fast text langdetect

_service = Service_Data.get_key()
REDIS_CONF = _service["redis"]
TTS_CONF = _service["tts"]
PLUGIN_TABLE = _service["plugin"]
PROXY_CONF = ProxyConfig(**_service["proxy"])
HARM_TYPE = _service["moderation_type"]
HARM_TYPE.extend([
    'violence',
    'violence/graphic'
])
HARM_TYPE = list(set(HARM_TYPE))

# Proxy

if PROXY_CONF.status:
    openai_kira.setting.proxyUrl = PROXY_CONF.url,
openai_kira.setting.redisSetting = openai_kira.setting.RedisConfig(**REDIS_CONF)

urlForm = {
    "Danger.form": [
        "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL2Z3d2RuL3NlbnNpdGl2ZS1zdG9wLXdvcmRzL21hc3Rlci8lRTYlOTQlQkYlRTYlQjIlQkIlRTclQjElQkIudHh0",
        "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL1RlbGVjaGFCb3QvQW50aVNwYW0vbWFpbi9EYW5nZXIudHh0",
        "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL2FkbGVyZWQvRGFuZ2Vyb3VzU3BhbVdvcmRzL21hc3Rlci9EYW5nZXJvdXNTcGFtV29yZHMvR2VuZXJhbF9TcGFtV29yZHNfVjEuMC4xX0NOLm1pbi50eHQ=",
        "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL0phaW1pbjEzMDQvc2Vuc2l0aXZlLXdvcmQtZGV0ZWN0b3IvbWFpbi9zYW1wbGVfZmlsZXMvc2FtcGxlX2Jhbm5lZF93b3Jkcy50eHQ=",
    ]
}


def initCensor():
    if PROXY_CONF.status:
        proxies = {
            'all://': PROXY_CONF.url,
        }  # 'http://127.0.0.1:7890'  # url
        return Censor.initWords(url=urlForm, home_dir="./Data/", proxy=proxies)
    else:
        return Censor.initWords(url=urlForm, home_dir="./Data/")


if not pathlib.Path("./Data/Danger.form").exists():
    initCensor()
# 过滤器
ContentDfa = DFA(path="./Data/Danger.form")

global _csonfig


# IO
def load_csonfig():
    global _csonfig
    now_table = DefaultData.defaultConfig()
    if pathlib.Path("./Config/config.json").exists():
        with open("./Config/config.json", encoding="utf-8") as f:
            _csonfig = json.load(f)
    else:
        _csonfig = {}
    DictUpdate.dict_update(now_table, _csonfig)
    _csonfig = now_table
    return _csonfig


def save_csonfig(pLock=None):
    if pLock:
        pLock.acquire()
    with open("./Config/config.json", "w+", encoding="utf8") as f:
        json.dump(_csonfig, f, indent=4, ensure_ascii=False)
    if pLock:
        pLock.release()


async def TTSSupportCheck(text, user_id):
    global TTS_CONF
    """
    处理消息文本并构造请求返回字节流或者空。隶属 Event 文件
    :return:
    """
    if not TTS_CONF["status"]:
        return
    if TTS_CONF['type'] == 'none':
        return

    try:
        from fatlangdetect import detect
        lang_type = detect(text=text.replace("\n", "").replace("\r", ""), low_memory=True).get("lang").upper()
    except Exception as e:
        from langdetect import detect
        lang_type = detect(text=text.replace("\n", "").replace("\r", ""))[0][0].upper()

    if TTS_CONF["type"] == "vits":
        _vits_config = TTS_CONF["vits"]
        if lang_type not in ["ZH", "JA"]:
            return
        if len(text) > _vits_config["limit"]:
            return
        cn_res = Cut.chinese_sentence_cut(text)
        cn = {i: f"[{lang_type}]" for i in cn_res}
        # 合成
        _spell = [f"{cn[x]}{x}{cn[x]}" for x in cn.keys()]
        _new_text = "".join(_spell)
        _new_text = "[LENGTH]1.4[LENGTH]" + _new_text
        # 接受数据
        result, e = await TTS_Clint.request_vits_server(url=_vits_config["api"],
                                                        params=TTS_REQ(task_id=user_id,
                                                                       text=_new_text,
                                                                       model_name=_vits_config["model_name"],
                                                                       speaker_id=_vits_config["speaker_id"],
                                                                       audio_type="ogg"
                                                                       ))

        if not result:
            logger.error(f"TTS:{user_id} --type:vits --content: {text}:{len(text)} --{e}")
            return
        logger.info(f"TTS:{user_id} --type:vits --content: {text}:{len(text)}")
        # 返回字节流
        return result
    # USE AZURE
    elif TTS_CONF["type"] == "azure":
        _azure_config = TTS_CONF["azure"]
        _new_text = text
        _speaker = _azure_config["speaker"].get(lang_type)
        if len(text) > _azure_config["limit"]:
            return
        if not _speaker:
            logger.info(f"TTS:{user_id} --type:azure --content: {text}:{len(text)} --this type lang not supported")
            return
        result, e = await TTS_Clint.request_azure_server(key=_azure_config["key"],
                                                         location=_azure_config["location"],
                                                         text=_new_text,
                                                         speaker=_speaker
                                                         )
        if not result:
            logger.error(f"TTS:{user_id} --type:azure --content: {text}:{len(text)} --{e}")
            return

        logger.info(f"TTS:{user_id} --type:azure --content: {text}:{len(text)}")
        # 返回字节流
        return result
    else:
        # 啥也没有
        return


async def Forget(user_id: int, chat_id: int):
    """
    重置消息流
    :param chat_id:
    :param user_id:
    :return:
    """
    from openai_kira.utils.data import MsgFlow
    _cid = DefaultData.composing_uid(user_id=user_id, chat_id=chat_id)
    budgetSet.delete(user_id)
    return MsgFlow(uid=_cid).forget()


class Reply(object):
    """
    群组
    """

    @staticmethod
    async def load_response(user,
                            group,
                            key: Union[str, list],
                            prompt: str = "Say this is a test",
                            method: str = "chat",
                            start_name: str = "Ai:",
                            restart_name: str = "Human:"
                            ) -> str:
        """
        发起请求
        :param start_name: 称呼自己
        :param restart_name: 称呼请求发起人
        :param user:
        :param group:
        :param key:
        :param prompt:
        :param method:
        :return:
        """
        load_csonfig()
        # 载入全局变量
        if not key:
            logger.error("SETTING:API key missing")
            raise Exception("API key missing")
        openai_kira.setting.openaiApiKey = key

        # 洪水防御攻击
        if Utils.WaitFlood(user=user, group=group):
            return "TOO FAST"

        # 长度限定
        if Utils.tokenizer(str(prompt)) > _csonfig['input_limit']:
            return "TOO LONG"

        # 用量检测
        # _UsageManger = Usage(uid=user)
        # _Usage = _UsageManger.isOutUsage()
        # if _Usage["status"]:
        #     return f"小时额度或者单人总额度用完，请申请重置或等待\n{_Usage['use']}"

        # 内容审计
        try:
            _harm = False
            _Moderation_rep = await openai_kira.Moderations().create(input=prompt)
            _moderation_result = _Moderation_rep["results"][0]
            _harm_result = [key for key, value in _moderation_result["categories"].items() if value == True]
            for item in _harm_result:
                if item in HARM_TYPE:
                    _harm = item
        except Exception as e:
            logger.error(f"Moderation：{prompt}:{e}")
            _harm = False
        if _harm:
            _info = DefaultData.getRefuseAnswer()
            await asyncio.sleep(random.randint(3, 6))
            return f"{_info}\nYour Content violates Openai policy:{_harm}..."

        # 内容过滤
        prompt = ContentDfa.filter_all(prompt)

        # 请求
        try:
            from openai_kira import Chat
            # 计算唯一消息桶 ID
            _cid = DefaultData.composing_uid(user_id=user, chat_id=group)
            # 启用单人账户桶
            if len(start_name) > 12:
                start_name = start_name[-10:]
            if len(restart_name) > 12:
                restart_name = restart_name[-10:]
            # 分发类型
            if method == "write":
                # OPENAI
                response = await openai_kira.Completion(call_func=Api_keys.pop_api_key).create(
                    model="text-davinci-003",
                    prompt=str(prompt),
                    temperature=0.2,
                    frequency_penalty=1,
                    max_tokens=int(_csonfig["token_limit"])
                )
            elif method == "catch":
                # 群组公用桶 ID
                _oid = f"-{abs(group)}"
                receiver = Chat.Chatbot(
                    conversation_id=int(_oid),
                    call_func=Api_keys.pop_api_key,
                    token_limit=1000,
                    start_sequ=start_name,
                    restart_sequ=restart_name,
                )
                response = await receiver.get_chat_response(model="text-davinci-003",
                                                            prompt=str(prompt),
                                                            optimizer=Optimizer.MatrixPoint,
                                                            head=".",
                                                            frequency_penalty=0.5,  # 不要用用过的字符
                                                            presence_penalty=-0.5,  # 不要谈论新话题
                                                            max_tokens=100,
                                                            web_enhance_server=PLUGIN_TABLE
                                                            )
            elif method == "chat":
                receiver = Chat.Chatbot(
                    conversation_id=int(_cid),
                    call_func=Api_keys.pop_api_key,
                    token_limit=3751,
                    start_sequ=start_name,
                    restart_sequ=restart_name,
                )
                _head = None
                if _csonfig.get("allow_change_head"):
                    _head = Header(uid=user).get()
                    _head = ContentDfa.filter_all(_head)

                _style = {}
                if _csonfig.get("allow_change_style"):
                    _style = Style(uid=user).get()
                response = await receiver.get_chat_response(model="text-davinci-003",
                                                            prompt=str(prompt),
                                                            max_tokens=int(_csonfig["token_limit"]),
                                                            role=_head,
                                                            web_enhance_server=PLUGIN_TABLE,
                                                            logit_bias=_style
                                                            )
            else:
                return "NO SUPPORT METHOD"
            # print(response)
            _deal_rq = rqParser.get_response_text(response)
            _deal = _deal_rq[0]
            _usage = rqParser.get_response_usage(response)
            _time = int(time.time() * 1000)
            logger.success(f"CHAT:{user}:{group} --time: {_time} --prompt: {prompt} --req: {_deal} ")
        except Exception as e:
            logger.error(f"RUN:Api Error:{e}")
            _usage = 0
            _deal = f"OH no,api Outline or crash? \n {prompt}"
        # 更新额度
        # _AnalysisUsage = _UsageManger.renewUsage(usage=_usage)
        # 更新统计
        # DefaultData().setAnalysis(usage={f"{user}": _AnalysisUsage.total_usage})
        # 人性化处理
        _deal = ContentDfa.filter_all(_deal)
        _deal = Utils.Humanization(_deal)
        return _deal


async def WhiteUserCheck(user_id: int, WHITE: str = "") -> PublicReturn:
    """
    :param user_id: user id
    :param WHITE: 白名单提示
    :return: TRUE,msg -> 在白名单
    """
    #
    if _csonfig["whiteUserSwitch"]:
        # 没有在白名单里！
        if UserManger(user_id).read("white"):
            return PublicReturn(status=True, trace="WhiteUserCheck")
        msg = f"{user_id}:Check the settings to find that you is not whitelisted!...{WHITE}"
        if UserManger(user_id).read("block"):
            msg = f"{user_id}:Blocked!...{WHITE}"
        return PublicReturn(status=False,
                            trace="WhiteUserCheck",
                            msg=msg)
    else:
        return PublicReturn(status=True, trace="WhiteUserCheck")


async def WhiteGroupCheck(group_id: int, WHITE: str = "") -> PublicReturn:
    """
    :param group_id: group id
    :param WHITE:
    :return: TRUE,msg -> 在白名单
    """
    #
    if _csonfig["whiteGroupSwitch"]:
        # 没有在白名单里！
        if GroupManger(group_id).read("white"):
            return PublicReturn(status=True, trace="WhiteUserCheck")
        msg = f"{group_id}:Check the settings to find that you is not whitelisted!...{WHITE}"
        if GroupManger(group_id).read("block"):
            msg = f"{group_id}:Blocked!...{WHITE}"
        return PublicReturn(status=False,
                            trace="WhiteUserCheck",
                            msg=msg)
    else:
        return PublicReturn(status=True, trace="WhiteUserCheck")


async def RemindSet(user_id, text, bypass=False) -> PublicReturn:
    """
    :param user_id:
    :param text:
    :return: Ture 代表设定成功
    """
    _text = text
    _user_id = user_id
    _remind_r = _text.split(" ", 1)
    if len(_remind_r) < 2:
        return PublicReturn(status=False, msg=f"", trace="Remind")
    _remind = _remind_r[1]
    # if Utils.tokenizer(_remind) > 333:
    #     return PublicReturn(status=True, msg=f"过长:{_remind}", trace="Remind")
    _remind = ContentDfa.filter_all(_remind)
    if bypass:
        if budgetSet.detect(user_id) == False:
            budgetSet.write(user_id)
            _remind = _remind.replace("你", "ME*")
            _remind = _remind.replace("我", "YOU*")
            _remind = _remind.replace("YOU*", "你")
            _remind = _remind.replace("ME*", "我")
            Header(uid=_user_id).set(_remind)
        return PublicReturn(status=True, msg=f"设定:{_remind}\nNo reply this msg", trace="Remind") 
    elif _csonfig.get("allow_change_head"):
        # _remind = _remind.replace("你是", "ME*扮演")
        _remind = _remind.replace("你", "ME*")
        _remind = _remind.replace("我", "YOU*")
        _remind = _remind.replace("YOU*", "你")
        _remind = _remind.replace("ME*", "我")
        Header(uid=_user_id).set(_remind)
        return PublicReturn(status=True, msg=f"设定:{_remind}\nNo reply this msg", trace="Remind")
    Header(uid=_user_id).set({})
    return PublicReturn(status=True, msg=f"I refuse Remind Command", trace="Remind")


async def StyleSet(user_id, text) -> PublicReturn:
    """
    :param user_id:
    :param text:
    :return: Ture 代表设定成功
    """
    _text = text
    _user_id = user_id
    _style_r = _text.split(" ", 1)
    if len(_style_r) < 2:
        return PublicReturn(status=False, msg=f"", trace="StyleSet")
    _style = _style_r[1]
    if Utils.tokenizer(_style) > 800:
        return PublicReturn(status=True, msg=f"过长:{_style}", trace="StyleSet")
    _style_token_list = re.split("[,，]", _style)
    _token = {}
    if _csonfig.get("allow_change_style"):
        for item in _style_token_list:
            item = str(item)
            _weight = round(item.count("(") + item.count("{") + 1 - item.count("[") * 1.5)
            item = item.replace("(", "").replace("{", "").replace("[", "").replace(")", "").replace("}", "").replace(
                "]", "")
            _weight = _weight if _weight <= 20 else 2
            _weight = _weight if _weight >= -80 else 0
            _encode_token = openai_kira.utils.chat.gpt_tokenizer.encode(item)
            _love = {str(token): _weight for token in _encode_token}
            _child_token = {}
            for token, weight in _love.items():
                token = str(token)
                if token in _token.keys():
                    __weight = _token.get(token) + _weight
                else:
                    __weight = _weight
                _child_token[token] = __weight
            _token.update(_child_token)
        Style(uid=_user_id).set(_token)
        return PublicReturn(status=True, msg=f"Style:{_style}\nNo reply this msg", trace="StyleSet")
    Style(uid=_user_id).set(_token)
    return PublicReturn(status=True, msg=f"I refuse StyleSet Command", trace="StyleSet")


async def PromptPreprocess(text, types: str = "group") -> PublicReturn:
    """
    消息预处理，命令识别和与配置的交互层
    :param text:
    :param types:
    :return: TRUE,msg -> 继续执行
    """
    load_csonfig()
    # 拿到 prompt
    _raw_prompt = text
    _prompt_types = "unknown"
    _prompt = ""
    # 不会重复的流程组
    # Chat
    if _raw_prompt.startswith("/chat"):
        _prompt_r = _raw_prompt.split(" ", 1)
        if len(_prompt_r) > 1:
            _prompt = _prompt_r[1]
        _prompt_types = "chat"
    # Write
    if _raw_prompt.startswith("/catch"):
        _prompt_r = _raw_prompt.split(" ", 1)
        if len(_prompt_r) > 1:
            _prompt = _prompt_r[1]
        _prompt_types = "catch"
    # Write
    if _raw_prompt.startswith("/write"):
        _prompt_r = _raw_prompt.split(" ", 1)
        if len(_prompt_r) > 1:
            _prompt = _prompt_r[1]
        _prompt_types = "write"
    # 处置空，也许是多余的
    if len(_prompt) < 1:
        _prompt_types = "unknown"
    # 校验结果
    if _prompt_types == "unknown":
        # 不执行
        return PublicReturn(status=False, msg=types, data=[_prompt, _prompt_types], trace="PromptPreprocess")
    return PublicReturn(status=True, msg=types, data=[_prompt, _prompt_types], trace="PromptPreprocess")


async def Group(Message: User_Message, bot_profile: ProfileReturn, config) -> PublicReturn:
    """
    根据文本特征分发决策
    :param bot_profile:
    :param Message:
    :param config:
    :return: True 回复用户
    """
    load_csonfig()
    _text = Message.text
    _user_id = Message.from_user.id
    _chat_id = Message.from_chat.id
    _user_name = Message.from_user.name
    _bot_name = bot_profile.bot_name
    # 状态
    if not _csonfig.get("statu"):
        return PublicReturn(status=True, msg="BOT:Under Maintenance", trace="Statu")
    # 白名单检查
    _white_user_check = await WhiteGroupCheck(_chat_id, config.WHITE)
    _white_user_check: PublicReturn
    if not _white_user_check.status:
        return PublicReturn(status=True,
                            trace="WhiteGroupCheck",
                            msg=_white_user_check.msg)
    # 线性决策
    if _text.startswith("/remind"):
        _remind_set = await RemindSet(user_id=_user_id, text=_text)
        _remind_set: PublicReturn
        return PublicReturn(status=True,
                            trace="Remind",
                            msg=_remind_set.msg)

    if _text.startswith("/style"):
        _style_set = await StyleSet(user_id=_user_id, text=_text)
        _style_set: PublicReturn
        return PublicReturn(status=True,
                            trace="Style",
                            msg=_style_set.msg)

    if _text.startswith("/forgetme"):
        await Forget(user_id=_user_id, chat_id=_chat_id)
        return PublicReturn(status=True, msg=f"Down,Miss you", trace="ForgetMe")
    if _text.startswith("/voice"):
        _user_manger = UserManger(_user_id)
        _set = True
        if _user_manger.read("voice"):
            _set = False
        _user_manger.save({"voice": _set})
        return PublicReturn(status=True, msg=f"TTS:{_set}", trace="VoiceSet")
    _prompt_preprocess = await PromptPreprocess(text=_text, types="group")
    _prompt_preprocess: PublicReturn
    if not _prompt_preprocess.status:
        # 预处理失败，不符合任何触发条件，不回复捏
        return PublicReturn(status=False, msg=f"No Match Type", trace="PromptPreprocess")
    _prompt = _prompt_preprocess.data[0]
    _reply_type = _prompt_preprocess.data[1]
    try:
        _name = f"{_user_name}"
        _req = await Reply.load_response(user=_user_id,
                                         group=_chat_id,
                                         key=Api_keys.get_key("./Config/api_keys.json")["OPENAI_API_KEY"],
                                         prompt=_prompt,
                                         restart_name=_name,
                                         start_name=get_start_name(prompt=_prompt, bot_name=_bot_name),
                                         method=_reply_type
                                         )

        # message_type = "text"
        _info = []
        # 语音消息
        _voice = UserManger(_user_id).read("voice")
        voice_data = None
        if _voice:
            voice_data = await TTSSupportCheck(text=_req, user_id=_user_id)
        if not voice_data and _voice:
            _info.append("TTS Unavailable")
        # message_type = "voice" if _voice and voice_data else message_type
        # f"{_req}\n{config.INTRO}\n{''.join(_info)}"
        _log = '\n'.join(_info)
        return PublicReturn(status=True, msg=f"OK", trace="Reply", voice=voice_data, reply=f"{_req}\n{_log}")
    except Exception as e:
        logger.error(e)
        return PublicReturn(status=True, msg=f"OK", trace="Error", reply="Error Occur~Maybe Api request rate limit~nya")


async def Friends(Message: User_Message, bot_profile: ProfileReturn, config) -> PublicReturn:
    """
    根据文本特征分发决策
    :param bot_profile:
    :param Message:
    :param config:
    :return: True 回复用户
    """
    load_csonfig()
    _text = Message.text
    _user_id = Message.from_user.id
    _chat_id = Message.from_chat.id
    _user_name = Message.from_user.name
    _bot_name = bot_profile.bot_name
    # 状态
    if not _csonfig.get("statu"):
        return PublicReturn(status=True, msg="BOT:Under Maintenance", trace="Statu")
    # 白名单检查
    _white_user_check = await WhiteUserCheck(_user_id, config.WHITE)
    _white_user_check: PublicReturn
    if not _white_user_check.status:
        return PublicReturn(status=True,
                            trace="WhiteGroupCheck",
                            msg=_white_user_check.msg)
    # 线性决策
    if _text.startswith("/remind"):
        _remind_set = await RemindSet(user_id=_user_id, text=_text)
        _remind_set: PublicReturn
        return PublicReturn(status=True,
                            trace="Remind",
                            msg=_remind_set.msg)

    if _text.startswith("/style"):
        _style_set = await StyleSet(user_id=_user_id, text=_text)
        _style_set: PublicReturn
        return PublicReturn(status=True,
                            trace="Style",
                            msg=_style_set.msg)

    if _text.startswith("/forgetme"):
        await Forget(user_id=_user_id, chat_id=_chat_id)
        return PublicReturn(status=True, msg=f"Down,Miss you", trace="ForgetMe")

    if _text.startswith("/voice"):
        _user_manger = UserManger(_user_id)
        _set = True
        if _user_manger.read("voice"):
            _set = False
        _user_manger.save({"voice": _set})
        return PublicReturn(status=True, msg=f"TTS:{_set}", trace="Voice")
    _prompt_preprocess = await PromptPreprocess(text=_text, types="private")
    _prompt_preprocess: PublicReturn
    if not _prompt_preprocess.status:
        # 预处理失败，不符合任何触发条件，不回复捏
        return PublicReturn(status=False, msg=f"No Match Type", trace="PromptPreprocess")
    _prompt = _prompt_preprocess.data[0]
    _reply_type = _prompt_preprocess.data[1]
    try:
        _name = f"{_user_name}"
        _req = await Reply.load_response(user=_user_id,
                                         group=_chat_id,
                                         key=Api_keys.get_key("./Config/api_keys.json")["OPENAI_API_KEY"],
                                         prompt=_prompt,
                                         restart_name=_name,
                                         start_name=get_start_name(prompt=_prompt, bot_name=_bot_name),
                                         method=_reply_type
                                         )

        message_type = "text"
        _info = []
        # 语音消息
        _voice = UserManger(_user_id).read("voice")
        voice_data = None
        if _voice:
            voice_data = await TTSSupportCheck(text=_req, user_id=_user_id)
        if not voice_data and _voice:
            _info.append("TTS Unavailable")
        message_type = "voice" if _voice and voice_data else message_type
        # f"{_req}\n{config.INTRO}\n{''.join(_info)}"
        _data = {"type": message_type, "msg": "".join(_info), "text": _req, "voice": voice_data}
        return PublicReturn(status=True,
                            msg=f"OK",
                            trace="Reply",
                            reply=_req + "\n".join(_info),
                            voice=voice_data
                            )
    except Exception as e:
        logger.error(e)
        return PublicReturn(status=True, msg=f"Error Occur~Maybe Api request rate limit~nya",
                            trace="Error",
                            reply="Error Occur~Maybe Api request rate limit~nya")


async def Trigger(Message: User_Message, config) -> PublicReturn:
    """
    :param Message: group id
    :param config:
    :return: TRUE,msg -> 在白名单
    """
    group_id = Message.from_chat.id
    if config.trigger:
        if GroupManger(group_id).read("trigger"):
            return PublicReturn(status=True, trace="TriggerCheck")
    return PublicReturn(status=False, trace="No trigger")


async def GroupAdminCommand(Message: User_Message, config, pLock):
    load_csonfig()
    _reply = []
    group_id = Message.from_chat.id
    try:
        command = Message.text
        if command.startswith("/trigger"):
            _group_manger = GroupManger(int(group_id))
            _set = True
            if _group_manger.read("trigger"):
                _set = False
            _group_manger.save({"trigger": _set})
            _ev = f"Group Admin:GroupTrigger {_set}"
            _reply.append(_ev)
            logger.info(_ev)
        #
    except Exception as e:
        logger.error(e)
    return _reply


async def MasterCommand(user_id: int, Message: User_Message, config, pLock=None):
    load_csonfig()
    _reply = []
    if user_id in config.master:
        try:
            command = Message.text
            # SET
            if command.startswith("/set_user_cold"):
                # 用户冷静时间
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["usercold_time"] = int(_len_)
                    _reply.append(f"user cooltime:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset user cold time limit to{_len_}")

            if command.startswith("/set_group_cold"):
                # 群组冷静时间
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["groupcold_time"] = int(_len_)
                    _reply.append(f"group cooltime:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset group cold time limit to{_len_}")

            if command.startswith("/set_per_user_limit"):
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["per_user_limit"] = int(_len_)
                    _reply.append(f"set_hour_limit:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset per_user_limit to{_len_}")

            if command.startswith("/set_per_hour_limit"):
                # 设定用户小时用量
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["hour_limit"] = int(_len_)
                    _reply.append(f"hour_limit:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset hour_limit to{_len_}")

            if command.startswith("/promote_user_limit"):
                # 设定用户小时用量
                _len = Utils.extract_arg(command)
                if len(_len) != 2:
                    return
                __user_id = int("".join(list(filter(str.isdigit, _len[0]))))
                __limit = int("".join(list(filter(str.isdigit, _len[1]))))
                if __user_id > 0 and __limit > 0:
                    UserManger(__user_id).save({"usage": __limit})
                    _reply.append(f"user_limit:{__limit}")
                    logger.info(f"SETTING:promote user_limit to{__limit}")

            if command.startswith("/reset_user_usage"):
                # 重置用户的用量总数据
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        Usage(uid=_len_).resetTotalUsage()
                        logger.info(f"SETTING:resetTotalUsage {_len_} limit to 0")
                        _reply.append(f"hour_limit:{_len}")

            if command.startswith("/set_token_limit"):
                # 返回多少？
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["token_limit"] = int(_len_)
                    _reply.append(f"tokenlimit:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset tokenlimit limit to{_len_}")

            if command.startswith("/set_input_limit"):
                # 输入字符？
                _len = Utils.extract_arg(command)[0]
                _len_ = "".join(list(filter(str.isdigit, _len)))
                if _len_:
                    _csonfig["input_limit"] = int(_len_)
                    _reply.append(f"input limit:{_len_}")
                    save_csonfig(pLock)
                    logger.info(f"SETTING:reset input limit to{_len_}")

            if "/add_block_group" in command:
                # 重置用户的用量总数据
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:add block group {_len_}"
                        GroupManger(int(_len_)).save({"block": True})
                        _reply.append(_ev)
                        logger.info(_ev)

            if "/del_block_group" in command:
                # 重置用户的用量总数据
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:del block group {_len_}"
                        GroupManger(int(_len_)).save({"block": False})
                        _reply.append(_ev)
                        logger.info(_ev)

            if "/add_block_user" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:add_block_userp {_len_}"
                        UserManger(int(_len_)).save({"block": True})
                        _reply.append(_ev)
                        logger.info(_ev)

            if "/del_block_user" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:del_block_user {_len_}"
                        UserManger(int(_len_)).save({"block": False})
                        _reply.append(_ev)
                        logger.info(_ev)

            # whiteGroup
            if "/add_white_group" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:add_white_group {_len_}"
                        GroupManger(int(_len_)).save({"white": True})
                        _reply.append(_ev)
                        logger.info(_ev)

            if "/del_white_group" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:del_white_group {_len_}"
                        GroupManger(int(_len_)).save({"white": False})
                        _reply.append(_ev)
                        logger.info(_ev)

            # whiteUser
            if "/add_white_user" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:add_white_user {_len_}"
                        UserManger(int(_len_)).save({"white": True})
                        _reply.append(_ev)
                        logger.info(_ev)

            if "/del_white_user" in command:
                _len = Utils.extract_arg(command)
                for i in _len:
                    _len_ = "".join(list(filter(str.isdigit, i)))
                    if _len_:
                        _ev = f"SETTING:del_white_user {_len_}"
                        UserManger(int(_len_)).save({"white": False})
                        _reply.append(_ev)
                        logger.info(_ev)

            # UPDATE
            if command.startswith("/update_detect"):
                keys, _error = initCensor()
                if _error:
                    error = '\n'.join(_error)
                    errors = f"Error:\n{error}"
                else:
                    # 重载 Danger 库
                    ContentDfa.change_words(path="./Data/Danger.form")
                    errors = "Success"
                _reply.append(f"{'|'.join(keys)}\n\n{errors}")

            # USER White
            if command.startswith("/open_user_white_mode"):
                _csonfig["whiteUserSwitch"] = True
                _reply.append("SETTING:whiteUserSwitch ON")
                save_csonfig(pLock)
                logger.info("SETTING:whiteUser ON")

            if command.startswith("/close_user_white_mode"):
                _csonfig["whiteUserSwitch"] = False
                _reply.append("SETTING:whiteUserSwitch OFF")
                save_csonfig(pLock)
                logger.info("SETTING:whiteUser OFF")

            # GROUP White
            if command.startswith("/open_group_white_mode"):
                _csonfig["whiteGroupSwitch"] = True
                _reply.append("ON:whiteGroup")
                save_csonfig(pLock)
                logger.info("SETTING:whiteGroup ON")

            if command.startswith("/close_group_white_mode"):
                _csonfig["whiteGroupSwitch"] = False
                _reply.append("SETTING:whiteGroup OFF")
                save_csonfig(pLock)
                logger.info("SETTING:whiteGroup OFF")

            if command.startswith("/see_api_key"):
                keys = Api_keys.get_key("./Config/api_keys.json")
                # 脱敏
                _key = []
                for i in keys["OPENAI_API_KEY"]:
                    _key.append(DefaultData.mask_middle(i, 10))
                _info = '\n'.join(_key)
                _reply.append(f"Now Have \n{_info}")

            if "/add_api_key" in command:
                _parser = Utils.extract_arg(command)
                if _parser:
                    Api_keys.add_key(key=str(_parser[0]).strip())
                logger.info("SETTING:ADD API KEY")
                _reply.append("SETTING:ADD API KEY")

            if "/del_api_key" in command:
                _parser = Utils.extract_arg(command)
                if _parser:
                    Api_keys.pop_key(key=str(_parser[0]).strip())
                logger.info("SETTING:DEL API KEY")
                _reply.append("SETTING:DEL API KEY")

            if "/enable_change_style" in command:
                _csonfig["allow_change_style"] = True
                _reply.append("SETTING:allow_change_style ON")
                save_csonfig(pLock)
                logger.info("SETTING:BOT ON")

            if "/disable_change_style" in command:
                _csonfig["allow_change_style"] = False
                _reply.append("SETTING:allow_change_style OFF")
                save_csonfig(pLock)
                logger.info("SETTING:BOT ON")

            if "/enable_change_head" in command:
                _csonfig["allow_change_head"] = True
                _reply.append("SETTING:allow_change_head ON")
                save_csonfig(pLock)
                logger.info("SETTING:BOT ON")

            if "/disable_change_head" in command:
                _csonfig["allow_change_head"] = False
                _reply.append("SETTING:allow_change_head OFF")
                save_csonfig(pLock)
                logger.info("SETTING:BOT ON")

            if command.startswith("/open"):
                _csonfig["statu"] = True
                _reply.append("SETTING:BOT ON")
                save_csonfig(pLock)
                logger.info("SETTING:BOT ON")

            if command.startswith("/close"):
                _csonfig["statu"] = False
                _reply.append("SETTING:BOT OFF")
                save_csonfig(pLock)
                logger.info("SETTING:BOT OFF")
        except Exception as e:
            logger.error(e)
        return _reply


async def Start(_):
    return f"Ping，Use /chat start a new chat loop"


async def About(config):
    return f"{config.ABOUT}"


async def Help(_):
    return """
Use /chat + 句子 启动消息流，只需要回复即可交谈。48小时前的消息不能回复。
Use /write +句子 进行空白的续写。
Use /remind 设置一个场景头，全程不会被裁剪。
Use /forgetme 遗忘过去，res history。
Use /voice 开启可能的 tts 支持。
Use /trigger Admin 可以开启主动回复模式。
Use /style 定制词汇风格，中文效果较弱，(增强),[减弱]。
"""
