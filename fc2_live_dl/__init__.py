from importlib.metadata import version
import argparse
import asyncio
import json
import sys

from .util import Logger, SmartFormatter
from .FC2LiveDL import FC2LiveDL

try:
    __version__ = version(__name__)
except:
    __version__ = "unknown"

ABOUT = {
    "name": "fc2-live-dl",
    "version": __version__,
    "date": "2022-01-12",
    "description": "Download fc2 livestreams",
    "author": "hizkifw",
    "license": "MIT",
    "url": "https://github.com/hizkifw/fc2-live-dl",
}


async def _main(args):
    version = "%(name)s v%(version)s" % ABOUT
    parser = argparse.ArgumentParser(formatter_class=SmartFormatter)
    parser.add_argument("url", help="A live.fc2.com URL.")

    parser.add_argument("-v", "--version", action="version", version=version)
    parser.add_argument(
        "--quality",
        choices=FC2LiveDL.STREAM_QUALITY.keys(),
        default=FC2LiveDL.DEFAULT_PARAMS["quality"],
        help="Quality of the stream to download. Default is {}.".format(
            FC2LiveDL.DEFAULT_PARAMS["quality"]
        ),
    )
    parser.add_argument(
        "--latency",
        choices=FC2LiveDL.STREAM_LATENCY.keys(),
        default=FC2LiveDL.DEFAULT_PARAMS["latency"],
        help="Stream latency. Select a higher latency if experiencing stability issues. Default is {}.".format(
            FC2LiveDL.DEFAULT_PARAMS["latency"]
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="The size of the thread pool used to download segments. Default is 1.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=FC2LiveDL.DEFAULT_PARAMS["outtmpl"],
        help="""A|Set the output filename format. Supports formatting options similar to youtube-dl. Default is '{}'

Available format options:
    channel_id (string): ID of the broadcast
    channel_name (string): broadcaster's profile name
    date (string): local date YYYY-MM-DD
    time (string): local time HHMMSS
    ext (string): file extension
    title (string): title of the live broadcast""".format(
            FC2LiveDL.DEFAULT_PARAMS["outtmpl"].replace("%", "%%")
        ),
    )

    parser.add_argument(
        "--no-remux",
        action="store_true",
        help="Do not remux recordings into mp4/m4a after it is finished.",
    )
    parser.add_argument(
        "-k",
        "--keep-intermediates",
        action="store_true",
        help="Keep the raw .ts recordings after it has been remuxed.",
    )
    parser.add_argument(
        "-x",
        "--extract-audio",
        action="store_true",
        help="Generate an audio-only copy of the stream.",
    )

    parser.add_argument("--cookies", help="Path to a cookies file.")

    parser.add_argument(
        "--write-chat", action="store_true", help="Save live chat into a json file."
    )
    parser.add_argument(
        "--write-info-json",
        action="store_true",
        help="Dump output stream information into a json file.",
    )
    parser.add_argument(
        "--write-thumbnail", action="store_true", help="Download thumbnail into a file"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait until the broadcast goes live, then start recording.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=FC2LiveDL.DEFAULT_PARAMS["wait_poll_interval"],
        help="How many seconds between checks to see if broadcast is live. Default is {}.".format(
            FC2LiveDL.DEFAULT_PARAMS["wait_poll_interval"]
        ),
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=Logger.LOGLEVELS.keys(),
        help="Log level verbosity. Default is info.",
    )

    # Debug flags
    parser.add_argument(
        "--dump-websocket",
        action="store_true",
        help="Dump all websocket communication to a file for debugging",
    )

    # Init fc2-live-dl
    args = parser.parse_args(args[1:])
    Logger.loglevel = Logger.LOGLEVELS[args.log_level]
    params = {
        "quality": args.quality,
        "latency": args.latency,
        "threads": args.threads,
        "outtmpl": args.output,
        "write_chat": args.write_chat,
        "write_info_json": args.write_info_json,
        "write_thumbnail": args.write_thumbnail,
        "wait_for_live": args.wait,
        "wait_poll_interval": args.poll_interval,
        "cookies_file": args.cookies,
        "remux": not args.no_remux,
        "keep_intermediates": args.keep_intermediates,
        "extract_audio": args.extract_audio,
        # Debug params
        "dump_websocket": args.dump_websocket,
    }

    logger = Logger("main")

    channel_id = None
    try:
        channel_id = (
            args.url.replace("http:", "https:")
            .split("https://live.fc2.com")[1]
            .split("/")[1]
        )
    except:
        logger.error("Error parsing URL: please provide a https://live.fc2.com/ URL.")
        return False

    logger.info(version)
    logger.debug("Using options:", json.dumps(vars(args), indent=2))

    async with FC2LiveDL(params) as fc2:
        try:
            await fc2.download(channel_id)
            logger.debug("Done")
        except Exception as ex:
            logger.error(repr(ex), str(ex))


def main():
    try:
        asyncio.run(_main(sys.argv))
    except KeyboardInterrupt:
        pass


__all__ = ["main", "FC2LiveDL"]
