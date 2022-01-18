import asyncio
import time
from .util import Logger
from .fc2 import FC2WebSocket


class HLSDownloader:
    def __init__(self, session, url, threads):
        self._session = session
        self._url = url
        self._threads = threads
        self._logger = Logger("hls")
        self._frag_urls = asyncio.PriorityQueue(100)
        self._frag_data = asyncio.PriorityQueue(100)
        self._download_task = None

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._logger.debug("init")
        return self

    async def __aexit__(self, *err):
        self._logger.trace("exit", err)
        if self._download_task is not None:
            self._download_task.cancel()
            await self._download_task

    async def _get_fragment_urls(self):
        async with self._session.get(self._url) as resp:
            if resp.status == 403:
                raise FC2WebSocket.StreamEnded()
            elif resp.status == 404:
                return []
            playlist = await resp.text()
            return [
                line.strip()
                for line in playlist.split("\n")
                if len(line) > 0 and not line[0] == "#"
            ]

    async def _fill_queue(self):
        last_fragment_timestamp = time.time()
        last_fragment = None
        frag_idx = 0
        while True:
            try:
                frags = await self._get_fragment_urls()

                new_idx = 0
                try:
                    new_idx = 1 + frags.index(last_fragment)
                except:
                    pass

                n_new = len(frags) - new_idx
                if n_new > 0:
                    last_fragment_timestamp = time.time()
                    self._logger.debug("Found", n_new, "new fragments")

                for frag in frags[new_idx:]:
                    last_fragment = frag
                    await self._frag_urls.put((frag_idx, (frag, 0)))
                    frag_idx += 1

                if time.time() - last_fragment_timestamp > 30:
                    self._logger.debug("Timeout receiving new segments")
                    return

                await asyncio.sleep(1)
            except Exception as ex:
                self._logger.error("Error fetching new segments:", ex)
                return

    async def _download_worker(self, wid):
        try:
            while True:
                i, (url, tries) = await self._frag_urls.get()
                self._logger.debug(wid, "Downloading fragment", i)
                try:
                    async with self._session.get(url) as resp:
                        if resp.status > 299:
                            self._logger.error(
                                wid, "Fragment", i, "errored:", resp.status
                            )
                            if tries < 5:
                                self._logger.debug(wid, "Retrying fragment", i)
                                await self._frag_urls.put((i, (url, tries + 1)))
                            else:
                                self._logger.error(
                                    wid,
                                    "Gave up on fragment",
                                    i,
                                    "after",
                                    tries,
                                    "tries",
                                )
                                await self._frag_data.put((i, b""))
                        else:
                            await self._frag_data.put((i, await resp.read()))
                except Exception as ex:
                    self._logger.error(wid, "Unhandled exception:", ex)
        except asyncio.CancelledError:
            self._logger.debug("worker", wid, "cancelled")

    async def _download(self):
        tasks = []
        try:
            if self._threads > 1:
                self._logger.info("Downloading with", self._threads, "threads")

            if self._threads > 8:
                self._logger.warn("Using more than 8 threads is not recommended")

            tasks = [
                asyncio.create_task(self._download_worker(i))
                for i in range(self._threads)
            ]

            self._logger.debug("Starting queue worker")
            await self._fill_queue()
            self._logger.debug("Queue finished")

            for task in tasks:
                task.cancel()
                await task
            self._logger.debug("Workers quit")
        except asyncio.CancelledError:
            self._logger.debug("_download cancelled")
            for task in tasks:
                task.cancel()
                await task

    async def _read(self, index):
        while True:
            p, frag = await self._frag_data.get()
            if p == index:
                return frag
            await self._frag_data.put((p, frag))
            await asyncio.sleep(0.1)

    async def read(self):
        try:
            if self._download_task is None:
                self._download_task = asyncio.create_task(self._download())

            index = 0
            while True:
                yield await self._read(index)
                index += 1
        except asyncio.CancelledError:
            self._logger.debug("read cancelled")
            if self._download_task is not None:
                self._download_task.cancel()
                await self._download_task
