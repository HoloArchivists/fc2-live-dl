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

    def __init__(self, module):
        self._module = module
        self._loadspin_n = 0

    def trace(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["trace"]:
            self._print("\033[35m", *args, **kwargs)

    def debug(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["debug"]:
            self._print("\033[36m", *args, **kwargs)

    def info(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["info"]:
            self._print("", *args, **kwargs)

    def warn(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["warn"]:
            self._print("\033[33m", *args, **kwargs)

    def error(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS["error"]:
            self._print("\033[31m", *args, **kwargs)

    def _spin(self):
        chars = "⡆⠇⠋⠙⠸⢰⣠⣄"
        self._loadspin_n = (self._loadspin_n + 1) % len(chars)
        return chars[self._loadspin_n]

    def _print(self, prefix, *args, inline=False, spin=False):
        if inline and not self.print_inline:
            return

        args = list(args)
        args.append("\033[0m")
        if spin:
            args.insert(0, self._spin())
        end = "\033[K\r" if inline else "\033[K\n"
        print("{}[{}]".format(prefix, self._module), *args, end=end, flush=True)


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
