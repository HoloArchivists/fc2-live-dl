import argparse
import asyncio
import copy
import json

from .FC2LiveDL import FC2LiveDL
from .util import Logger


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

    async def handle_channel(self, channel_id):
        params = self.get_channel_params(channel_id)
        async with FC2LiveDL(params) as fc2:
            await fc2.download(channel_id)

    async def _main(self):
        tasks = {}
        sleep_task = None
        config_task = asyncio.create_task(self.config_watcher())
        try:
            while True:
                self.reload_channels_list(tasks)
                sleep_task = asyncio.create_task(asyncio.sleep(1))
                task_arr = [config_task, sleep_task]
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
