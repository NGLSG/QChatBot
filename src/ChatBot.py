"""
Standard ChatGPT
"""
from __future__ import annotations

import base64
import binascii
import contextlib
import datetime
import json
import logging
import time
import uuid
from functools import wraps
from os import environ
from os import getenv
from pathlib import Path
from typing import AsyncGenerator
from typing import Generator
from typing import NoReturn

import httpx
import requests
from httpx import AsyncClient
from OpenAIAuth import Authenticator
from OpenAIAuth import Error as AuthError

__version__ = "5.0.0"
import typings as t
from recipient import PythonRecipient
from recipient import Recipient
from recipient import RecipientManager
from utils import create_completer
from utils import create_session
from utils import get_input

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s",
    )

log = logging.getLogger(__name__)


def logger(is_timed: bool):
    """Logger decorator

    Args:
        is_timed (bool): Whether to include function running time in exit log

    Returns:
        _type_: decorated function
    """

    def decorator(func):
        wraps(func)

        def wrapper(*args, **kwargs):
            log.debug(
                "Entering %s with args %s and kwargs %s",
                func.__name__,
                args,
                kwargs,
            )
            start = time.time()
            out = func(*args, **kwargs)
            end = time.time()
            if is_timed:
                log.debug(
                    "Exiting %s with return value %s. Took %s seconds.",
                    func.__name__,
                    out,
                    end - start,
                )
            else:
                log.debug("Exiting %s with return value %s", func.__name__, out)
            return out

        return wrapper

    return decorator


BASE_URL = environ.get("CHATGPT_BASE_URL") or "https://ai.fakeopen.com/api/"

bcolors = t.Colors()


class Chatbot:
    """
    Chatbot class for ChatGPT
    """

    recipients: RecipientManager

    @logger(is_timed=True)
    def __init__(
        self,
        config: dict[str, str],
        conversation_id: str | None = None,
        parent_id: str | None = None,
        session_client=None,
        lazy_loading: bool = True,
        base_url: str | None = None,
    ) -> None:
        """Initialize a chatbot

        Args:
            config (dict[str, str]): Login and proxy info. Example:
                {
                    "email": "OpenAI account email",
                    "password": "OpenAI account password",
                    "access_token": "<access_token>"
                    "proxy": "<proxy_url_string>",
                    "paid": True/False, # whether this is a plus account
                }
                More details on these are available at https://github.com/acheong08/ChatGPT#configuration
            conversation_id (str | None, optional): Id of the conversation to continue on. Defaults to None.
            parent_id (str | None, optional): Id of the previous response message to continue on. Defaults to None.
            session_client (_type_, optional): _description_. Defaults to None.

        Raises:
            Exception: _description_
        """
        user_home = getenv("HOME")
        if user_home is None:
            user_home = Path().cwd()
            self.cache_path = Path(Path().cwd(), ".chatgpt_cache.json")
        else:
            # mkdir ~/.config/revChatGPT
            if not Path(user_home, ".config").exists():
                Path(user_home, ".config").mkdir()
            if not Path(user_home, ".config", "revChatGPT").exists():
                Path(user_home, ".config", "revChatGPT").mkdir()
            self.cache_path = Path(user_home, ".config", "revChatGPT", "cache.json")

        self.config = config
        self.session = session_client() if session_client else requests.Session()
        if "email" in config and "password" in config:
            try:
                cached_access_token = self.__get_cached_access_token(
                    self.config.get("email", None),
                )
            except t.Error as error:
                if error.code == 5:
                    raise
                cached_access_token = None
            if cached_access_token is not None:
                self.config["access_token"] = cached_access_token

        if "proxy" in config:
            if not isinstance(config["proxy"], str):
                error = TypeError("Proxy must be a string!")
                raise error
            proxies = {
                "http": config["proxy"],
                "https": config["proxy"],
            }
            if isinstance(self.session, AsyncClient):
                proxies = {
                    "http://": config["proxy"],
                    "https://": config["proxy"],
                }
                self.session = AsyncClient(proxies=proxies)  # type: ignore
            else:
                self.session.proxies.update(proxies)

        self.conversation_id = conversation_id
        self.parent_id = parent_id
        self.conversation_mapping = {}
        self.conversation_id_prev_queue = []
        self.parent_id_prev_queue = []
        self.lazy_loading = lazy_loading
        self.base_url = base_url or BASE_URL
        self.recipients = RecipientManager()

        self.__check_credentials()

    @logger(is_timed=True)
    def __check_credentials(self) -> None:
        """Check login info and perform login

        Any one of the following is sufficient for login. Multiple login info can be provided at the same time and they will be used in the order listed below.
            - access_token
            - email + password

        Raises:
            Exception: _description_
            AuthError: _description_
        """
        if "access_token" in self.config:
            self.set_access_token(self.config["access_token"])
        elif "email" not in self.config or "password" not in self.config:
            error = t.AuthenticationError("Insufficient login details provided!")
            raise error
        if "access_token" not in self.config:
            try:
                self.login()
            except AuthError as error:
                print(error.details)
                print(error.status_code)
                raise error

    @logger(is_timed=False)
    def set_access_token(self, access_token: str) -> None:
        """Set access token in request header and self.config, then cache it to file.

        Args:
            access_token (str): access_token
        """
        self.session.headers.clear()
        self.session.headers.update(
            {
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Openai-Assistant-App-Id": "",
                "Connection": "close",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://chat.openai.com/chat",
            },
        )
        self.session.cookies.update(
            {
                "library": "revChatGPT",
            },
        )

        self.config["access_token"] = access_token

        email = self.config.get("email", None)
        if email is not None:
            self.__cache_access_token(email, access_token)

    @logger(is_timed=False)
    def __get_cached_access_token(self, email: str | None) -> str | None:
        """Read access token from cache

        Args:
            email (str | None): email of the account to get access token

        Raises:
            Error: _description_
            Error: _description_
            Error: _description_

        Returns:
            str | None: access token string or None if not found
        """
        email = email or "default"
        cache = self.__read_cache()
        access_token = cache.get("access_tokens", {}).get(email, None)

        # Parse access_token as JWT
        if access_token is not None:
            try:
                # Split access_token into 3 parts
                s_access_token = access_token.split(".")
                # Add padding to the middle part
                s_access_token[1] += "=" * ((4 - len(s_access_token[1]) % 4) % 4)
                d_access_token = base64.b64decode(s_access_token[1])
                d_access_token = json.loads(d_access_token)
            except binascii.Error:
                error = t.Error(
                    source="__get_cached_access_token",
                    message="Invalid access token",
                    code=t.ErrorType.INVALID_ACCESS_TOKEN_ERROR,
                )
                raise error from None
            except json.JSONDecodeError:
                error = t.Error(
                    source="__get_cached_access_token",
                    message="Invalid access token",
                    code=t.ErrorType.INVALID_ACCESS_TOKEN_ERROR,
                )
                raise error from None

            exp = d_access_token.get("exp", None)
            if exp is not None and exp < time.time():
                error = t.Error(
                    source="__get_cached_access_token",
                    message="Access token expired",
                    code=t.ErrorType.EXPIRED_ACCESS_TOKEN_ERROR,
                )
                raise error

        return access_token

    @logger(is_timed=False)
    def __cache_access_token(self, email: str, access_token: str) -> None:
        """Write an access token to cache

        Args:
            email (str): account email
            access_token (str): account access token
        """
        email = email or "default"
        cache = self.__read_cache()
        if "access_tokens" not in cache:
            cache["access_tokens"] = {}
        cache["access_tokens"][email] = access_token
        self.__write_cache(cache)

    @logger(is_timed=False)
    def __write_cache(self, info: dict) -> None:
        """Write cache info to file

        Args:
            info (dict): cache info, current format
            {
                "access_tokens":{"someone@example.com": 'this account's access token', }
            }
        """
        dirname = self.cache_path.home() or Path(".")
        dirname.mkdir(parents=True, exist_ok=True)
        json.dump(info, open(self.cache_path, "w", encoding="utf-8"), indent=4)

    @logger(is_timed=False)
    def __read_cache(self):
        try:
            cached = json.load(open(self.cache_path, encoding="utf-8"))
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            cached = {}
        return cached

    @logger(is_timed=True)
    def login(self) -> None:
        """Login to OpenAI by email and password"""
        if self.config.get("email") and self.config.get("password"):
            log.error("Insufficient login details provided!")
            error = t.AuthenticationError("Insufficient login details provided!")
            raise error
        auth = Authenticator(
            email_address=self.config.get("email"),
            password=self.config.get("password"),
            proxy=self.config.get("proxy"),
        )
        log.debug("Using authenticator to get access token")
        auth.begin()
        auth.get_access_token()

        self.set_access_token(auth.access_token)

    @logger(is_timed=True)
    def __send_request(
        self,
        data: dict,
        auto_continue: bool = False,
        timeout: float = 360,
        **kwargs,
    ) -> Generator[dict, None, None]:
        log.debug("Sending the payload")

        cid, pid = data["conversation_id"], data["parent_message_id"]
        model, message = None, ""

        self.conversation_id_prev_queue.append(cid)
        self.parent_id_prev_queue.append(pid)
        response = self.session.post(
            url=f"{self.base_url}conversation",
            data=json.dumps(data),
            timeout=timeout,
            stream=True,
        )
        self.__check_response(response)

        finish_details = None
        for line in response.iter_lines():
            # remove b' and ' at the beginning and end and ignore case
            line = str(line)[2:-1]
            if line.lower() == "internal server error":
                log.error(f"Internal Server Error: {line}")
                error = t.Error(
                    source="ask",
                    message="Internal Server Error",
                    code=t.ErrorType.SERVER_ERROR,
                )
                raise error
            if not line or line is None:
                continue
            if "data: " in line:
                line = line[6:]
            if line == "[DONE]":
                break

            line = line.replace('\\"', '"')
            line = line.replace("\\'", "'")
            line = line.replace("\\\\", "\\")

            try:
                line = json.loads(line)
            except json.decoder.JSONDecodeError:
                continue
            if not self.__check_fields(line):
                raise ValueError(f"Field missing. Details: {str(line)}")
            if line.get("message").get("author").get("role") != "assistant":
                continue
            message: str = line["message"]["content"]["parts"][0]
            cid = line["conversation_id"]
            pid = line["message"]["id"]
            metadata = line["message"].get("metadata", {})
            model = metadata.get("model_slug", None)
            finish_details = metadata.get("finish_details", {"type": None})["type"]
            yield {
                "message": message,
                "conversation_id": cid,
                "parent_id": pid,
                "model": model,
                "finish_details": finish_details,
                "end_turn": line["message"].get("end_turn", True),
                "recipient": line["message"].get("recipient", "all"),
            }

        self.conversation_mapping[cid] = pid
        if pid is not None:
            self.parent_id = pid
        if cid is not None:
            self.conversation_id = cid

        if not (auto_continue and finish_details == "max_tokens"):
            return
        message = message.strip("\n")
        for i in self.continue_write(
            conversation_id=cid,
            timeout=timeout,
            auto_continue=False,
        ):
            i["message"] = message + i["message"]
            yield i

    @logger(is_timed=True)
    def post_messages(
        self,
        messages: list[dict],
        conversation_id: str | None = None,
        parent_id: str | None = None,
        model: str | None = None,
        auto_continue: bool = False,
        timeout: float = 360,
        **kwargs,
    ) -> Generator[dict, None, None]:
        """Ask a question to the chatbot
        Args:
            messages (list[dict]): The messages to send
            conversation_id (str | None, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str | None, optional): UUID for the message to continue on. Defaults to None.
            model (str | None, optional): The model to use. Defaults to None.
            auto_continue (bool, optional): Whether to continue the conversation automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.

        Yields: Generator[dict, None, None] - The response from the chatbot
            dict: {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str, # "max_tokens" or "stop"
                "end_turn": bool,
                "recipient": str,
            }
        """
        if parent_id and not conversation_id:
            raise t.Error(
                source="User",
                message="conversation_id must be set once parent_id is set",
                code=t.ErrorType.USER_ERROR,
            )

        if conversation_id and conversation_id != self.conversation_id:
            self.parent_id = None
        conversation_id = conversation_id or self.conversation_id
        parent_id = parent_id or self.parent_id or ""
        if not conversation_id and not parent_id:
            parent_id = str(uuid.uuid4())

        if conversation_id and not parent_id:
            if conversation_id not in self.conversation_mapping:
                if self.lazy_loading:
                    log.debug(
                        "Conversation ID %s not found in conversation mapping, try to get conversation history for the given ID",
                        conversation_id,
                    )
                    with contextlib.suppress(Exception):
                        history = self.get_msg_history(conversation_id)
                        self.conversation_mapping[conversation_id] = history[
                            "current_node"
                        ]
                else:
                    self.__map_conversations()
            if conversation_id in self.conversation_mapping:
                parent_id = self.conversation_mapping[conversation_id]
            else:  # invalid conversation_id provided, treat as a new conversation
                conversation_id = None
                parent_id = str(uuid.uuid4())

        data = {
            "action": "next",
            "messages": messages,
            "conversation_id": conversation_id,
            "parent_message_id": parent_id,
            "model": model
            or self.config.get("model")
            or (
                "text-davinci-002-render-paid"
                if self.config.get("paid")
                else "text-davinci-002-render-sha"
            ),
        }

        yield from self.__send_request(
            data,
            timeout=timeout,
            auto_continue=auto_continue,
        )

    @logger(is_timed=True)
    def ask(
        self,
        prompt: str,
        conversation_id: str | None = None,
        parent_id: str = "",
        model: str = "",
        auto_continue: bool = False,
        timeout: float = 360,
        **kwargs,
    ) -> Generator[dict, None, None]:
        """Ask a question to the chatbot
        Args:
            prompt (str): The question
            conversation_id (str, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str, optional): UUID for the message to continue on. Defaults to "".
            model (str, optional): The model to use. Defaults to "".
            auto_continue (bool, optional): Whether to continue the conversation automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.

        Yields: The response from the chatbot
            dict: {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str, # "max_tokens" or "stop"
                "end_turn": bool,
                "recipient": str,
            }
        """
        messages = [
            {
                "id": str(uuid.uuid4()),
                "role": "user",
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            },
        ]

        yield from self.post_messages(
            messages,
            conversation_id=conversation_id,
            parent_id=parent_id,
            model=model,
            auto_continue=auto_continue,
            timeout=timeout,
        )

    @logger(is_timed=True)
    def continue_write(
        self,
        conversation_id: str | None = None,
        parent_id: str = "",
        model: str = "",
        auto_continue: bool = False,
        timeout: float = 360,
    ) -> Generator[dict, None, None]:
        """let the chatbot continue to write.
        Args:
            conversation_id (str | None, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str, optional): UUID for the message to continue on. Defaults to None.
            model (str, optional): The model to use. Defaults to None.
            auto_continue (bool, optional): Whether to continue the conversation automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.

        Yields:
            dict: {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str, # "max_tokens" or "stop"
                "end_turn": bool,
                "recipient": str,
            }
        """
        if parent_id and not conversation_id:
            raise t.Error(
                source="User",
                message="conversation_id must be set once parent_id is set",
                code=t.ErrorType.USER_ERROR,
            )

        if conversation_id and conversation_id != self.conversation_id:
            self.parent_id = None
        conversation_id = conversation_id or self.conversation_id
        parent_id = parent_id or self.parent_id or ""
        if not conversation_id and not parent_id:
            parent_id = str(uuid.uuid4())

        if conversation_id and not parent_id:
            if conversation_id not in self.conversation_mapping:
                if self.lazy_loading:
                    log.debug(
                        "Conversation ID %s not found in conversation mapping, try to get conversation history for the given ID",
                        conversation_id,
                    )
                    with contextlib.suppress(Exception):
                        history = self.get_msg_history(conversation_id)
                        self.conversation_mapping[conversation_id] = history[
                            "current_node"
                        ]
                else:
                    log.debug(
                        f"Conversation ID {conversation_id} not found in conversation mapping, mapping conversations",
                    )
                    self.__map_conversations()
            if conversation_id in self.conversation_mapping:
                parent_id = self.conversation_mapping[conversation_id]
            else:  # invalid conversation_id provided, treat as a new conversation
                conversation_id = None
                parent_id = str(uuid.uuid4())

        data = {
            "action": "continue",
            "conversation_id": conversation_id,
            "parent_message_id": parent_id,
            "model": model
            or self.config.get("model")
            or (
                "text-davinci-002-render-paid"
                if self.config.get("paid")
                else "text-davinci-002-render-sha"
            ),
        }

        yield from self.__send_request(
            data,
            timeout=timeout,
            auto_continue=auto_continue,
        )

    @logger(is_timed=False)
    def __check_fields(self, data: dict) -> bool:
        try:
            data["message"]["content"]
        except (TypeError, KeyError):
            return False
        return True

    @logger(is_timed=False)
    def __check_response(self, response: requests.Response) -> None:
        """Make sure response is success

        Args:
            response (_type_): _description_

        Raises:
            Error: _description_
        """
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            error = t.Error(
                source="OpenAI",
                message=response.text,
                code=response.status_code,
            )
            raise error from ex

    @logger(is_timed=True)
    def get_conversations(
        self,
        offset: int = 0,
        limit: int = 20,
        encoding: str | None = None,
    ) -> list:
        """
        Get conversations
        :param offset: Integer
        :param limit: Integer
        """
        url = f"{self.base_url}conversations?offset={offset}&limit={limit}"
        response = self.session.get(url)
        self.__check_response(response)
        if encoding is not None:
            response.encoding = encoding
        data = json.loads(response.text)
        return data["items"]

    @logger(is_timed=True)
    def get_msg_history(self, convo_id: str, encoding: str | None = None) -> list:
        """
        Get message history
        :param id: UUID of conversation
        :param encoding: String
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = self.session.get(url)
        self.__check_response(response)
        if encoding is not None:
            response.encoding = encoding
        return json.loads(response.text)

    @logger(is_timed=True)
    def gen_title(self, convo_id: str, message_id: str) -> str:
        """
        Generate title for conversation
        """
        response = self.session.post(
            f"{self.base_url}conversation/gen_title/{convo_id}",
            data=json.dumps(
                {"message_id": message_id, "model": "text-davinci-002-render"},
            ),
        )
        self.__check_response(response)
        return response.json().get("title", "Error generating title")

    @logger(is_timed=True)
    def change_title(self, convo_id: str, title: str) -> None:
        """
        Change title of conversation
        :param id: UUID of conversation
        :param title: String
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = self.session.patch(url, data=json.dumps({"title": title}))
        self.__check_response(response)

    @logger(is_timed=True)
    def delete_conversation(self, convo_id: str) -> None:
        """
        Delete conversation
        :param id: UUID of conversation
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = self.session.patch(url, data='{"is_visible": false}')
        self.__check_response(response)

    @logger(is_timed=True)
    def clear_conversations(self) -> None:
        """
        Delete all conversations
        """
        url = f"{self.base_url}conversations"
        response = self.session.patch(url, data='{"is_visible": false}')
        self.__check_response(response)

    @logger(is_timed=False)
    def __map_conversations(self) -> None:
        conversations = self.get_conversations()
        histories = [self.get_msg_history(x["id"]) for x in conversations]
        for x, y in zip(conversations, histories):
            self.conversation_mapping[x["id"]] = y["current_node"]

    @logger(is_timed=False)
    def reset_chat(self) -> None:
        """
        Reset the conversation ID and parent ID.

        :return: None
        """
        self.conversation_id = None
        self.parent_id = str(uuid.uuid4())

    @logger(is_timed=False)
    def rollback_conversation(self, num: int = 1) -> None:
        """
        Rollback the conversation.
        :param num: Integer. The number of messages to rollback
        :return: None
        """
        for _ in range(num):
            self.conversation_id = self.conversation_id_prev_queue.pop()
            self.parent_id = self.parent_id_prev_queue.pop()


class AsyncChatbot(Chatbot):
    """Async Chatbot class for ChatGPT"""

    def __init__(
        self,
        config: dict,
        conversation_id: str | None = None,
        parent_id: str = "",
        base_url: str = "",
    ) -> None:
        """
        Same as Chatbot class, but with async methods.
        """
        super().__init__(
            config=config,
            conversation_id=conversation_id,
            parent_id=parent_id,
            session_client=AsyncClient,
            base_url=base_url,
        )

    async def __send_request(
        self,
        data: dict,
        auto_continue: bool = False,
        timeout: float = 360,
    ) -> AsyncGenerator[dict, None]:
        cid, pid = data["conversation_id"], data["parent_message_id"]

        self.conversation_id_prev_queue.append(cid)
        self.parent_id_prev_queue.append(pid)
        message = ""

        finish_details = None
        response = None
        async with self.session.stream(
            method="POST",
            url=f"{self.base_url}conversation",
            data=json.dumps(data),
            timeout=timeout,
        ) as response:
            await self.__check_response(response)
            async for line in response.aiter_lines():
                if not line or line is None:
                    continue
                if "data: " in line:
                    line = line[6:]
                if "[DONE]" in line:
                    break

                try:
                    line = json.loads(line)
                except json.decoder.JSONDecodeError:
                    continue
                if not self.__check_fields(line):
                    raise ValueError(f"Field missing. Details: {str(line)}")

                message: str = line["message"]["content"]["parts"][0]
                cid = line["conversation_id"]
                pid = line["message"]["id"]
                metadata = line["message"].get("metadata", {})
                model = metadata.get("model_slug", None)
                finish_details = metadata.get("finish_details", {"type": None})["type"]
                yield {
                    "message": message,
                    "conversation_id": cid,
                    "parent_id": pid,
                    "model": model,
                    "finish_details": finish_details,
                    "end_turn": line["message"].get("end_turn", True),
                    "recipient": line["message"].get("recipient", "all"),
                }

            self.conversation_mapping[cid] = pid
            if pid:
                self.parent_id = pid
            if cid:
                self.conversation_id = cid

        if not (auto_continue and finish_details == "max_tokens"):
            return
        async for msg in self.continue_write(
            conversation_id=cid,
            auto_continue=False,
            timeout=timeout,
        ):
            msg["message"] = message + msg["message"]
            yield msg

    async def post_messages(
        self,
        messages: list[dict],
        conversation_id: str | None = None,
        parent_id: str = "",
        model: str = "",
        auto_continue: bool = False,
        timeout: int = 360,
    ) -> AsyncGenerator[dict, None]:
        """Post messages to the chatbot

        Args:
            messages (list[dict]): the messages to post
            conversation_id (str | None, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str, optional): UUID for the message to continue on. Defaults to "".
            model (str, optional): The model to use. Defaults to "".
            auto_continue (bool, optional): Whether to continue the conversation automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.

        Yields:
            AsyncGenerator[dict, None]: The response from the chatbot
            {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str,
                "end_turn": bool,
                "recipient": str,
            }
        """
        if parent_id and not conversation_id:
            error = t.Error(
                source="User",
                message="conversation_id must be set once parent_id is set",
                code=t.ErrorType.SERVER_ERROR,
            )
            raise error
        if conversation_id and conversation_id != self.conversation_id:
            self.parent_id = None
        conversation_id = conversation_id or self.conversation_id

        parent_id = parent_id or self.parent_id or ""
        if not conversation_id and not parent_id:
            parent_id = str(uuid.uuid4())
        if conversation_id and not parent_id:
            if conversation_id not in self.conversation_mapping:
                await self.__map_conversations()
            if conversation_id in self.conversation_mapping:
                parent_id = self.conversation_mapping[conversation_id]
            else:  # invalid conversation_id provided, treat as a new conversation
                conversation_id = None
                parent_id = str(uuid.uuid4())

        data = {
            "action": "next",
            "messages": messages,
            "conversation_id": conversation_id,
            "parent_message_id": parent_id,
            "model": model
            or self.config.get("model")
            or (
                "text-davinci-002-render-paid"
                if self.config.get("paid")
                else "text-davinci-002-render-sha"
            ),
        }

        async for msg in self.__send_request(
            data=data,
            auto_continue=auto_continue,
            timeout=timeout,
        ):
            yield msg

    async def ask(
        self,
        prompt: str,
        conversation_id: str | None = None,
        parent_id: str = "",
        model: str = "",
        auto_continue: bool = False,
        timeout: int = 360,
    ) -> AsyncGenerator[dict, None]:
        """Ask a question to the chatbot

        Args:
            prompt (str): The question to ask
            conversation_id (str | None, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str, optional): UUID for the message to continue on. Defaults to "".
            model (str, optional): The model to use. Defaults to "".
            auto_continue (bool, optional): Whether to continue the conversation automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.

        Yields:
            AsyncGenerator[dict, None]: The response from the chatbot
            {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str,
                "end_turn": bool,
                "recipient": str,
            }
        """

        messages = [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            },
        ]

        async for msg in self.post_messages(
            messages=messages,
            conversation_id=conversation_id,
            parent_id=parent_id,
            model=model,
            auto_continue=auto_continue,
            timeout=timeout,
        ):
            yield msg

    async def continue_write(
        self,
        conversation_id: str | None = None,
        parent_id: str = "",
        model: str = "",
        auto_continue: bool = False,
        timeout: float = 360,
    ) -> AsyncGenerator[dict, None]:
        """let the chatbot continue to write
        Args:
            conversation_id (str | None, optional): UUID for the conversation to continue on. Defaults to None.
            parent_id (str, optional): UUID for the message to continue on. Defaults to None.
            model (str, optional): Model to use. Defaults to None.
            auto_continue (bool, optional): Whether to continue writing automatically. Defaults to False.
            timeout (float, optional): Timeout for getting the full response, unit is second. Defaults to 360.


        Yields:
            AsyncGenerator[dict, None]: The response from the chatbot
            {
                "message": str,
                "conversation_id": str,
                "parent_id": str,
                "model": str,
                "finish_details": str,
                "end_turn": bool,
                "recipient": str,
            }
        """
        if parent_id and not conversation_id:
            error = t.Error(
                source="User",
                message="conversation_id must be set once parent_id is set",
                code=t.ErrorType.SERVER_ERROR,
            )
            raise error
        if conversation_id and conversation_id != self.conversation_id:
            self.parent_id = None
        conversation_id = conversation_id or self.conversation_id

        parent_id = parent_id or self.parent_id or ""
        if not conversation_id and not parent_id:
            parent_id = str(uuid.uuid4())
        if conversation_id and not parent_id:
            if conversation_id not in self.conversation_mapping:
                await self.__map_conversations()
            if conversation_id in self.conversation_mapping:
                parent_id = self.conversation_mapping[conversation_id]
            else:  # invalid conversation_id provided, treat as a new conversation
                conversation_id = None
                parent_id = str(uuid.uuid4())

        data = {
            "action": "continue",
            "conversation_id": conversation_id,
            "parent_message_id": parent_id,
            "model": model
            or self.config.get("model")
            or (
                "text-davinci-002-render-paid"
                if self.config.get("paid")
                else "text-davinci-002-render-sha"
            ),
        }

        async for msg in self.__send_request(
            data=data,
            auto_continue=auto_continue,
            timeout=timeout,
        ):
            yield msg

    async def get_conversations(self, offset: int = 0, limit: int = 20) -> list:
        """
        Get conversations
        :param offset: Integer
        :param limit: Integer
        """
        url = f"{self.base_url}conversations?offset={offset}&limit={limit}"
        response = await self.session.get(url)
        await self.__check_response(response)
        data = json.loads(response.text)
        return data["items"]

    async def get_msg_history(
        self,
        convo_id: str,
        encoding: str | None = "utf-8",
    ) -> dict:
        """
        Get message history
        :param id: UUID of conversation
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = await self.session.get(url)
        if encoding is not None:
            response.encoding = encoding
            await self.__check_response(response)
            return json.loads(response.text)
        return None

    async def gen_title(self, convo_id: str, message_id: str) -> None:
        """
        Generate title for conversation
        """
        url = f"{self.base_url}conversation/gen_title/{convo_id}"
        response = await self.session.post(
            url,
            data=json.dumps(
                {"message_id": message_id, "model": "text-davinci-002-render"},
            ),
        )
        await self.__check_response(response)

    async def change_title(self, convo_id: str, title: str) -> None:
        """
        Change title of conversation
        :param convo_id: UUID of conversation
        :param title: String
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = await self.session.patch(url, data=f'{{"title": "{title}"}}')
        await self.__check_response(response)

    async def delete_conversation(self, convo_id: str) -> None:
        """
        Delete conversation
        :param convo_id: UUID of conversation
        """
        url = f"{self.base_url}conversation/{convo_id}"
        response = await self.session.patch(url, data='{"is_visible": false}')
        await self.__check_response(response)

    async def clear_conversations(self) -> None:
        """
        Delete all conversations
        """
        url = f"{self.base_url}conversations"
        response = await self.session.patch(url, data='{"is_visible": false}')
        await self.__check_response(response)

    async def __map_conversations(self) -> None:
        conversations = await self.get_conversations()
        histories = [await self.get_msg_history(x["id"]) for x in conversations]
        for x, y in zip(conversations, histories):
            self.conversation_mapping[x["id"]] = y["current_node"]

    def __check_fields(self, data: dict) -> bool:
        try:
            data["message"]["content"]
        except (TypeError, KeyError):
            return False
        return True

    async def __check_response(self, response: httpx.Response) -> None:
        # 改成自带的错误处理
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as ex:
            await response.aread()
            error = t.Error(
                source="OpenAI",
                message=response.text,
                code=response.status_code,
            )
            raise error from ex


get_input = logger(is_timed=False)(get_input)


@logger(is_timed=False)
def configure() -> dict:
    """
    Looks for a config file in the following locations:
    """
    config_files: list[Path] = [Path("config.json")]
    if xdg_config_home := getenv("XDG_CONFIG_HOME"):
        config_files.append(Path(xdg_config_home, "revChatGPT/config.json"))
    if user_home := getenv("HOME"):
        config_files.append(Path(user_home, ".config/revChatGPT/config.json"))
    if windows_home := getenv("HOMEPATH"):
        config_files.append(Path(f"{windows_home}/.config/revChatGPT/config.json"))

    if config_file := next((f for f in config_files if f.exists()), None):
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
    else:
        print("No config file found.")
        raise FileNotFoundError("No config file found.")
    return config


@logger(is_timed=False)
def main(config: dict) -> NoReturn:
    """
    Main function for the chatGPT program.
    """
    chatbot = Chatbot(
        config,
        conversation_id=config.get("conversation_id"),
        parent_id=config.get("parent_id"),
    )
    plugins: dict[str, Recipient] = {}
    chatbot.recipients["python"] = PythonRecipient

    def handle_commands(command: str) -> bool:
        if command == "!help":
            print(
                """
            !help - Show this message
            !reset - Forget the current conversation
            !config - Show the current configuration
            !plugins - Show the current plugins
            !switch x - Switch to plugin x. Need to reset the conversation to ativate the plugin.
            !rollback x - Rollback the conversation (x being the number of messages to rollback)
            !setconversation - Changes the conversation
            !exit - Exit this program
            """,
            )
        elif command == "!reset":
            chatbot.reset_chat()
            print("Chat session successfully reset.")
        elif command == "!config":
            print(json.dumps(chatbot.config, indent=4))
        elif command.startswith("!rollback"):
            try:
                rollback = int(command.split(" ")[1])
            except IndexError:
                logging.exception(
                    "No number specified, rolling back 1 message",
                    stack_info=True,
                )
                rollback = 1
            chatbot.rollback_conversation(rollback)
            print(f"Rolled back {rollback} messages.")
        elif command.startswith("!setconversation"):
            try:
                chatbot.conversation_id = chatbot.config[
                    "conversation_id"
                ] = command.split(" ")[1]
                print("Conversation has been changed")
            except IndexError:
                log.exception(
                    "Please include conversation UUID in command",
                    stack_info=True,
                )
                print("Please include conversation UUID in command")
        elif command.startswith("!continue"):
            print()
            print(f"{bcolors.OKGREEN + bcolors.BOLD}Chatbot: {bcolors.ENDC}")
            prev_text = ""
            for data in chatbot.continue_write():
                message = data["message"][len(prev_text) :]
                print(message, end="", flush=True)
                prev_text = data["message"]
            print(bcolors.ENDC)
            print()
        elif command == "!plugins":
            print("Plugins:")
            for plugin, docs in chatbot.recipients.available_recipients.items():
                print(" [x] " if plugin in plugins else " [ ] ", plugin, ": ", docs)
            print()
        elif command.startswith("!switch"):
            try:
                plugin = command.split(" ")[1]
                if plugin in plugins:
                    del plugins[plugin]
                else:
                    plugins[plugin] = chatbot.recipients[plugin]()
                print(
                    f"Plugin {plugin} has been "
                    + ("enabled" if plugin in plugins else "disabled"),
                )
                print()
            except IndexError:
                log.exception("Please include plugin name in command")
                print("Please include plugin name in command")
        elif command == "!exit":
            if isinstance(chatbot.session, httpx.AsyncClient):
                chatbot.session.aclose()
            exit()
        else:
            return False
        return True

    session = create_session()
    completer = create_completer(
        [
            "!help",
            "!reset",
            "!config",
            "!rollback",
            "!exit",
            "!setconversation",
            "!continue",
            "!plugins",
            "!switch",
        ],
    )
    print()
    try:
        msg = {}
        result = {}
        times = 0
        while True:
            if not msg:
                times = 0
                print(f"{bcolors.OKBLUE + bcolors.BOLD}You: {bcolors.ENDC}")

                prompt = get_input(session=session, completer=completer)
                if prompt.startswith("!") and handle_commands(prompt):
                    continue
                if not chatbot.conversation_id and plugins:
                    prompt = (
                        (
                            f"""You are ChatGPT.

Knowledge cutoff: 2021-09
Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}

###Available Tools:
"""
                            + ";".join(plugins)
                            + "\n\n"
                            + "\n\n".join([i.API_DOCS for i in plugins.values()])
                        )
                        + "\n\n\n\n"
                        + prompt
                    )
                msg = {
                    "id": str(uuid.uuid4()),
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [prompt]},
                }
            else:
                print(
                    f"{bcolors.OKCYAN + bcolors.BOLD}{result['recipient'] if result['recipient'] != 'user' else 'You'}: {bcolors.ENDC}",
                )
                print(msg["content"]["parts"][0])

            print()
            print(f"{bcolors.OKGREEN + bcolors.BOLD}Chatbot: {bcolors.ENDC}")
            prev_text = ""
            for data in chatbot.post_messages([msg], auto_continue=True):
                result = data
                message = data["message"][len(prev_text) :]
                print(message, end="", flush=True)
                prev_text = data["message"]
            print(bcolors.ENDC)
            print()

            msg = {}
            if not result.get("end_turn", True):
                times += 1
                if times >= 5:
                    continue
                api = plugins.get(result["recipient"])
                if not api:
                    msg = {
                        "id": str(uuid.uuid4()),
                        "author": {"role": "user"},
                        "content": {
                            "content_type": "text",
                            "parts": [f"Error: No plugin {result['recipient']} found"],
                        },
                    }
                    continue
                msg = api.process(result)

    except (KeyboardInterrupt, EOFError):
        exit()
    except Exception as exc:
        error = t.CLIError("command line program unknown error")
        raise error from exc


if __name__ == "__main__":
    print(
        f"""
        ChatGPT - A command-line interface to OpenAI's ChatGPT (https://chat.openai.com/chat)
        Repo: github.com/acheong08/ChatGPT
        Version: {__version__}
        """,
    )
    print("Type '!help' to show a full list of commands")
    print(
        f"{bcolors.BOLD}{bcolors.WARNING}Press Esc followed by Enter or Alt+Enter to send a message.{bcolors.ENDC}",
    )
    main(configure())
