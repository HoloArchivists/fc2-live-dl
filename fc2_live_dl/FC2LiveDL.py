#!/usr/bin/env python3

from datetime import datetime
import http.cookies
import asyncio
import aiohttp
import pathlib
import json
import time
import os

from .util import Logger, sanitize_filename
from .ffmpeg import FFMpeg
from .fc2 import FC2LiveStream, FC2WebSocket
from .hls import HLSDownloader


class FC2LiveDL:
    # Constants
    STREAM_QUALITY = {
        "150Kbps": 10,
        "400Kbps": 20,
        "1.2Mbps": 30,
        "2Mbps": 40,
        "3Mbps": 50,
        "sound": 90,
    }
    STREAM_LATENCY = {
        "low": 0,
        "high": 1,
        "mid": 2,
    }
    DEFAULT_PARAMS = {
        "quality": "3Mbps",
        "latency": "mid",
        "threads": 1,
        "outtmpl": "%(date)s %(title)s (%(channel_name)s).%(ext)s",
        "write_chat": False,
        "write_info_json": False,
        "write_thumbnail": False,
        "wait_for_live": False,
        "wait_for_quality_timeout": 15,
        "wait_poll_interval": 5,
        "cookies_file": None,
        "remux": True,
        "keep_intermediates": False,
        "extract_audio": False,
        "trust_env_proxy": False,
        # Debug params
        "dump_websocket": False,
    }

    def __init__(self, params={}):
        self._logger = Logger("fc2")
        self._session = None
        self._background_tasks = []

        self.params = json.loads(json.dumps(self.DEFAULT_PARAMS))
        self.params.update(params)
        # Validate outtmpl
        self._format_outtmpl()

        # Parse cookies
        self._cookie_jar = aiohttp.CookieJar()
        cookies_file = self.params["cookies_file"]
        if cookies_file is not None:
            self._logger.info("Loading cookies from", cookies_file)
            cookies = self._parse_cookies_file(cookies_file)
            self._cookie_jar.update_cookies(cookies)

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            cookie_jar=self._cookie_jar,
            trust_env=self.params["trust_env_proxy"],
        )
        self._loop = asyncio.get_running_loop()
        return self

    async def __aexit__(self, *err):
        self._logger.trace("exit", err)
        await self._session.close()
        self._session = None

    async def download(self, channel_id):
        self._logger = Logger("fc2 " + channel_id)
        tasks = []
        fname_stream = None
        try:
            live = FC2LiveStream(self._session, channel_id)

            self._logger.info("Fetching stream info")

            is_online = await live.is_online()
            if not is_online:
                if not self.params["wait_for_live"]:
                    raise FC2LiveStream.NotOnlineException()
                await live.wait_for_online(self.params["wait_poll_interval"])

            meta = await live.get_meta(refetch=False)

            fname_info = self._prepare_file(meta, "info.json")
            fname_thumb = self._prepare_file(meta, "png")
            fname_stream = self._prepare_file(meta, "ts")
            fname_chat = self._prepare_file(meta, "fc2chat.json")
            fname_muxed = self._prepare_file(
                meta, "m4a" if self.params["quality"] == "sound" else "mp4"
            )
            fname_audio = self._prepare_file(meta, "m4a")
            fname_websocket = (
                self._prepare_file(meta, "ws")
                if self.params["dump_websocket"]
                else None
            )

            if self.params["write_info_json"]:
                self._logger.info("Writing info json to", fname_info)
                with open(fname_info, "w") as f:
                    f.write(json.dumps(meta))

            if self.params["write_thumbnail"]:
                self._logger.info("Writing thumbnail to", fname_thumb)
                thumb_url = meta["channel_data"]["image"]
                async with self._session.get(thumb_url) as resp:
                    with open(fname_thumb, "wb") as f:
                        async for data in resp.content.iter_chunked(1024):
                            f.write(data)

            ws_url = await live.get_websocket_url()
            self._logger.info("Found websocket url")
            async with FC2WebSocket(
                self._session, ws_url, output_file=fname_websocket
            ) as ws:
                started = time.time()
                mode = self._get_mode()
                got_mode = None
                hls_url = None

                # Wait for the selected quality to be available
                while (
                    time.time() - started < self.params["wait_for_quality_timeout"]
                    and got_mode != mode
                ):
                    hls_info = await ws.get_hls_information()
                    hls_url, got_mode = self._get_hls_url(hls_info, mode)

                    # Log a warning if the requested mode is not available
                    if got_mode != mode:
                        self._logger.warn(
                            "Requested quality",
                            self._format_mode(mode),
                            "is not available, waiting ({}/{}s)".format(
                                round(time.time() - started),
                                self.params["wait_for_quality_timeout"],
                            ),
                        )
                        await asyncio.sleep(1)

                if got_mode != mode:
                    self._logger.warn(
                        "Timeout reached, falling back to next best quality",
                        self._format_mode(got_mode),
                    )

                self._logger.info("Received HLS info")

                coros = []

                coros.append(ws.wait_disconnection())

                self._logger.info("Writing stream to", fname_stream)
                coros.append(self._download_stream(hls_url, fname_stream))

                if self.params["write_chat"]:
                    self._logger.info("Writing chat to", fname_chat)
                    coros.append(self._download_chat(ws, fname_chat))

                tasks = [asyncio.create_task(coro) for coro in coros]

                self._logger.debug("Starting", len(tasks), "tasks")
                _exited, _pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                self._logger.debug("Tasks exited")

                while len(_pending) > 0:
                    pending_task = _pending.pop()
                    self._logger.debug("Cancelling pending task", pending_task)
                    pending_task.cancel()

                exited = _exited.pop()
                self._logger.debug("Exited task was", exited)
                if exited.exception() is not None:
                    raise exited.exception()
        except asyncio.CancelledError:
            self._logger.error("Interrupted by user")
        except FC2WebSocket.ServerDisconnection as ex:
            self._logger.error(ex)
        except FC2WebSocket.StreamEnded:
            self._logger.info("Stream ended")
        finally:
            self._logger.debug("Cancelling tasks")
            for task in tasks:
                if not task.done():
                    self._logger.debug("Cancelling", task)
                    task.cancel()
                    await task

        if (
            fname_stream is not None
            and self.params["remux"]
            and os.path.isfile(fname_stream)
        ):
            self._logger.info("Remuxing stream to", fname_muxed)
            await self._remux_stream(fname_stream, fname_muxed)
            self._logger.debug("Finished remuxing stream", fname_muxed)

            if self.params["extract_audio"]:
                self._logger.info("Extracting audio to", fname_audio)
                await self._remux_stream(fname_stream, fname_audio, extra_flags=["-vn"])
                self._logger.debug("Finished remuxing stream", fname_muxed)

            if not self.params["keep_intermediates"] and os.path.isfile(fname_muxed):
                self._logger.info("Removing intermediate files")
                os.remove(fname_stream)
            else:
                self._logger.debug("Not removing intermediates")
        else:
            self._logger.debug("Not remuxing stream")

        self._logger.info("Done")

    async def _download_stream(self, hls_url, fname):
        def sizeof_fmt(num, suffix="B"):
            for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
                if abs(num) < 1024.0:
                    return f"{num:3.1f}{unit}{suffix}"
                num /= 1024.0
            return f"{num:.1f}Yi{suffix}"

        try:
            async with HLSDownloader(
                self._session, hls_url, self.params["threads"]
            ) as hls:
                with open(fname, "wb") as out:
                    n_frags = 0
                    total_size = 0
                    async for frag in hls.read():
                        n_frags += 1
                        total_size += len(frag)
                        out.write(frag)
                        self._logger.info(
                            "Downloaded",
                            n_frags,
                            "fragments,",
                            sizeof_fmt(total_size),
                            inline=True,
                        )
        except asyncio.CancelledError:
            self._logger.debug("_download_stream cancelled")
        except Exception as ex:
            self._logger.error(ex)

    async def _remux_stream(self, ifname, ofname, *, extra_flags=[]):
        mux_flags = [
            "-y",
            "-hide_banner",
            "-loglevel",
            "fatal",
            "-stats",
            "-i",
            ifname,
            *extra_flags,
            "-c",
            "copy",
            "-movflags",
            "faststart",
            ofname,
        ]
        async with FFMpeg(mux_flags) as mux:
            self._logger.info("Remuxing stream", inline=True)
            while await mux.print_status():
                pass

    async def _download_chat(self, ws, fname):
        with open(fname, "w") as f:
            while True:
                comment = await ws.comments.get()
                f.write(json.dumps(comment))
                f.write("\n")

    def _get_hls_url(self, hls_info, mode):
        p_merged = self._merge_playlists(hls_info)
        p_sorted = self._sort_playlists(p_merged)
        playlist = self._get_playlist_or_best(p_sorted, mode)
        return playlist["url"], playlist["mode"]

    def _get_playlist_or_best(self, sorted_playlists, mode):
        playlist = None

        if len(sorted_playlists) == 0:
            raise FC2WebSocket.EmptyPlaylistException()

        # Find the playlist with matching (quality, latency) mode
        for p in sorted_playlists:
            if p["mode"] == mode:
                playlist = p

        # If no playlist matches, ignore the quality and find the best
        # one matching the latency
        if playlist is None:
            for p in sorted_playlists:
                _, p_latency = self._format_mode(p["mode"])
                _, r_latency = self._format_mode(mode)
                if p_latency == r_latency:
                    playlist = p
                    break

        # If no playlist matches, return the first one
        if playlist is None:
            playlist = sorted_playlists[0]

        return playlist

    def _sort_playlists(self, merged_playlists):
        def key_map(playlist):
            mode = playlist["mode"]
            if mode >= 90:
                return mode - 90
            return mode

        return sorted(merged_playlists, reverse=True, key=key_map)

    def _merge_playlists(self, hls_info):
        playlists = []
        for name in ["playlists", "playlists_high_latency", "playlists_middle_latency"]:
            if name in hls_info:
                playlists.extend(hls_info[name])
        return playlists

    def _get_mode(self):
        mode = 0
        mode += self.STREAM_QUALITY[self.params["quality"]]
        mode += self.STREAM_LATENCY[self.params["latency"]]
        return mode

    def _format_mode(self, mode):
        def dict_search(haystack, needle):
            return list(haystack.keys())[list(haystack.values()).index(needle)]

        latency = dict_search(self.STREAM_LATENCY, mode % 10)
        quality = dict_search(self.STREAM_QUALITY, mode // 10 * 10)
        return quality, latency

    def _prepare_file(self, meta=None, ext=""):
        def get_unique_name(meta, ext):
            n = 0
            while True:
                extn = ext if n == 0 else "{}.{}".format(n, ext)
                fname = self._format_outtmpl(meta, {"ext": extn})
                n += 1
                if not os.path.exists(fname):
                    return fname

        fname = get_unique_name(meta, ext)
        fpath = pathlib.Path(fname)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        return fname

    def _format_outtmpl(self, meta=None, overrides={}):
        finfo = {
            "channel_id": "",
            "channel_name": "",
            "date": datetime.now().strftime("%F"),
            "time": datetime.now().strftime("%H%M%S"),
            "title": "",
            "ext": "",
        }

        if meta is not None:
            finfo["channel_id"] = sanitize_filename(meta["channel_data"]["channelid"])
            finfo["channel_name"] = sanitize_filename(meta["profile_data"]["name"])
            finfo["title"] = sanitize_filename(meta["channel_data"]["title"])

        for key in self.params:
            if key.startswith("_"):
                finfo[key] = self.params[key]

        finfo.update(overrides)

        formatted = self.params["outtmpl"] % finfo
        if formatted.startswith("-"):
            formatted = "_" + formatted

        return formatted

    def _parse_cookies_file(self, cookies_file):
        cookies = http.cookies.SimpleCookie()
        with open(cookies_file, "r") as cf:
            for line in cf:
                try:
                    domain, _flag, path, secure, _expiration, name, value = [
                        t.strip() for t in line.split("\t")
                    ]
                    cookies[name] = value
                    cookies[name]["domain"] = domain.replace("#HttpOnly_", "")
                    cookies[name]["path"] = path
                    cookies[name]["secure"] = secure
                    cookies[name]["httponly"] = domain.startswith("#HttpOnly_")
                except Exception as ex:
                    self._logger.trace(line, repr(ex), str(ex))
        return cookies
