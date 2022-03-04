import re
import sys
import asyncio
import argparse


class Logger:
    LOGLEVELS = {
        "silent": 0,
        "error": 1,
        "warn": 2,
        "info": 3,
        "debug": 4,
        "trace": 5,
    }

    loglevel = LOGLEVELS["info"]
    print_inline = True
    print_colors = True

    ansi_purple = "\033[35m"
    ansi_cyan = "\033[36m"
    ansi_yellow = "\033[33m"
    ansi_red = "\033[31m"
    ansi_reset = "\033[0m"
    ansi_delete_line = "\033[K"

    def __init__(self, module):
        self._module = module
        self._loadspin_n = 0

        if not sys.stdout.isatty():
            self.print_inline = False
            self.print_colors = False

    def trace(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["trace"]:
            self._print(self.ansi_purple, *args, **kwargs)

    def debug(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["debug"]:
            self._print(self.ansi_cyan, *args, **kwargs)

    def info(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["info"]:
            self._print("", *args, **kwargs)

    def warn(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["warn"]:
            self._print(self.ansi_yellow, *args, **kwargs)

    def error(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["error"]:
            self._print(self.ansi_red, *args, **kwargs)

    def _spin(self):
        chars = "⡆⠇⠋⠙⠸⢰⣠⣄"
        self._loadspin_n = (self._loadspin_n + 1) % len(chars)
        return chars[self._loadspin_n]

    def _print(self, color, *args, inline=False, spin=False):
        if inline and not self.print_inline:
            return

        args = list(args)

        if self.print_colors:
            args.append(self.ansi_reset)
        else:
            color = ""

        if spin:
            args.insert(0, self._spin())

        end = self.ansi_delete_line if self.print_inline else ""
        end = end + ("\r" if inline else "\n")

        print("{}[{}]".format(color, self._module), *args, end=end, flush=True)


class AsyncMap:
    def __init__(self):
        self._map = {}
        self._cond = asyncio.Condition()

    async def put(self, key, value):
        async with self._cond:
            self._map[key] = value
            self._cond.notify_all()

    async def pop(self, key):
        while True:
            async with self._cond:
                await self._cond.wait()
                if key in self._map:
                    return self._map.pop(key)


class SmartFormatter(argparse.HelpFormatter):
    def flatten(self, input_array):
        result_array = []
        for element in input_array:
            if isinstance(element, str):
                result_array.append(element)
            elif isinstance(element, list):
                result_array += self.flatten(element)
        return result_array

    def _split_lines(self, text, width):
        if text.startswith("R|"):
            return text[2:].splitlines()
        elif text.startswith("A|"):
            return self.flatten(
                [
                    argparse.HelpFormatter._split_lines(self, x, width)
                    if len(x) >= width
                    else x
                    for x in text[2:].splitlines()
                ]
            )
        return argparse.HelpFormatter._split_lines(self, text, width)


def sanitize_filename(fname):
    # https://stackoverflow.com/a/31976060
    fname = str(fname)

    # replace windows and linux forbidden characters
    fname = re.sub(r"[\\/:*?\"<>|]+", "_", fname)

    # remove ascii control characters
    fname = re.sub(r"[\x00-\x1f\x7f]", "", fname)

    # remove leading and trailing whitespace
    fname = fname.strip()

    # remove leading and trailing dots
    fname = fname.strip(".")

    # check windows reserved names
    badnames = """
        CON PRN AUX NUL
        COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9
        LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9
    """.split()

    fup = fname.upper()
    for badname in badnames:
        if fup == badname or fup.startswith(badname + "."):
            fname = "_" + fname

    return fname
