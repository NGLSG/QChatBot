import json
import os

import openai


class Chatbot:
    client: openai.OpenAI
    conversionList: dict

    def __init__(self, apiKey: str, endPoint: str) -> None:
        self.conversationList = self.loadConversions()
        self.client = openai.OpenAI(api_key=apiKey, base_url=endPoint)

    def ask(self, prompt: str, conversation_id: str, role: str = "user"):
        if conversation_id not in self.conversationList:
            self.conversationList[conversation_id] = [{"role": "system", "content": "You are a helpful assistant"}]
        history = self.conversationList[conversation_id]
        newTry = {"role": role, "content": prompt}
        history.append(newTry)
        response = self.client.chat.completions.create(
            model="deepseek-chat",
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
