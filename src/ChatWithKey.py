"""
A simple wrapper for the official ChatGPT API
"""
import argparse
import json
import os
import sys

import requests
import tiktoken

from utils import create_completer
from utils import create_session
from utils import get_input

ENGINE = os.environ.get("GPT_ENGINE") or "gpt-3.5-turbo"
ENCODER = tiktoken.get_encoding("gpt2")


class Chatbot:
    """
    Official ChatGPT API
    """

    def __init__(
        self,
        api_key: str,
        engine: str = None,
        proxy: str = None,
        max_tokens: int = 3000,
        temperature: float = 0.5,
        top_p: float = 1.0,
        reply_count: int = 1,
        system_prompt: str = "You are ChatGPT, a large language model trained by OpenAI. Respond conversationally",
    ) -> None:
        """
        Initialize Chatbot with API key (from https://platform.openai.com/account/api-keys)
        """
        self.engine = engine or ENGINE
        self.session = requests.Session()
        self.api_key = api_key
        self.proxy = proxy
        if self.proxy:
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
            self.session.proxies = proxies
        self.conversation: dict = {
            "default": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
            ],
        }
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.reply_count = reply_count

        initial_conversation = "\n".join(
            [x["content"] for x in self.conversation["default"]],
        )
        if len(ENCODER.encode(initial_conversation)) > self.max_tokens:
            raise Exception("System prompt is too long")

    def __add_to_conversation(self, message: str, role: str, convo_id: str = "default"):
        """
        Add a message to the conversation
        """
        self.conversation[convo_id].append({"role": role, "content": message})

    def __truncate_conversation(self, convo_id: str = "default"):
        """
        Truncate the conversation
        """
        while True:
            full_conversation = "\n".join(
                [x["content"] for x in self.conversation[convo_id]],
            )
            if (
                len(ENCODER.encode(full_conversation)) > self.max_tokens
                and len(self.conversation[convo_id]) > 1
            ):
                # Don't remove the first message
                self.conversation[convo_id].pop(1)
            else:
                break

    def send_message(self, message: str, role: str = "user", convo_id: str = "default"):
        """
        Adds a message to the conversation without sending a request
        Allowed roles: user, system, assistant
        """
        self.__add_to_conversation(message, role, convo_id)

    def ask_stream(
        self,
        prompt: str,
        role: str = "user",
        convo_id: str = "default",
        **kwargs,
    ) -> str:
        """
        Ask a question
        """
        self.__add_to_conversation(prompt, "user")
        self.__truncate_conversation()
        # Get response
        response = self.session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {kwargs.get('api_key', self.api_key)}"},
            json={
                "model": self.engine,
                "messages": self.conversation[convo_id],
                "stream": True,
                # kwargs
                "temperature": kwargs.get("temperature", self.temperature),
                "top_p": kwargs.get("top_p", self.top_p),
                "n": kwargs.get("n", self.reply_count),
                "user": role,
            },
            stream=True,
        )
        if response.status_code != 200:
            raise Exception(
                f"Error: {response.status_code} {response.reason} {response.text}",
            )
        response_role: str = None
        full_response: str = ""
        for line in response.iter_lines():
            if not line:
                continue
            # Remove "data: "
            line = line.decode("utf-8")[6:]
            if line == "[DONE]":
                break
            resp: dict = json.loads(line)
            choices = resp.get("choices")
            if not choices:
                continue
            delta = choices[0].get("delta")
            if not delta:
                continue
            if "role" in delta:
                response_role = delta["role"]
            if "content" in delta:
                content = delta["content"]
                full_response += content
                yield content
        self.__add_to_conversation(full_response, response_role, convo_id=convo_id)

    def ask(self, prompt: str, role: str = "user", convo_id: str = "default", **kwargs):
        """
        Non-streaming ask
        """
        response = self.ask_stream(
            prompt=prompt,
            role=role,
            convo_id=convo_id**kwargs,
        )
        full_response: str = "".join(response)
        return full_response

    def rollback(self, n: int = 1, convo_id: str = "default"):
        """
        Rollback the conversation
        """
        for _ in range(n):
            self.conversation[convo_id].pop()

    def reset(self, convo_id: str = "default"):
        """
        Reset the conversation
        """
        self.conversation[convo_id] = [
            {"role": "system", "content": self.system_prompt},
        ]

    def save(self, file: str):
        """
        Save the conversation to a JSON file
        """
        try:
            with open(file, "w", encoding="utf-8") as f:
                json.dump(self.conversation, f, indent=2)
        except FileNotFoundError:
            print(f"Error: {file} cannot be created")

    def load(self, file: str):
        """
        Load the conversation from a JSON  file
        """
        try:
            with open(file, encoding="utf-8") as f:
                self.conversation = json.load(f)
        except FileNotFoundError:
            print(f"Error: {file} does not exist")

    def print_config(self, convo_id: str = "default"):
        """
        Prints the current configuration
        """
        print(
            f"""
ChatGPT Configuration:
  Messages:         {len(self.conversation[convo_id])} / {self.max_tokens}
  Engine:           {self.engine}
  Temperature:      {self.temperature}
  Top_p:            {self.top_p}
  Reply count:      {self.reply_count}
            """,
        )

    def print_help(self):
        """
        Prints the help message
        """
        print(
            """
Commands:
  !help           Display this message
  !rollback n     Rollback the conversation by n messages
  !save filename  Save the conversation to a file
  !load filename  Load the conversation from a file
  !reset          Reset the conversation
  !exit           Quit chat

Config Commands:
  !config         Display the current config
  !temperature n  Set the temperature to n
  !top_p n        Set the top_p to n
  !reply_count n  Set the reply_count to n
  !engine engine  Sets the chat model to engine
  """,
        )

    def handle_commands(self, input: str, convo_id: str = "default") -> bool:
        """
        Handle chatbot commands
        """
        command, *value = input.split(" ")
        if command == "!help":
            self.print_help()
        elif command == "!exit":
            exit()
        elif command == "!reset":
            self.reset(convo_id=convo_id)
            print("\nConversation has been reset")
        elif command == "!config":
            self.print_config(convo_id=convo_id)
        elif command == "!rollback":
            self.rollback(int(value[0]), convo_id=convo_id)
            print(f"\nRolled back by {value[0]} messages")
        elif command == "!save":
            self.save(value[0])
            print(f"\nConversation has been saved to {value[0]}")
        elif command == "!load":
            self.load(value[0])
            print(
                f"\n{len(self.conversation[convo_id])} messages loaded from {value[0]}",
            )
        elif command == "!temperature":
            self.temperature = float(value[0])
            print(f"\nTemperature set to {value[0]}")
        elif command == "!top_p":
            self.top_p = float(value[0])
            print(f"\nTop_p set to {value[0]}")
        elif command == "!reply_count":
            self.reply_count = int(value[0])
            print(f"\nReply count set to {value[0]}")
        elif command == "!engine":
            self.engine = value[0]
            print(f"\nEngine set to {value[0]}")
        else:
            return False

        return True


def main():
    """
    Main function
    """
    print(
        """
    ChatGPT - Official ChatGPT API
    Repo: github.com/acheong08/ChatGPT
    """,
    )
    print("Type '!help' to show a full list of commands")
    print("Press Esc followed by Enter or Alt+Enter to send a message.\n")

    # Get API key from command line
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api_key",
        type=str,
        required=True,
        help="OpenAI API key",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.5,
        help="Temperature for response",
    )
    parser.add_argument(
        "--no_stream",
        action="store_true",
        help="Disable streaming",
    )
    parser.add_argument(
        "--base_prompt",
        type=str,
        default="You are ChatGPT, a large language model trained by OpenAI. Respond conversationally",
        help="Base prompt for chatbot",
    )
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="Proxy address",
    )
    parser.add_argument(
        "--top_p",
        type=float,
        default=1,
        help="Top p for response",
    )
    parser.add_argument(
        "--reply_count",
        type=int,
        default=1,
        help="Number of replies for each prompt",
    )
    args = parser.parse_args()
    # Initialize chatbot
    chatbot = Chatbot(
        api_key=args.api_key,
        system_prompt=args.base_prompt,
        proxy=args.proxy,
        temperature=args.temperature,
        top_p=args.top_p,
        reply_count=args.reply_count,
    )
    session = create_session()
    completer = create_completer(
        [
            "!help",
            "!exit",
            "!reset",
            "!rollback",
            "!config",
            "!engine",
            "!temperture",
            "!top_p",
            "!reply_count",
            "!save",
            "!load",
        ],
    )
    # Start chat
    while True:
        print()
        try:
            print("User: ")
            prompt = get_input(session=session, completer=completer)
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit()
        if prompt.startswith("!") and chatbot.handle_commands(prompt):
            continue
        print()
        print("ChatGPT: ", flush=True)
        if args.no_stream:
            print(chatbot.ask(prompt, "user"))
        else:
            for response in chatbot.ask_stream(prompt):
                print(response, end="", flush=True)
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit()
