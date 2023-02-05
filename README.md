<p align="center">
    <img src="https://github.com/NGLSG/QChatBot/raw/main/img/self.png" width="200" height="200" alt="ChatBot">
</p>

<div align="center">

# ChatBot

_✨基于[ChatGPT](https://github.com/acheong08/ChatGPT)修改的,并使用[go-cqhttp](https://github.com/Mrs4s/go-cqhttp)转发ChatGPT的消息到QQ✨_  

如果你喜欢这个项目请点一个⭐吧(注意这是ChatGPT不是GPT3,请在试了之后再评论)

</div>
<p align="center">
  <img src="https://img.shields.io/badge/Author-Ge%E6%B1%81%E8%8F%8C-yellow">
  <a href="https://raw.githubusercontent.com/NGLSG/QChatBot/main/LICENSE">
    <img src="https://img.shields.io/github/license/NGLSG/ChatBot" alt="license">
  </a>
  <img src="https://img.shields.io/github/stars/NGLSG/QChatBot.svg" alt="stars">
  <img src="https://img.shields.io/github/forks/NGLSG/QChatBot.svg" alt="forks">
</p>


# 要求
* Python3 版本 >= 3.9
* Rust

# 安装
```
git clone https://github.com/NGLSG/ChatBot.git
cd py/
运行安装依赖.bat或者DependenceInstaller.sh
```



# 使用
请修改py/config.json中的`qq_on*`为你的机器人的qq和`*admin_qq`你的qq
修改QBot/config.yml中的 `uin`为机器人的qq `password`为机器人的qq密码
最后修改启动脚本中的 `api_key`为你的openAI的[密钥](https://platform.openai.com/account/api-keys)

此后你只需要运行对应系统的启动脚本即可

# 注意
如果你是Arm架构的机型,请将对应go-cqhttp的可执行文件修改为你的架构对应的执行文件[下载链接](https://github.com/Mrs4s/go-cqhttp/releases)
