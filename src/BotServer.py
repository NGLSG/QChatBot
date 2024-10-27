import sys

from NcatBot.ws import WebSocketClient
from NcatBot.hp import *
from NcatBot.message import *
import NcatBot.log as _log

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import QBot


# 定义回调函数
def on_meta_event(msg: EventMessage):
    pass


def on_message(msg: Message):
    QBot.old_user_id = msg.user_id
    if msg.message_type == "private":
        if msg.message[0]['type'] == 'text':
            res = QBot.chat(msg.message[0]['data']['text'], "P" + str(msg.user_id), str(msg.user_id))
            if res.find(".wav"):
                send_private_record(msg.user_id, res)
            send_private_msg(msg.user_id, res)

    elif msg.message_type == "group":
        send_group_msg(msg.group_id, QBot.chat(msg.message["text"], "P" + str(msg.user_id), str(msg.user_id), True))
    pass


def on_message_sent(msg):
    pass


def on_request(msg):
    pass


def on_notice(msg):
    pass


# 创建 WebSocketClient 实例并传递回调函数
client = WebSocketClient(url="ws://localhost:3001",
                         meta_event=on_meta_event,
                         message=on_message,
                         message_sent=on_message_sent,
                         request=on_request,
                         notice=on_notice)

QBot.init()
client.run()
