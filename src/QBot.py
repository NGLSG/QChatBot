import json
import os
import sys
import traceback
import uuid
from copy import deepcopy

import openai
import requests
from flask import request, Flask

from transformers import GPT2TokenizerFast

import atexit
import ChatBot
import ChatWithKey
from text_to_image import text_to_image

lastSession: str = ""
manager = []
admin = ""

with open("config.json", "r", encoding='utf-8') as jsonfile:
    config_data = json.load(jsonfile)
    qq_no = config_data['qq_bot']['qq_no']
    manager = config_data['qq_bot']['manager']
    admin = config_data['qq_bot']['admin']
    if admin not in manager:
        manager.append(admin)

session_config = {
    'preset': '',
    'context': ''
}

sessions = {}

# 创建一个服务，把当前这个python文件当做一个服务
server = Flask(__name__)

tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")

Conversations: dict = dict()

useApi: bool = False


def OnExit():
    for conversation in Conversations.values():
        print("删除:" + conversation + "\n")
        chatbot.delete_conversation(conversation)


atexit.register(OnExit)


def AddManager(uid: str):
    manager.append(uid)
    config_data['qq_bot']['manager'] = manager
    data = json.dumps(config_data, indent=4)
    with open("config.json", "w", encoding='utf-8') as jsonfile:
        jsonfile.write(data)


def DelManager(uid: str):
    manager.remove(uid)
    config_data['qq_bot']['manager'] = manager
    data = json.dumps(config_data, indent=4)
    with open("config.json", "w", encoding='utf-8') as jsonfile:
        jsonfile.write(data)


class Account:
    def __init__(self):
        self.passwd = ""
        self.email = ""
        self.session_token = ""
        self.api_key = ""
        self.proxy = ""
        self.init = Flase

    passwd = ""
    email = ""
    session_token = ""
    api_key = ""
    proxy = ""
    init = False


account = Account


# 测试接口，可以测试本代码是否正常启动
@server.route('/', methods=["GET"])
def index():
    return f"你好，QQ机器人逻辑处理端已启动<br/>"


def submitWithoutApiKey(prompt, sessionid) -> str:
    res = ""
    for data in chatbot.ask(
            prompt, conversation_id=sessionid
    ):
        message = data["message"][len(res):]
        print(message, end="", flush=True)
        res = data["message"]
    return res


def submit(prompt) -> str:
    res = ""
    for data in chatbot.ask_stream(prompt):
        # print(data, end="", flush=True)
        print(data, end="", flush=True)
        res += data
    return res


# qq消息上报接口，qq机器人监听到的消息内容将被上报到这里
@server.route('/', methods=["POST"])
def get_message():
    if request.get_json().get('message_type') == 'private':  # 如果是私聊信息
        uid = request.get_json().get('sender').get('user_id')  # 获取信息发送者的 QQ号码
        message = request.get_json().get('raw_message')  # 获取原始信息
        sender = request.get_json().get('sender')  # 消息发送者的资料
        print("收到私聊消息：")
        print(message)
        # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
        msg_text = chat(message, 'P' + str(uid), str(uid))  # 将消息转发给ChatGPT处理
        send_private_message(uid, msg_text)  # 将消息返回的内容发送给用户

    if request.get_json().get('message_type') == 'group':  # 如果是群消息
        gid = request.get_json().get('group_id')  # 群号
        uid = request.get_json().get('sender').get('user_id')  # 发言者的qq号
        message = request.get_json().get('raw_message')  # 获取原始信息
        # 判断当被@时才回答
        if str("[CQ:at,qq=%s]" % qq_no) in message:
            sender = request.get_json().get('sender')  # 消息发送者的资料
            print("收到群聊消息：")
            print(message)
            message = str(message).replace(str("[CQ:at,qq=%s]" % qq_no), '')
            # 下面你可以执行更多逻辑，这里只演示与ChatGPT对话
            msg_text = chat(message, 'G' + str(gid), str(uid), True)  # 将消息转发给ChatGPT处理

            send_group_message(gid, msg_text, uid)  # 将消息转发到群里
            id = "G" + str(gid)
    if request.get_json().get('post_type') == 'request':  # 收到请求消息
        print("收到请求消息")
        request_type = request.get_json().get('request_type')  # group
        uid = request.get_json().get('user_id')
        flag = request.get_json().get('flag')
        comment = request.get_json().get('comment')
        print("配置文件 auto_confirm:" + str(config_data['qq_bot']['auto_confirm']) + " admin: " + str(
            config_data['qq_bot']['admin']))
        if request_type == "friend":
            print("收到加好友申请")
            print("QQ：", uid)
            print("验证信息", comment)
            # 如果配置文件里auto_confirm为 TRUE，则自动通过
            if config_data['qq_bot']['auto_confirm']:
                set_friend_add_request(flag, "true")
            else:
                if str(uid) == config_data['qq_bot']['admin']:  # 否则只有管理员的好友请求会通过
                    print("管理员加好友请求，通过")
                    set_friend_add_request(flag, "true")
        if request_type == "group":
            print("收到群请求")
            sub_type = request.get_json().get('sub_type')  # 两种，一种的加群(当机器人为管理员的情况下)，一种是邀请入群
            gid = request.get_json().get('group_id')
            if sub_type == "add":
                # 如果机器人是管理员，会收到这种请求，请自行处理
                print("收到加群申请，不进行处理")
            elif sub_type == "invite":
                print("收到邀请入群申请")
                print("群号：", gid)
                # 如果配置文件里auto_confirm为 TRUE，则自动通过
                if config_data['qq_bot']['auto_confirm']:
                    set_group_invite_request(flag, "true")
                else:
                    if str(uid) == config_data['qq_bot']['admin']:  # 否则只有管理员的拉群请求会通过
                        set_group_invite_request(flag, "true")
    return "ok"


# 测试接口，可以用来测试与ChatGPT的交互是否正常，用来排查问题
@server.route('/chat', methods=['post'])
def chatapi():
    requestJson = request.get_data()
    if requestJson is None or requestJson == "" or requestJson == {}:
        resu = {'code': 1, 'msg': '请求内容不能为空'}
        return json.dumps(resu, ensure_ascii=False)
    data = json.loads(requestJson)
    print(data)
    try:
        msg = chat(data['msg'], '11111111')
        resu = {'code': 0, 'data': msg}
        return json.dumps(resu, ensure_ascii=False)
    except Exception as error:
        print("接口报错")
        resu = {'code': 1, 'msg': '请求异常: ' + str(error)}
        return json.dumps(resu, ensure_ascii=False)


def saveContent(uid: str, session):
    # chatHistory[uid] = session['context'] + message + "\n"
    data = json.dumps(session['context'], ensure_ascii=False, indent=3)
    with open("presets/" + uid + ".json", "w", encoding='utf-8') as f:
        f.write(data)


# 与ChatGPT交互的方法
def chat(msg, sessionid, uid="", isgroup=False):
    global lastSession
    try:
        if msg.strip() == '':
            return '您好，我是人工智能助手，如果您有任何问题，请随时告诉我，我将尽力回答。\n如果您需要重置我们的会话，请回复`重置会话`'
        # 获得对话session
        session = get_chat_session(sessionid)
        if '重置会话' == msg.strip():
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            if not useApi:
                chatbot.reset_chat()
            else:
                chatbot.reset()
            session['context'] = ''

            # saveContent(lastSession, session, "")
            return "重置成功"

        if msg.strip().startswith('保存会话'):
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            msessionid = msg.split(" ")[1]
            if not useApi:
                chatbot.change_title(chatbot.conversation_id, msessionid)
            # chatHistory[msessionid] = session['context']
            saveContent(msessionid, session)
            return "会话保存成功"

        if msg.strip().startswith('添加管理'):
            if uid != admin:
                return "非常抱歉,你没有权限"
            uid = msg.split(" ")[1]
            AddManager(uid)
            return ""

        if msg.strip().startswith('删除管理'):
            if uid != admin:
                return "非常抱歉,你没有权限"
            uid = msg.split(" ")[1]
            DelManager(uid)
            return ""

        if msg.strip().startswith('加载会话'):
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            msessionid = msg.split(" ")[1]
            lastSession = msessionid
            if msessionid.isspace() | len(msessionid) == 0:
                return "你输入的会话不合法,请检查是否传入的会话名为空"
            try:
                if not os.path.exists("presets/" + lastSession + ".json"):
                    return "无法找到的会话:  " + lastSession
                data: str
                with open("presets/" + lastSession + ".json", 'r', encoding='utf-8') as f:
                    data = f.read()
                session['context'] = json.loads(data)
            except Exception as error:
                traceback.print_exc()
                return error
            return "会话以加载"

        if msg.strip().startswith('删除会话'):
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            if not useApi:
                chatbot.reset_chat()
            else:
                chatbot.reset()
            msessionid = msg.split(" ")[1]
            lastSession = ""
            if msessionid.isspace() | len(msessionid) == 0:
                return "你输入的会话不合法,请检查是否传入的会话名为空"
            try:
                if not useApi:
                    chatbot.delete_conversation(chatbot.conversation_id)
                    Conversations.pop(session)
                os.remove("presets/" + msessionid + ".json")
            except Exception as error:
                traceback.print_exc()
                return error
            return "会话以删除"

        if '指令说明' == msg.strip():
            return "指令如下(群内需@机器人)：\n" \
                   "1.[重置会话] 请发送 重置会话\n" \
                   "2.[保存会话] 请发送保存会话 [会话ID(如果不填则为当前会话)]\n" \
                   "3.[加载会话] 请发送加载会话 [会话ID]" \
                   "4.[删除会话] 请发送删除会话 [会话ID]\n" \
                   "5.[添加管理] 请发送添加管理 [QQ]\n" \
                   "6.[删除管理] 请发送删除管理 [QQ]\n" \
                   "7.[指令说明] 获取帮助"

        if (not sessionid in Conversations.keys()) and (not useApi):
            CreateConversion(sessionid)
        # 处理上下文逻辑
        token_limit = 4096 - config_data['chatgpt']['max_tokens'] - len(tokenizer.encode(session['preset'])) - 3
        session['context'] = session['context'] + "\n\nQ:" + msg + "\nA:"
        ids = tokenizer.encode(session['context'])
        tokens = tokenizer.decode(ids[-token_limit:])
        # 计算可发送的字符数量
        char_limit = len(''.join(tokens))
        session['context'] = session['context'][-char_limit:]
        # 从最早的提问开始截取
        pos = session['context'].find('Q:')
        session['context'] = session['context'][pos:]
        # 设置预设
        msg = session['preset'] + '\n\n' + session['context']
        # 与ChatGPT交互获得对话内容

        if (not useApi):
            message = askWithoutKey(msg, Conversations[sessionid])
        else:
            message = ask(msg)
        print("会话ID: " + str(sessionid))
        print("ChatGPT返回内容: ")
        print(message)

        return message
    except Exception as error:
        traceback.print_exc()
        return str('异常: ' + str(error))


# 获取对话session
def get_chat_session(sessionid):
    if sessionid not in sessions:
        config = deepcopy(session_config)
        config['id'] = sessionid
        sessions[sessionid] = config
    return sessions[sessionid]


def askWithoutKey(prompt, sessionid):
    try:
        resp = submitWithoutApiKey(prompt, sessionid)
    except openai.OpenAIError as e:
        print('openai 接口报错: ' + str(e))
        resp = str(e)
    return resp


def ask(prompt):
    try:
        resp = submit(prompt)
    except openai.OpenAIError as e:
        print('openai 接口报错: ' + str(e))
        resp = str(e)
    return resp


# 生成图片
def genImg(message):
    img = text_to_image(message)
    filename = str(uuid.uuid1()) + ".png"
    filepath = config_data['qq_bot']['image_path'] + str(os.path.sep) + filename
    print(filename)
    img.save(filepath)
    print("图片生成完毕: " + filepath)
    return filename


def genVoice(message):
    sound_url = "http://tts.youdao.com/fanyivoice?word=" + message + "&le=zh&keyfrom=speaker-target"
    filename = str(uuid.uuid1()) + ".mp3"
    filepath = config_data['qq_bot']['sound_path'] + str(os.path.sep) + filename
    r = requests.get(sound_url)  # create HTTP response object
    with open(filepath, 'wb') as f:
        f.write(r.content)
    return filename


# 发送私聊消息方法 uid为qq号，message为消息内容
def send_private_message(uid, message):
    try:
        # if len(message) >= config_data['qq_bot']['max_length']:  # 如果消息长度超过限制，转成图片发送
        # voice_path = genVoice(message)
        # message = "[CQ:record,file=" + voice_path + "]"
        # pic_path = genImg(message)
        # message = "[CQ:image,file=" + pic_path + "]"

        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_private_msg",
                            params={'user_id': int(uid), 'message': message}).json()

        if res["status"] == "ok":
            print("私聊消息发送成功")
        else:
            print(res)
            print("私聊消息发送失败，错误信息：" + str(res['wording']))

    except Exception as error:
        print("私聊消息发送失败")
        print(error)


# 发送私聊消息方法 uid为qq号，pic_path为图片地址
def send_private_message_image(uid, pic_path, msg):
    try:
        message = "[CQ:image,file=" + pic_path + "]"
        if msg != "":
            message = msg + '\n' + message
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_private_msg",
                            params={'user_id': int(uid), 'message': message}).json()

        if res["status"] == "ok":
            print("私聊消息发送成功")
        else:
            print(res)
            print("私聊消息发送失败，错误信息：" + str(res['wording']))

    except Exception as error:
        print("私聊消息发送失败")
        print(error)


# 发送群消息方法
def send_group_message(gid, message, uid):
    try:
        # if len(message) >= config_data['qq_bot']['max_length']:  # 如果消息长度超过限制，转成图片发送
        # pic_path = genImg(message)
        # message = "[CQ:image,file=" + pic_path + "]"
        message = str('[CQ:at,qq=%s]\n' % uid) + message  # @发言人
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_group_msg",
                            params={'group_id': int(gid), 'message': message}).json()
        if res["status"] == "ok":
            print("群消息发送成功")
        else:
            print("群消息发送失败，错误信息：" + str(res['wording']))
    except Exception as error:
        print("群消息发送失败")
        print(error)


# 发送群消息图片方法
def send_group_message_image(gid, pic_path, uid, msg):
    try:
        message = "[CQ:image,file=" + pic_path + "]"
        if msg != "":
            message = msg + '\n' + message
        message = str('[CQ:at,qq=%s]\n' % uid) + message  # @发言人
        res = requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/send_group_msg",
                            params={'group_id': int(gid), 'message': message}).json()
        if res["status"] == "ok":
            print("群消息发送成功")
        else:
            print("群消息发送失败，错误信息：" + str(res['wording']))
    except Exception as error:
        print("群消息发送失败")
        print(error)


# 处理好友请求
def set_friend_add_request(flag, approve):
    try:
        requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/set_friend_add_request",
                      params={'flag': flag, 'approve': approve})
        print("处理好友申请成功")
    except:
        print("处理好友申请失败")


# 处理邀请加群请求
def set_group_invite_request(flag, approve):
    try:
        requests.post(url=config_data['qq_bot']['cqhttp_url'] + "/set_group_add_request",
                      params={'flag': flag, 'sub_type': 'invite', 'approve': approve})
        print("处理群申请成功")
    except:
        print("处理群申请失败")


def CreateConversion(sessionid):
    try:
        global chatbot, useApi, account
        if not account.init:
            account = Account
            with open("config.json", "r", encoding='utf-8') as jsonfile:
                config_data = json.load(jsonfile)
                account.email = config_data['account']['email']
                account.passwd = config_data['account']['password']
                account.session_token = config_data['account']['session_token']
                account.api_key = config_data['account']['api_key']
                account.proxy = config_data['account']['proxy']
                account.init = True

        if not account.api_key.strip() == '':
            useApi = True
            chatbot = ChatWithKey.Chatbot(api_key=account.api_key, proxy=account.proxy)
        elif not account.email.strip() == '':
            if account.passwd.strip() == '':
                chatbot = ChatBot.Chatbot(config={
                    "email": account.email,
                    "session_token": account.session_token,
                    "proxy": account.proxy
                })
            elif account.session_token.strip() == '':
                chatbot = ChatBot.Chatbot(config={
                    "email": account.email,
                    "password": account.passwd,
                    "proxy": account.proxy
                })
            res = ""
            for data in chatbot.ask(
                    "1+1=多少?",
            ):
                message = data["message"][len(res):]
                print(message, end="", flush=True)
            Conversations[sessionid] = chatbot.conversation_id
        elif account.email.strip() == '':
            print("账号邮箱不能为空!")
            sys.exit()
        else:
            print("api_key或密码或token必须提供一个!")
            sys.exit()
    except Exception as e:
        print(e)


if __name__ == '__main__':
    server.run(port=5555, host='0.0.0.0', use_reloader=False)
