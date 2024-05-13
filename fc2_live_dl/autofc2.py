import traceback
import argparse
import asyncio
import json
import time

import apprise
from aiohttp import web

from .FC2LiveDL import FC2LiveDL, CallbackEvent
from .util import Logger


class Metrics:
    prefix = "autofc2_"

    def __init__(self):
        self._lock = asyncio.Lock()
        self._channel_metrics = {}

    def _reset(self, channel_id):
        self._channel_metrics[channel_id] = {
            "event_type": 0,
            "fragments_downloaded": 0,
            "total_downloaded": 0,
        }

    async def reset(self, channel_id):
        async with self._lock:
            self._reset(channel_id)

    async def update(self, event: CallbackEvent):
        async with self._lock:
            if event.channel_id not in self._channel_metrics:
                self._reset(event.channel_id)

            self._channel_metrics[event.channel_id]["event_type"] = event.type
            if event.type == CallbackEvent.Type.FRAGMENT_PROGRESS:
                self._channel_metrics[event.channel_id]["fragments_downloaded"] = (
                    event.data["fragments_downloaded"]
                )
                self._channel_metrics[event.channel_id]["total_downloaded"] = (
                    event.data["total_size"]
                )

    async def promstr(self):
        async with self._lock:
            res = ""
            for channel_id, metrics in self._channel_metrics.items():
                label = f'channel_id="{channel_id}"'

                for typ in CallbackEvent.Type:
                    val = 1 if metrics["event_type"] == typ else 0
                    res += f'{self.prefix}event{{{label},type="{typ.name.lower()}"}} {val}\n'

                res += f"{self.prefix}fragments_downloaded{{{label}}} {metrics['fragments_downloaded']}\n"
                res += f"{self.prefix}bytes_downloaded{{{label}}} {metrics['total_downloaded']}\n"

            return res

    async def http_server(self, host, port, path):
        async def handler(request):
            return web.Response(text=await self.promstr(), content_type="text/plain")

        app = web.Application()
        app.add_routes([web.get(path, handler)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()


class ChannelState:
    def __init__(self):
        self._last_startup_time = 0

    async def wait_for_debounce(self, duration):
        diff = time.time() - self._last_startup_time
        if diff < duration:
            await asyncio.sleep(duration - diff)
        self._last_startup_time = time.time()


class AutoFC2:
    default_args = {
        "config": "autofc2.json",
    }

    def __init__(self, args):
        # Merge default args with user args
        self.args = self.clone(self.default_args)
        self.args.update(args)

        self.logger = Logger("autofc2")
        self.logger.info("starting")
        self.last_valid_config = None
        self.metrics = Metrics()
        self.channel_state = {}

        # Disable progress spinners
        Logger.print_inline = False

    def get_config(self):
        try:
            with open(self.args["config"], "r", encoding="utf8") as f:
                self.last_valid_config = json.load(f)
        except Exception as ex:
            if self.last_valid_config is None:
                self.logger.error("Error reading config file")
                raise ex
            else:
                self.logger.warn("Warning: unable to load config, using last valid one")
                self.logger.warn(ex)
        return self.last_valid_config

    def clone(self, obj):
        return json.loads(json.dumps(obj))

    def get_channels(self):
        config = self.get_config()
        return config["channels"].keys()

    def get_channel_params(self, channel_id):
        config = self.get_config()
        params = self.clone(config["default_params"])
        params.update(self.clone(config["channels"][channel_id]))
        return params

    def reload_channels_list(self, tasks):
        async def noop():
            pass

        channels = self.get_channels()
        for channel_id in channels:
            if channel_id not in tasks:
                tasks[channel_id] = asyncio.create_task(noop())

        for channel_id in tasks.keys():
            if channel_id not in channels:
                tasks[channel_id].cancel()

    async def debounce_channel(self, channel_id):
        config = self.get_config()
        debounce_time = 0
        if "autofc2" in config and "debounce_time" in config["autofc2"]:
            debounce_time = config["autofc2"]["debounce_time"]

        if channel_id not in self.channel_state:
            self.channel_state[channel_id] = ChannelState()

        if debounce_time > 0:
            await self.channel_state[channel_id].wait_for_debounce(debounce_time)

    async def config_watcher(self):
        last_log_level = Logger.loglevel

        while True:
            await asyncio.sleep(1)

            config = self.get_config()

            if "autofc2" not in config:
                continue

            log_level = config["autofc2"]["log_level"]
            if log_level == last_log_level:
                continue

            last_log_level = log_level

            if log_level not in Logger.LOGLEVELS:
                self.logger.error(f"Invalid log level {log_level}")
                continue

            Logger.loglevel = Logger.LOGLEVELS[log_level]
            self.logger.info(f"Setting log level to {log_level}")

    async def handle_event(self, event):
        try:
            await self.metrics.update(event)

            if event.type != CallbackEvent.Type.GOT_HLS_URL:
                return

            config = self.get_config()
            finfo = FC2LiveDL.get_format_info(
                meta=event.data["meta"],
                params=event.instance.params,
                sanitize=False,
            )

            if "notifications" not in config:
                return

            for cfg in config["notifications"]:
                notifier = apprise.Apprise()
                notifier.add(cfg["url"])
                await notifier.async_notify(body=cfg["message"] % finfo)

        except:
            self.logger.error("Error handling event")
            self.logger.error(traceback.format_exc())
            return

    async def handle_channel(self, channel_id):
        params = self.get_channel_params(channel_id)
        async with FC2LiveDL(params, self.handle_event) as fc2:
            await self.debounce_channel(channel_id)
            await self.metrics.reset(channel_id)
            await fc2.download(channel_id)

    async def metrics_webserver(self):
        config = self.get_config()
        if "autofc2" not in config or "metrics" not in config["autofc2"]:
            # Stall forever
            return await asyncio.Future()

        metrics_cfg = config["autofc2"]["metrics"]

        self.logger.info(
            f"Metrics available at http://{metrics_cfg['host']}:{metrics_cfg['port']}{metrics_cfg['path']}"
        )
        return await self.metrics.http_server(
            metrics_cfg["host"],
            metrics_cfg["port"],
            metrics_cfg["path"],
        )

    async def _main(self):
        tasks = {}
        sleep_task = None
        config_task = asyncio.create_task(self.config_watcher())
        metrics_task = asyncio.create_task(self.metrics_webserver())
        try:
            while True:
                self.reload_channels_list(tasks)
                sleep_task = asyncio.create_task(asyncio.sleep(1))
                task_arr = [config_task, sleep_task, metrics_task]
                for channel in tasks.keys():
                    if tasks[channel].done():
                        tasks[channel] = asyncio.create_task(
                            self.handle_channel(channel)
                        )
                    task_arr.append(tasks[channel])

                await asyncio.wait(task_arr, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            self.logger.error("Interrupted")
        finally:
            if sleep_task is not None:
                sleep_task.cancel()
            for task in tasks.values():
                task.cancel()

    def main(self):
        try:
            asyncio.run(self._main())
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Automatically download FC2 live streams"
    )
    parser.add_argument(
        "--config",
        "-c",
        help="config file to use",
        default="autofc2.json",
    )
    args = parser.parse_args()

    AutoFC2({"config": args.config}).main()


if __name__ == "__main__":
    main()
