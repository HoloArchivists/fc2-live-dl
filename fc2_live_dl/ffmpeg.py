import asyncio
import signal
from .util import Logger


class FFMpeg:
    FFMPEG_BIN = "ffmpeg"

    def __init__(self, flags):
        self._logger = Logger("ffmpeg")
        self._ffmpeg = None
        self._flags = flags

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._ffmpeg = await asyncio.create_subprocess_exec(
            self.FFMPEG_BIN,
            *self._flags,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        return self

    async def __aexit__(self, *err):
        self._logger.trace("exit", err)
        ret = self._ffmpeg.returncode
        if ret is None:
            try:
                if hasattr(signal, "CTRL_C_EVENT"):
                    # windows
                    self._ffmpeg.send_signal(
                        signal.CTRL_C_EVENT
                    )  # pylint: disable=no-member
                else:
                    # unix
                    self._ffmpeg.send_signal(signal.SIGINT)  # pylint: disable=no-member
            except Exception as ex:
                self._logger.error("unable to stop ffmpeg:", repr(ex), str(ex))
        ret = await self._ffmpeg.wait()
        self._logger.debug("exited with code", ret)

    async def print_status(self):
        try:
            status = await self.get_status()
            self._logger.info(
                "[q] to stop", status["time"], status["size"], inline=True
            )
            return True
        except:
            return False

    async def get_status(self):
        stderr = (await self._ffmpeg.stderr.readuntil(b"\r")).decode("utf-8")
        self._logger.trace(stderr)
        stats = {
            "frame": 0,
            "fps": 0,
            "q": 0,
            "size": "0kB",
            "time": "00:00:00.00",
            "bitrate": "N/A",
            "speed": "N/A",
        }
        last_item = "-"
        parts = [x for x in stderr.split(" ") if len(x) > 0]
        for item in parts:
            if last_item[-1] == "=":
                stats[last_item[:-1]] = item
            elif "=" in item:
                k, v = item.split("=")
                stats[k] = v
            last_item = item
        return stats
