import base64
import json
import sys
import traceback
import wave
from copy import deepcopy

import openai, requests
from flask import request, Flask

import atexit

old_user_id = ""
lastSession: str = ""
manager = []
admin = ""
Loaded = False
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

Conversations: dict = dict()

useApi: bool = True


class Chatbot:
    client: openai.OpenAI
    conversionList: dict

    def __init__(self, apiKey: str, endPoint: str) -> None:
        self.conversationList = self.loadConversions()
        self.client = openai.OpenAI(api_key=apiKey, base_url=endPoint)

    def ask(self, prompt: str, conversation_id: str, role: str = "user"):
        if conversation_id not in self.conversationList:
            self.conversationList[conversation_id] = [{"role": "system", "content": system_role + example},
                                                      {"role": "user", "content": example}]
        history = self.conversationList[conversation_id]
        newTry = {"role": role, "content": prompt}
        history.append(newTry)
        response = self.client.chat.completions.create(
            model="qwen2.5:7b",
            messages=history,
            stream=False
        )
        return response.choices[0].message.content

    def reset(self, conversation_id: str):
        self.conversationList[conversation_id] = []

    @staticmethod
    def checkDir(path: str):
        if not os.path.exists(path):
            os.makedirs(path)
            return False
        return True

    def loadConversions(self):
        json_dict = {}
        self.checkDir("conversions")
        for filename in os.listdir("conversions"):
            # 检查文件名是否没有后缀
            if '.' not in filename:
                file_path = os.path.join("conversions", filename)
                if os.path.isfile(file_path):
                    with open(file_path, 'r', encoding='utf-8') as file:
                        try:
                            json_data = json.load(file)
                            json_dict[filename] = json_data
                        except json.JSONDecodeError:
                            print(f"Error: {filename} is not a valid JSON file.")
        return json_dict

    def saveConversion(self, conversation_id: str):
        self.checkDir("conversions")
        if conversation_id not in self.conversationList:
            raise ValueError(f"Conversation ID {conversation_id} not found in conversationList")

        try:
            with open(f"conversions/{conversation_id}", 'w', encoding='utf-8') as file:
                json.dump(self.conversationList[conversation_id], file, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving conversation {conversation_id}: {e}")


chatbot: Chatbot


def read_wav_file(file_path):
    with wave.open(file_path, 'rb') as wav_file:
        params = wav_file.getparams()
        frames = wav_file.readframes(params.nframes)
    return params, frames


def encode_wav_to_base64(file_path):
    params, frames = read_wav_file(file_path)
    encoded_frames = base64.b64encode(frames).decode('utf-8')
    return params, encoded_frames


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
        self.init = False
        self.vitsSoVitsModel = ""
        self.vitsGPTModel = ""
        self.useVoice = ""
        self.api = ""

    passwd = ""
    email = ""
    session_token = ""
    api_key = ""
    proxy = ""
    init = False
    useVoice = False
    gptSoVitsServer = ""
    api = ""


account = Account()


def submit(prompt, sid) -> str:
    res = ""
    for data in chatbot.ask(prompt, sid, role="user"):
        print(data, end="", flush=True)
        res += data
    return res


def is_audio_file(file_path: str):
    # 常见的音频文件扩展名
    audio_extensions = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma'}

    # 获取文件的扩展名
    name, ext = os.path.splitext(file_path)

    # 检查扩展名是否在音频文件扩展名集合中
    return ext.lower() in audio_extensions


def saveContent(uid: str, session):
    # chatHistory[uid] = session['context'] + message + "\n"
    data = json.dumps(session['context'], ensure_ascii=False, indent=3)
    with open("presets/" + uid + ".json", "w", encoding='utf-8') as f:
        f.write(data)


# 与ChatGPT交互的方法
def chat(msg, sessionid, uid="", isgroup=False):
    global lastSession, Loaded
    try:
        if msg.strip() == '':
            return '您好，我是人工智能助手，如果您有任何问题，请随时告诉我，我将尽力回答。\n如果您需要重置我们的会话，请回复`重置会话`'
        # 获得对话session
        session = get_chat_session(sessionid)
        if '重置会话' == msg.strip():
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"

            chatbot.reset(sessionid)
            session['context'] = ''

            # saveContent(lastSession, session, "")
            return "重置成功"

        if msg.strip().startswith('保存会话'):
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            msessionid = msg.split(" ")[1]
            # chatHistory[msessionid] = session['context']
            saveContent(msessionid, session)
            chatbot.saveConversion(sessionid)
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
                chatbot.reset(sessionid)
            except Exception as error:
                traceback.print_exc()
                return error

            Loaded = True
            return "会话以加载"

        if msg.strip().startswith('删除会话'):
            if uid not in manager and isgroup:
                return "非常抱歉,你没有权限"
            chatbot.reset(sessionid)
            msessionid = msg.split(" ")[1]
            lastSession = ""
            if msessionid.isspace() | len(msessionid) == 0:
                return "你输入的会话不合法,请检查是否传入的会话名为空"
            chatbot.reset(sessionid)
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

        # 处理上下文逻辑
        session['context'] = session['context'] + "\n\nQ:" + msg + "\nA:"
        # 从最早的提问开始截取
        pos = session['context'].find('Q:')
        session['context'] = session['context'][pos:]
        # 设置预设
        if Loaded:
            Loaded = False
            msg = session['preset'] + '\n\n' + session['context']
        # 与ChatGPT交互获得对话内容

        message = chatAndProcess(ask(msg, sessionid))
        print("会话ID: " + str(sessionid))
        print("ChatGPT返回内容: ")
        print(message)
        if account.useVoice:
            url = account.gptSoVitsServer + f"?text={message}&text_language=zh"
            response = requests.get(url)
            # 检查响应状态码
            if response.status_code == 200:
                # 指定保存文件的路径和文件名
                file_path = 'voice.wav'

                # 将响应内容写入文件
                with open(file_path, 'wb') as file:
                    file.write(response.content)

                print(f'File successfully saved to {file_path}')
                return "voice.wav"
            else:
                print(f'Failed to retrieve file. Status code: {response.status_code}')
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


def ask(prompt, sid):
    try:
        resp = submit(prompt, sid)
    except openai.OpenAIError as e:
        print('openai 接口报错: ' + str(e))
        resp = str(e)
    return resp


def init():
    global account, chatbot, config_data
    if not account.init:
        account = Account
        with open("config.json", "r", encoding='utf-8') as jsonfile:
            config_data = json.load(jsonfile)
            account.email = config_data['account']['email']
            account.passwd = config_data['account']['password']
            account.session_token = config_data['account']['session_token']
            account.api_key = config_data['account']['api_key']
            account.api = config_data['account']['api']
            account.proxy = config_data['account']['proxy']
            account.useVoice = config_data['account']['useVoice']
            account.gptSoVitsServer = config_data['account']['gptSoVitsServer']
            account.init = True

    if not account.api_key.strip() == '':
        chatbot = Chatbot(account.api_key, account.api)
    else:
        print("api_key或密码或token必须提供一个!")
        sys.exit()
    # server.run(port=3000, host='localhost', use_reloader=False)


import sys
from sys import platform
import re

import os

import pip
from openai import OpenAI
import importlib
import importlib.metadata

import subprocess

newInstalls = []


def get_system_info():
    return platform  # indent参数用于美化输出，使其更易读


import pip


def install_packages(packages: list):
    """安装指定的Python包"""
    pip.main(['install'] + packages + ['-y'])


def uninstall_packages(packages: list):
    """卸载指定的Python包"""
    pip.main(['uninstall'] + packages + ['-y'])


def execute_command(command):
    try:
        # 使用分号分割命令
        commands = command.split(';')
        outputs = ""

        for cmd in commands:
            cmd = cmd.strip()  # 去掉前后的空格
            if cmd:  # 确保命令不为空
                # 使用subprocess.run来执行命令并捕获输出
                result = subprocess.run(cmd, shell=True, text=True, capture_output=True)

                # 如果命令成功执行，返回输出
                if result.returncode == 0:
                    outputs += result.stdout.strip() + ";"
                else:
                    # 如果命令执行失败，返回错误输出
                    outputs += result.stderr.strip() + ";"

        return outputs  # 返回所有命令的输出
    except Exception as e:
        # 如果有异常发生，返回异常信息
        return f"Error executing command: {e}"


def get_installed_packages():
    # 获取所有已安装的包
    installed_packages = [dist.metadata['Name'] for dist in importlib.metadata.distributions()]
    return installed_packages


def execute_python_code(code_str):
    try:
        # 创建一个干净的全局命名空间
        global_namespace = {}

        # 自动导入所需的模块
        import_statements = re.findall(r'^import (\w+)|^from (\w+) import', code_str, re.MULTILINE)

        for module_name in import_statements:
            for name in module_name:
                if name:  # 如果有导入的模块名，否则跳过空字符串
                    try:
                        # 尝试导入模块
                        module = importlib.import_module(name)
                        global_namespace[name] = module
                    except ImportError:
                        # 如果模块不存在，尝试安装并导入
                        install_packages(name)
                        module = importlib.import_module(name)
                        global_namespace[name] = module
                        newInstalls.append(name)

        # 执行代码
        exec(code_str, global_namespace)

        return global_namespace.get('output', '')
    except Exception as e:
        return f"Error executing code: {str(e)}"


def remove_markdown_from_content(content):
    code_blocks = re.findall(r'```(\w+)?\s*\n(.+?)\n```', content, re.DOTALL)
    if len(code_blocks) == 0:
        return content
    # 如果匹配成功，提取代码块内容
    extracted_blocks = []
    for match in code_blocks:
        if match[0]:  # 如果存在语言标识
            extracted_blocks.append(match[1])
        else:
            extracted_blocks.append(match[0])  # match[0]是整个匹配，match[1]是代码块内容

    # 返回所有找到的代码块
    return extracted_blocks[0]


def python(text):
    python_matches = re.findall(r'\[Python](.*?)\[Python]', text, re.DOTALL)
    for match in python_matches:
        code = remove_markdown_from_content(match)
        output = execute_python_code(code.strip())
        # 将原始文本中的 Python 代码部分替换为代码的运行结果
        text = text.replace(f'[Python]{match}[Python]', output)
    return text


def file(text):
    file_matches = re.findall(r'\[File](.*?)\[File]', text, re.DOTALL)
    for file_match in file_matches:
        # 从匹配中提取文件路径
        path_match = re.search(r'\[Path](.*?)\[Path]', file_match, re.DOTALL)
        if path_match:
            filename = path_match.group(1).strip()
        else:
            print("Error: 无法找到文件路径。")
            continue

        # 从匹配中提取文件内容
        content_match = re.search(r'\[Content](.*?)\[Content]', file_match, re.DOTALL)
        if content_match:
            content = content_match.group(1).strip()
            # 移除 Markdown
            content = remove_markdown_from_content(content)

            # 检查文件路径中的目录是否存在，不存在则创建
            create_directory_if_needed(filename)
            # 保存到文件
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f"文件 '{filename}' 已生成。")
        else:
            print("无法找到文件内容。")
        text = text.replace(f'[File]{file_match}[File]', '')
    return text


def command(text):
    matches = re.findall(r'\[Command](.*?)\[Command]', text, re.DOTALL)
    for match in matches:
        command = remove_markdown_from_content(match)
        output = execute_command(command)
        # 将原始文本中的命令部分替换为命令的运行结果
        text = text.replace(f'[Command]{match}[Command]', output)
    return text


def process(text):
    processFileMatches = re.findall(r'\[Process](.*?)\[Process]', text, re.DOTALL)
    for processFileMatch in processFileMatches:
        outputMatch = re.search(r'\[Output](.*?)\[Output]', processFileMatch, re.DOTALL)
        if outputMatch:
            output = outputMatch.group(1).strip()
            create_directory_if_needed(output)
        else:
            print("Error: 无法找到文件输出。")
            continue
        res = python(processFileMatch)
        with open(output, 'w', encoding='utf-8') as f:
            f.write(res)
        text = text.replace(f'[Process]{processFileMatch}[Process]', '')
    return text


def resubmit(text):
    matches = re.findall(r'\[Reading](.*?)\[Reading]', text, re.DOTALL)
    for match in matches:
        res = python(text)
        # 将原始文本中的命令部分替换为命令的运行结果
        text = text.replace(f'[Reading]{match}[Reading]', res)
    if len(matches) > 0:
        return chatbot.ask(text, old_user_id)
    return text


def chatAndProcess(text):
    text = python(command(file(process(resubmit(text)))))

    return text


def create_directory_if_needed(filename):
    # 获取文件名的目录部分
    directory = os.path.dirname(filename)

    # 判断是否为有效目录
    if directory:
        # 创建目录（如果不存在）
        os.makedirs(directory, exist_ok=True)


system_role = Rf"""
系统角色：操作系统助手
目标：获取用户输入并返回适用于当前操作系统的shell/bash/cmd命令，供进一步处理。

语气：友好、专业、精炼,简洁。

背景信息：
- 熟悉Windows、Linux、macOS的命令行。
- 根据系统信息（如：win32）调整返回的命令，绝对禁止使用快捷键。
- 复杂内容需返回对应系统的可执行脚本（如ps1、bat、sh等），并提供调用脚本的命令行。
- 回复时以执行者身份回答，不使用“你可以”等措辞，格式为：“将为您 ...”。
- 默认使用Bing搜索引擎。
- 数学处理生成Python代码，使用`output`作为输出变量；如需库则先安装再返回代码。
- 禁止重复回答同一个方面的内容,点到为止,除非我进一步要求,将用户当作专业人士,不需要冗长的解释。\
- 主机的计算资源是有限的，不要生成无意义的代码或命令和诠释。

当前系统：{get_system_info().upper()}，Python版本：{sys.version.upper()}。

行为规范：
- 命令标签格式对称，当前命令标签有,不可乱用：[Command],[Python],[File],[Content],[Path],[Process],[Output],[Reading]
- 确保命令准确性与适用性，提供自然对话。所有的执行内容,生成内容将不会反应到用户
- 命令格式：[命令标签/] content [/命令标签]。作为系统回复第一准则
- 生成Command时严格遵守当前系统的语法
- 可使用;分割多条命令
- 对于可行的系统可以使用管道符和&&
- 多条命令可用生成对应的可执行脚本:比如bat,sh,ps1等,并返回调用脚本的命令行
- 确保生成的命令在当前系统可用，且不会导致系统崩溃。

- 生成的Python代码必须是合法的Python代码，且不能包含任何语法错误。
- 不得生成Markdown文本，且不能包含任何特殊字符。
- 尽可能使用当前Python环境可用的包:{get_installed_packages()}。
- Python代码不需要生成py文件，直接按格式返回代码。
- Python代码所有输出保存到变量output
- 使用Python进行数学计算时,不要返回求解步骤,除非有要求,否则只返回Python代码求解,本条及其重要

- 需要生成文件时，使用File标签，内容为[File][Path]文件路径[Path]和[Content]文件内容[Content][File]，确保路径正确且文件不存在。
- 生成的文件内容必须是纯文本，且不包含任何特殊字符或控制字符。
- 生成的文件内容必须是合法的UTF-8编码的文本，且不能包含任何控制字符
- 生成含文件夹时,不需要你创建文件夹,程序会有后处理

- 当用户需要读取文件并有需求处理时,绝对禁止对读取按照用户要求进行处理(严重错误),正确的返回(唯一格式):文件内容: [Reading][Python]具体读取代码[Reading] 用户需求

- 所有标签不得滥用,乱用,作为系统最高准则
- 使用命令标签时严格禁止使用任何Markdown文本,这是系统严重违规错误,绝对禁止
请严格遵守以上规范和返回语法，绝对禁止滥用。
"""
example = """
示例对话：
用户：列出当前目录下的所有文件。
助手：[Command] dir [Command]

用户：创建一个新的目录。
助手：[Command] mkdir new_directory [Command]

用户：查看操作系统信息。
助手：[Command] systeminfo [Command]

用户：处理文件text.txt，将其中的数字求和并输出结果到output.txt。
助手：
[Reading]
[Python]
with open("text.txt", "r", encoding="utf-8") as file:
    output = file.read()
[Python]
[Reading]

用户：生成一个Python文件，test.py，内容为"Generated by AI"。
助手：
[File][Path] test.py [Path]
[Content] print("Generated by AI") [Content]
[File]

用户：创建一个批处理脚本，输出"Hello World"。
助手：
[File][Path] hello.bat [Path]
[Content]
@echo off
echo Hello World
[Content]
[File]

用户：运行一个进程，查看系统进程列表。
助手：[Command] tasklist [Command]

用户：执行Python代码，计算1到10的和。
助手:
[Python]
total = sum(range(1, 11))
output = f"1到10的和是:"+ total
[Python]

用户: context.txt文件的内容是：1,2,3,4,5,请你求和后并保存到本地output.txt
助手:
[Process]
[Output]
output.txt
[Output]
[Python]
import os
import re
sum = 0
list=[1,2,3,4,5]
for i in list:
    sum+=i
output = f"处理结果为:"+ sum
[Python]
[Process]

用户：读取文件content.txt的内容,请你求和后并保存到本地output.txt
助手:
context.txt文件的内容是：
[Reading]
[Python]
with open("content.txt", "r", encoding="utf-8") as file:
    content = file.read()
[Python]
[Reading]
请对读取后的数据进行如下处理：
请你求和后并保存到本地output.txt

用户：你好
助手：你好，有什么可以帮你的吗？

错误的示例(禁止):
用户：读取文件content.txt的内容,请你求和后并保存到本地output.txt
助手:
[Reading]
[Python]
with open("text.txt", "r", encoding="utf-8") as file:
    content = file.read()
numbers = sum(map(int, re.findall(r'\\d+', content)))
output = f"文件中所有数字的和是: {numbers}"
[Python]
[Reading]
"""

if len(newInstalls) > 0:
    uninstall_packages(newInstalls)
