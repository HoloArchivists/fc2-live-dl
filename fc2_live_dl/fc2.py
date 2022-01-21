import asyncio
import base64
import json
import time
import html
from .util import Logger, AsyncMap


class FC2WebSocket:
    heartbeat_interval = 30

    def __init__(self, session, url, *, output_file=None):
        self._session = session
        self._url = url
        self._msg_id = 0
        self._msg_responses = AsyncMap()
        self._last_heartbeat = 0
        self._is_ready = False
        self._logger = Logger("ws")
        self.comments = asyncio.Queue()

        self._output_file = None
        if output_file is not None:
            self._logger.info("Writing websocket to", output_file)
            self._output_file = open(output_file, "w")

    def __del__(self):
        if self._output_file is not None:
            self._logger.debug("Closing file")
            self._output_file.close()

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._ws = await self._session.ws_connect(self._url)
        self._logger.trace(self._ws)
        self._logger.debug("connected")
        self._task = asyncio.create_task(self._main_loop(), name="main_loop")
        return self

    async def __aexit__(self, *err):
        self._logger.trace("exit", err)
        if not self._task.done():
            self._task.cancel()
        await self._ws.close()
        self._logger.debug("closed")

    async def wait_disconnection(self):
        res = await self._task
        if res.exception() is not None:
            raise res.exception()

    async def get_hls_information(self):
        msg = None
        tries = 0
        max_tries = 5

        while msg is None and tries < max_tries:
            msg = await self._send_message_and_wait("get_hls_information", timeout=5)

            backoff_delay = 2 ** tries
            tries += 1

            if msg is None:
                self._logger.warn(
                    "Timeout reached waiting for HLS information, retrying in",
                    backoff_delay,
                    "seconds",
                )
                await asyncio.sleep(backoff_delay)
            elif "playlists" not in msg["arguments"]:
                msg = None
                self._logger.warn(
                    "Received empty playlist, retrying in", backoff_delay, "seconds"
                )
                await asyncio.sleep(backoff_delay)

        if tries == max_tries:
            self._logger.error("Gave up after", tries, "tries")
            raise self.EmptyPlaylistException()

        return msg["arguments"]

    async def _main_loop(self):
        while True:
            msg = await asyncio.wait_for(
                self._ws.receive_json(), self.heartbeat_interval
            )
            self._logger.trace("<", json.dumps(msg)[:100])
            if self._output_file is not None:
                self._output_file.write("< ")
                self._output_file.write(json.dumps(msg))
                self._output_file.write("\n")

            if msg["name"] == "connect_complete":
                self._is_ready = True
            elif msg["name"] == "_response_":
                await self._msg_responses.put(msg["id"], msg)
            elif msg["name"] == "control_disconnection":
                code = msg["arguments"]["code"]
                if code == 4101:
                    raise self.PaidProgramDisconnection()
                elif code == 4507:
                    raise self.LoginRequiredError()
                elif code == 4512:
                    raise self.MultipleConnectionError()
                else:
                    raise self.ServerDisconnection(code)
            elif msg["name"] == "publish_stop":
                raise self.StreamEnded()
            elif msg["name"] == "comment":
                for comment in msg["arguments"]["comments"]:
                    await self.comments.put(comment)

            await self._try_heartbeat()

    async def _try_heartbeat(self):
        if time.time() - self._last_heartbeat < self.heartbeat_interval:
            return
        self._logger.debug("heartbeat")
        await self._send_message("heartbeat")
        self._last_heartbeat = time.time()

    async def _send_message_and_wait(self, name, arguments={}, *, timeout=0):
        msg_id = await self._send_message(name, arguments)
        if msg_id is None:
            return None

        msg_wait_task = asyncio.create_task(self._msg_responses.pop(msg_id))
        tasks = [msg_wait_task, self._task]

        if timeout > 0:
            tasks.append(asyncio.create_task(asyncio.sleep(timeout), name="timeout"))

        _done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        done = _done.pop()
        if done.get_name() == "main_loop":
            _pending.pop().cancel()
            raise done.exception()
        elif done.get_name() == "timeout":
            return None
        return done.result()

    async def _send_message(self, name, arguments={}):
        self._msg_id += 1
        msg = {"name": name, "arguments": arguments, "id": self._msg_id}

        self._logger.trace(">", name, arguments)
        if self._output_file is not None:
            self._output_file.write("> ")
            self._output_file.write(json.dumps(msg))
            self._output_file.write("\n")

        try:
            await self._ws.send_json(msg)
        except asyncio.TimeoutError as e:
            self._logger.debug("_send_message: send_json timeout", e)
            return None
        return self._msg_id

    class ServerDisconnection(Exception):
        """Raised when the server sends a `control_disconnection` message"""

        def __init__(self, code=None, reason=None):
            self.code = code
            self.reason = reason

        def __str__(self):
            if self.reason is not None:
                return "Server disconnected: {} ({})".format(self.code, self.reason)
            return "Server disconnected: {}".format(self.code)

    class PaidProgramDisconnection(ServerDisconnection):
        """Raised when the streamer switches the broadcast to a paid program"""

        def __init__(self):
            super().__init__(code=4101, reason="Paid program")

    class LoginRequiredError(ServerDisconnection):
        """Raised when the stream requires a login"""

        def __init__(self):
            super().__init__(code=4507, reason="Login required")

    class MultipleConnectionError(ServerDisconnection):
        """Raised when the server detects multiple connections to the same live stream"""

        def __init__(self):
            super().__init__(code=4512, reason="Multiple connections")

    class StreamEnded(Exception):
        def __str__(self):
            return "Stream has ended"

    class EmptyPlaylistException(Exception):
        """Raised when the server did not return a valid playlist"""

        def __str__(self):
            return "Server did not return a valid playlist"


class FC2LiveStream:
    def __init__(self, session, channel_id):
        self._meta = None
        self._session = session
        self._logger = Logger("live")
        self.channel_id = channel_id

    async def wait_for_online(self, interval):
        while not await self.is_online():
            for _ in range(interval):
                self._logger.info("Waiting for stream", inline=True, spin=True)
                await asyncio.sleep(1)

    async def is_online(self, *, refetch=True):
        meta = await self.get_meta(refetch=refetch)
        return meta["channel_data"]["is_publish"] > 0

    async def get_websocket_url(self):
        meta = await self.get_meta()
        if not await self.is_online(refetch=False):
            raise self.NotOnlineException()

        orz = ""
        cookie_orz = self._get_cookie("l_ortkn")
        if cookie_orz is not None:
            orz = cookie_orz.value

        url = "https://live.fc2.com/api/getControlServer.php"
        data = {
            "channel_id": self.channel_id,
            "mode": "play",
            "orz": orz,
            "channel_version": meta["channel_data"]["version"],
            "client_version": "2.1.0\n+[1]",
            "client_type": "pc",
            "client_app": "browser_hls",
            "ipv6": "",
        }
        self._logger.trace("get_websocket_url>", url, data)
        async with self._session.post(url, data=data) as resp:
            self._logger.trace(resp.request_info)
            info = await resp.json()
            self._logger.trace("<get_websocket_url", info)

            jwt_body = info["control_token"].split(".")[1]
            control_token = json.loads(
                base64.b64decode(jwt_body + "==").decode("utf-8")
            )
            fc2id = control_token["fc2_id"]
            if len(fc2id) > 0:
                self._logger.debug("Logged in with ID", fc2id)
            else:
                self._logger.debug("Using anonymous account")

            return "%(url)s?control_token=%(control_token)s" % info

    async def get_meta(self, *, refetch=False):
        if self._meta is not None and not refetch:
            return self._meta

        url = "https://live.fc2.com/api/memberApi.php"
        data = {
            "channel": 1,
            "profile": 1,
            "user": 1,
            "streamid": self.channel_id,
        }
        self._logger.trace("get_meta>", url, data)
        async with self._session.post(url, data=data) as resp:
            # FC2 returns text/javascript instead of application/json
            # Content type is specified so aiohttp knows what to expect
            data = await resp.json(content_type="text/javascript")
            self._logger.trace("<get_meta", data)

            # FC2 html-encodes data.channel_data.title
            data["data"]["channel_data"]["title"] = html.unescape(
                data["data"]["channel_data"]["title"]
            )

            self._meta = data["data"]
            return data["data"]

    def _get_cookie(self, key):
        jar = self._session.cookie_jar
        for cookie in jar:
            if cookie.key == key:
                return cookie

    class NotOnlineException(Exception):
        """Raised when the channel is not currently broadcasting"""

        def __str__(self):
            return "Live stream is currently not online"
