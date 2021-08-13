#!/usr/bin/env python3

from datetime import datetime
import http.cookies
import argparse
import asyncio
import aiohttp
import signal
import time
import json
import sys

ABOUT = {
    'name': 'fc2-live-dl',
    'version': '1.0.2',
    'date': '2021-08-09',
    'description': 'Download fc2 livestreams',
    'author': 'hizkifw',
    'license': 'MIT',
    'url': 'https://github.com/hizkifw/fc2-live-dl'
}

class Logger():
    LOGLEVELS = {
        'silent': 0,
        'error': 1,
        'warn': 2,
        'info': 3,
        'debug': 4,
        'trace': 5,
    }

    loglevel = LOGLEVELS['info']

    def __init__(self, module):
        self._module = module
        self._loadspin_n = 0

    def trace(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS['trace']:
            self._print('\033[35m', *args, **kwargs)

    def debug(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS['debug']:
            self._print('\033[36m', *args, **kwargs)

    def info(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS['info']:
            self._print('', *args, **kwargs)

    def warn(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS['warn']:
            self._print('\033[33m', *args, **kwargs)

    def error(self, *args, **kwargs):
        if self.loglevel >= self.LOGLEVELS['error']:
            self._print('\033[31m', *args, **kwargs)

    def _spin(self):
        chars = '⡆⠇⠋⠙⠸⢰⣠⣄'
        self._loadspin_n = (self._loadspin_n + 1) % len(chars)
        return chars[self._loadspin_n]

    def _print(self, prefix, *args, inline=False, spin=False):
        args = list(args)
        args.append('\033[0m')
        if spin:
            args.insert(0, self._spin())
        end = '\033[K\r' if inline else '\033[K\n'
        print('{}[{}]'.format(prefix, self._module), *args, end=end, flush=True)

class AsyncMap():
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

class FC2WebSocket():
    heartbeat_interval = 30

    def __init__(self, session, url):
        self._session = session
        self._url = url
        self._msg_id = 0
        self._msg_responses = AsyncMap()
        self._last_heartbeat = 0
        self._is_ready = False
        self._logger = Logger('ws')
        self.comments = asyncio.Queue()

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._ws = await self._session.ws_connect(self._url)
        self._logger.debug('connected')
        self._task = asyncio.create_task(
            self._main_loop(),
            name='main_loop'
        )
        return self

    async def __aexit__(self, *err):
        self._logger.trace('exit', err)
        if not self._task.done():
            self._task.cancel()
        await self._ws.close()
        self._logger.debug('closed')

    async def wait_disconnection(self):
        res = await self._task
        if res.exception() is not None:
            raise res.exception()

    async def get_hls_information(self):
        msg = await self._send_message_and_wait('get_hls_information')
        return msg['arguments']

    async def _main_loop(self):
        while True:
            msg = await asyncio.wait_for(self._ws.receive_json(), self.heartbeat_interval)
            self._logger.trace('<', json.dumps(msg)[:100])
            if msg['name'] == 'connect_complete':
                self._is_ready = True
            elif msg['name'] == '_response_':
                await self._msg_responses.put(msg['id'], msg)
            elif msg['name'] == 'control_disconnection':
                code = msg['arguments']['code']
                if code == 4101:
                    raise self.PaidProgramDisconnection()
                elif code == 4507:
                    raise self.LoginRequiredError()
                elif code == 4512:
                    raise self.MultipleConnectionError()
                else:
                    raise self.ServerDisconnection(code)
            elif msg['name'] == 'comment':
                for comment in msg['arguments']['comments']:
                    await self.comments.put(comment)

            await self._try_heartbeat()

    async def _try_heartbeat(self):
        if time.time() - self._last_heartbeat < self.heartbeat_interval:
            return
        self._logger.debug('heartbeat')
        await self._send_message('heartbeat')
        self._last_heartbeat = time.time()

    async def _send_message_and_wait(self, name, arguments={}):
        msg_id = await self._send_message(name, arguments)
        msg_wait_task = asyncio.create_task(self._msg_responses.pop(msg_id))
        _done, _pending = await asyncio.wait(
            [msg_wait_task, self._task],
            return_when=asyncio.FIRST_COMPLETED
        )
        done = _done.pop()
        if done.get_name() == 'main_loop':
            _pending.pop().cancel()
            raise done.exception()
        return done.result()

    async def _send_message(self, name, arguments={}):
        self._msg_id += 1
        self._logger.trace('>', name, arguments)
        await self._ws.send_json({
            'name': name,
            'arguments': arguments,
            'id': self._msg_id
        })
        return self._msg_id

    class ServerDisconnection(Exception):
        '''Raised when the server sends a `control_disconnection` message'''
        def __init__(self, code=None):
            if code is not None:
                self.code = code

        def __str__(self):
            return 'Server disconnected with code {}'.format(self.code)

    class PaidProgramDisconnection(ServerDisconnection):
        '''Raised when the streamer switches the broadcast to a paid program'''
        code = 4101

    class LoginRequiredError(ServerDisconnection):
        '''Raised when the stream requires a login'''
        code = 4507

    class MultipleConnectionError(ServerDisconnection):
        '''Raised when the server detects multiple connections to the same live stream'''
        code = 4512

class FC2LiveStream():
    def __init__(self, session, channel_id):
        self._meta = None
        self._session = session
        self._logger = Logger('live')
        self.channel_id = channel_id

    async def wait_for_online(self, interval):
        while not await self.is_online():
            for _ in range(interval):
                self._logger.info('Waiting for stream', inline=True, spin=True)
                await asyncio.sleep(1)

    async def is_online(self, *, refetch=True):
        meta = await self.get_meta(refetch)
        return len(meta['channel_data']['version']) > 0

    async def get_websocket_url(self):
        meta = await self.get_meta()
        if not await self.is_online(refetch=False):
            raise self.NotOnlineException()

        url = 'https://live.fc2.com/api/getControlServer.php'
        data = {
            'channel_id': self.channel_id,
            'mode': 'play',
            'orz': '',
            'channel_version': meta['channel_data']['version'],
            'client_version': '2.1.0\n+[1]',
            'client_type': 'pc',
            'client_app': 'browser_hls',
            'ipv6': '',
        }
        async with self._session.post(url, data=data) as resp:
            info = await resp.json()
            return '%(url)s?control_token=%(control_token)s' % info

    async def get_meta(self, force_refetch=False):
        if self._meta is not None and not force_refetch:
            return self._meta

        url = 'https://live.fc2.com/api/memberApi.php'
        data = {
            'channel': 1,
            'profile': 1,
            'user': 1,
            'streamid': self.channel_id,
        }
        async with self._session.post(url, data=data) as resp:
            # FC2 returns text/javascript instead of application/json
            # Content type is specified so aiohttp knows what to expect
            data = await resp.json(content_type='text/javascript')
            self._meta = data['data']
            return data['data']

    class NotOnlineException(Exception):
        '''Raised when the channel is not currently broadcasting'''

class LiveStreamRecorder():
    FFMPEG_BIN = 'ffmpeg'

    def __init__(self, src, dest):
        self._logger = Logger('recording')
        self.src = src
        self.dest = dest

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        self._ffmpeg = await asyncio.create_subprocess_exec(
            self.FFMPEG_BIN,
            '-y', '-hide_banner', '-loglevel', 'fatal', '-stats',
            '-i', self.src, '-c', 'copy', self.dest,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        return self

    async def __aexit__(self, *err):
        self._logger.trace('exit', err)
        ret = self._ffmpeg.returncode
        if ret is None:
            try:
                if hasattr(signal, 'CTRL_C_EVENT'):
                    # windows
                    self._ffmpeg.send_signal(signal.CTRL_C_EVENT) # pylint: disable=no-member
                else:
                    # unix
                    self._ffmpeg.send_signal(signal.SIGINT) # pylint: disable=no-member
            except Exception as ex:
                self._logger.error('unable to stop ffmpeg:', repr(ex), str(ex))
        ret = await self._ffmpeg.wait()
        self._logger.debug('exited with code', ret)

    async def print_status(self):
        try:
            status = await self.get_status()
            self._logger.info(status['time'], status['size'], inline=True)
            return True
        except:
            return False

    async def get_status(self):
        stderr = (await self._ffmpeg.stderr.readuntil(b'\r')).decode('utf-8')
        self._logger.trace(stderr)
        stats = {
            'frame': 0,
            'fps': 0,
            'q': 0,
            'size': '0kB',
            'time': '00:00:00.00',
            'bitrate': 'N/A',
            'speed': 'N/A',
        }
        last_item = '-'
        parts = [x for x in stderr.split(' ') if len(x) > 0]
        for item in parts:
            if last_item[-1] == '=':
                stats[last_item[:-1]] = item
            elif '=' in item:
                k, v = item.split('=')
                stats[k] = v
            last_item = item
        return stats

class FC2LiveDL():
    # Constants
    STREAM_QUALITY = {
        '150Kbps': 10,
        '400Kbps': 20,
        '1.2Mbps': 30,
        '2Mbps': 40,
        '3Mbps': 50,
        'sound': 90,
    }
    STREAM_LATENCY = {
        'low': 0,
        'high': 1,
        'mid': 2,
    }

    # Default params
    params = {
        'quality': '3Mbps',
        'latency': 'mid',
        'outtmpl': '%(date)s %(title)s (%(channel_name)s).%(ext)s',
        'write_chat': False,
        'write_info_json': False,
        'write_thumbnail': False,
        'wait_for_live': False,
        'wait_poll_interval': 5,
        'cookies_file': None,
    }

    _session = None
    _background_tasks = []

    def __init__(self, params={}):
        self._logger = Logger('fc2')
        self.params.update(params)
        # Validate outtmpl
        self._format_outtmpl()

        # Parse cookies
        self._cookies = None
        cookies_file = self.params['cookies_file']
        if cookies_file is not None:
            self._cookies = self._parse_cookies_file(cookies_file)
            self._logger.info('Loaded cookies from', cookies_file)

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(cookies=self._cookies)
        return self

    async def __aexit__(self, *err):
        self._logger.trace('exit', err)
        await self._session.close()
        self._session = None

    async def download(self, channel_id):
        tasks = []
        try:
            live = FC2LiveStream(self._session, channel_id)

            self._logger.info('Fetching stream info')
            meta = await live.get_meta()
            if self.params['write_info_json']:
                fname_info = self._format_outtmpl(meta, { 'ext': 'info.json' })
                self._logger.info('Writing info json to', fname_info)
                with open(fname_info, 'w') as f:
                    f.write(json.dumps(meta))

            if self.params['write_thumbnail']:
                fname_thumb = self._format_outtmpl(meta, { 'ext': 'png' })
                self._logger.info('Writing thumbnail to', fname_thumb)
                thumb_url = meta['channel_data']['image']
                async with self._session.get(thumb_url) as resp:
                    with open(fname_thumb, 'wb') as f:
                        async for data in resp.content.iter_chunked(1024):
                            f.write(data)

            is_online = await live.is_online(refetch=False)
            if not is_online:
                if not self.params['wait_for_live']:
                    raise FC2LiveStream.NotOnlineException()
                await live.wait_for_online(self.params['wait_poll_interval'])

            ws_url = await live.get_websocket_url()
            self._logger.info('Found websocket url')
            async with FC2WebSocket(self._session, ws_url) as ws:
                hls_info = await ws.get_hls_information()
                hls_url = self._get_hls_url(hls_info)
                self._logger.info('Received HLS info')

                coros = []

                coros.append(ws.wait_disconnection())

                fname_stream = self._format_outtmpl(meta, { 'ext': 'ts' })
                self._logger.info('Writing stream to', fname_stream)
                coros.append(self._download_stream(hls_url, fname_stream))

                if self.params['write_chat']:
                    fname_chat = self._format_outtmpl(meta, { 'ext': 'fc2chat.json' })
                    self._logger.info('Writing chat to', fname_chat)
                    coros.append(self._download_chat(ws, fname_chat))

                tasks = [asyncio.create_task(coro) for coro in coros]

                self._logger.debug('Starting', len(tasks), 'tasks')
                _exited, _pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )
                self._logger.debug('Tasks exited')

                while len(_pending) > 0:
                    pending_task = _pending.pop()
                    self._logger.trace('Cancelling pending task', pending_task)
                    pending_task.cancel()

                exited = _exited.pop()
                self._logger.trace('Exited task was', exited)
                if exited.exception() is not None:
                    raise exited.exception()

        except asyncio.CancelledError:
            self._logger.error('Interrupted by user')
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _download_stream(self, hls_url, fname):
        async with LiveStreamRecorder(hls_url, fname) as rec:
            self._logger.info('Starting download', inline=True)
            while await rec.print_status():
                pass

    async def _download_chat(self, ws, fname):
        with open(fname, 'w') as f:
            while True:
                comment = await ws.comments.get()
                f.write(json.dumps(comment))
                f.write('\n')

    def _get_hls_url(self, hls_info):
        mode = self._get_mode()
        p_merged = self._merge_playlists(hls_info)
        p_sorted = self._sort_playlists(p_merged)
        playlist = self._get_playlist_or_best(p_sorted, mode)
        return playlist['url']

    def _get_playlist_or_best(self, sorted_playlists, mode=None):
        playlist = None
        for p in sorted_playlists:
            if p['mode'] == mode:
                playlist = p

        if playlist is None:
            playlist = sorted_playlists[0]
            self._logger.warn(
                'Requested quality',
                self._format_mode(mode),
                'is not available'
            )
            self._logger.warn(
                'falling back to next best quality',
                self._format_mode(playlist['mode'])
            )

        return playlist

    def _sort_playlists(self, merged_playlists):
        def key_map(playlist):
            mode = playlist['mode']
            if mode >= 90:
                return mode - 90
            return mode

        return sorted(
            merged_playlists,
            reverse=True,
            key=key_map
        )

    def _merge_playlists(self, hls_info):
        playlists = []
        for name in ['playlists', 'playlists_high_latency', 'playlists_middle_latency']:
            if name in hls_info:
                playlists.extend(hls_info[name])
        return playlists

    def _get_mode(self):
        mode = 0
        mode += self.STREAM_QUALITY[self.params['quality']]
        mode += self.STREAM_LATENCY[self.params['latency']]
        return mode

    def _format_mode(self, mode):
        def dict_search(haystack, needle):
            return list(haystack.keys())[list(haystack.values()).index(needle)]
        latency = dict_search(self.STREAM_LATENCY, mode % 10)
        quality = dict_search(self.STREAM_QUALITY, mode // 10 * 10)
        return quality, latency

    def _format_outtmpl(self, meta=None, overrides={}):
        def sanitize_filename(fname):
            fname = str(fname)
            for c in '<>:"/\\|?*':
                fname = fname.replace(c, '_')
            return fname

        finfo = {
            'channel_id': '',
            'channel_name': '',
            'date': datetime.now().strftime('%F'),
            'time': datetime.now().strftime('%H%M%S'),
            'title': '',
            'ext': ''
        }

        if meta is not None:
            finfo['channel_id'] = sanitize_filename(meta['channel_data']['channelid'])
            finfo['channel_name'] = sanitize_filename(meta['profile_data']['name'])
            finfo['title'] = sanitize_filename(meta['channel_data']['title'])

        finfo.update(overrides)

        formatted = self.params['outtmpl'] % finfo
        if formatted.startswith('-'):
            formatted = '_' + formatted

        return formatted

    def _parse_cookies_file(self, cookies_file):
        cookies = http.cookies.SimpleCookie()
        with open(cookies_file, 'r') as cf:
            for line in cf:
                try:
                    domain, _flag, path, secure, _expiration, name, value = [t.strip() for t in line.split('\t')]
                    cookies[name] = value
                    cookies[name]['domain'] = domain
                    cookies[name]['path'] = path
                    cookies[name]['secure'] = secure
                except:
                    pass
        return cookies

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
        if text.startswith('R|'):
            return text[2:].splitlines()  
        elif text.startswith('A|'):
            return self.flatten(
                [
                    argparse.HelpFormatter._split_lines(self, x, width)
                        if len(x) >= width else x
                    for x in text[2:].splitlines()
                ]
            )
        return argparse.HelpFormatter._split_lines(self, text, width)

async def main(args):
    version = '%(name)s v%(version)s' % ABOUT
    parser = argparse.ArgumentParser(formatter_class=SmartFormatter)
    parser.add_argument('url',
        help='A live.fc2.com URL.'
    )

    parser.add_argument(
        '-v', '--version',
        action='version',
        version=version
    )
    parser.add_argument(
        '--quality',
        choices=FC2LiveDL.STREAM_QUALITY.keys(),
        default=FC2LiveDL.params['quality'],
        help='Quality of the stream to download. Default is {}.'.format(FC2LiveDL.params['quality'])
    )
    parser.add_argument(
        '--latency',
        choices=FC2LiveDL.STREAM_LATENCY.keys(),
        default=FC2LiveDL.params['latency'],
        help='Stream latency. Select a higher latency if experiencing stability issues. Default is {}.'.format(FC2LiveDL.params['latency'])
    )
    parser.add_argument(
        '-o', '--output',
        default=FC2LiveDL.params['outtmpl'],
        help='''A|Set the output filename format. Supports formatting options similar to youtube-dl. Default is '{}'

Available format options:
    channel_id (string): ID of the broadcast
    channel_name (string): broadcaster's profile name
    date (string): local date YYYY-MM-DD
    time (string): local time HHMMSS
    ext (string): file extension
    title (string): title of the live broadcast'''.format(FC2LiveDL.params['outtmpl'].replace('%', '%%'))
    )

    #  parser.add_argument(
        #  '--cookies',
        #  help='Path to a cookies file.'
    #  )

    parser.add_argument(
        '--write-chat',
        action='store_true',
        help='Save live chat into a json file.'
    )
    parser.add_argument(
        '--write-info-json',
        action='store_true',
        help='Dump output stream information into a json file.'
    )
    parser.add_argument(
        '--write-thumbnail',
        action='store_true',
        help='Download thumbnail into a file'
    )
    parser.add_argument(
        '--wait',
        action='store_true',
        help='Wait until the broadcast goes live, then start recording.'
    )
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=FC2LiveDL.params['wait_poll_interval'],
        help='How many seconds between checks to see if broadcast is live. Default is {}.'.format(FC2LiveDL.params['wait_poll_interval'])
    )
    parser.add_argument(
        '--log-level',
        default='info',
        choices=Logger.LOGLEVELS.keys(),
        help='Log level verbosity. Default is info.'
    )

    # Init fc2-live-dl
    args = parser.parse_args(args[1:])
    Logger.loglevel = Logger.LOGLEVELS[args.log_level]
    params = {
        'quality': args.quality,
        'latency': args.latency,
        'outtmpl': args.output,
        'write_chat': args.write_chat,
        'write_info_json': args.write_info_json,
        'write_thumbnail': args.write_thumbnail,
        'wait_for_live': args.wait,
        'wait_poll_interval': args.poll_interval,
        #  'cookies_file': args.cookies,
    }
    channel_id = args.url.split('https://live.fc2.com')[1].split('/')[1]
    logger = Logger('main')

    logger.info(version)

    async with FC2LiveDL(params) as fc2:
        try:
            await fc2.download(channel_id)
        except Exception as ex:
            logger.error(repr(ex), str(ex))

if __name__ == '__main__':
    # Set up asyncio loop
    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(main(sys.argv))
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
    finally:
        # Give some time for aiohttp cleanup
        loop.run_until_complete(asyncio.sleep(0.250))
        loop.close()
