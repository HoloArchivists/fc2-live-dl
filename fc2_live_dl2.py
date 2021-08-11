#!/usr/bin/env python3

from datetime import datetime
import argparse
import asyncio
import aiohttp
import signal
import time
import json
import sys

ABOUT = {
    'name': 'fc2-live-dl',
    'version': '0.0.1',
    'date': '2021-08-09',
    'description': 'Download fc2 livestreams',
    'author': 'hizkifw',
    'license': 'MIT',
    'url': 'https://github.com/hizkifw/fc2-live-dl'
}

def clearline():
    print('\033[2K\r', end='')

loadspin_n = 0
def loadspin():
    global loadspin_n
    chars = '⠋⠙⠸⠴⠦⠇'
    loadspin_n = (loadspin_n + 1) % len(chars)
    return chars[loadspin_n]

def parse_ffmpeg_stats(stderr):
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

def sanitize_filename(fname):
    for c in '<>:"/\\|?*':
        fname = fname.replace(c, '_')
    return fname

class FC2WebSocket():
    heartbeat_interval = 30

    def __init__(self, session, url):
        self._session = session
        self._url = url
        self._msg_id = 0
        self._msg_responses = {}
        self._is_ready = False
        self.comments = asyncio.Queue()

    async def __aenter__(self):
        self._ws = await self._session.ws_connect(self._url)
        coros = [self._handle_incoming, self._handle_heartbeat]
        self._tasks = [asyncio.create_task(coro()) for coro in coros]
        return self

    async def __aexit__(self, *err):
        for task in self._tasks:
            await task.cancel()
        await self._ws.close()

    async def get_hls_information(self):
        return await self._send_message_and_wait('get_hls_information')

    async def _handle_incoming(self):
        while True:
            msg = await self._ws.receive_json()
            if msg['name'] == 'connect_complete':
                self._is_ready = True
            elif msg['name'] == '_response_':
                self._msg_responses[msg['id']] = msg['arguments']
            elif msg['name'] == 'control_disconnection':
                code = msg['arguments']['code']
                if code == 4101:
                    raise self.PaidProgramDisconnection()
                elif code == 4512:
                    raise self.MultipleConnectionError()
            elif msg['name'] == 'comment':
                for comment in msg['arguments']['comments']:
                    self.comments.put(comment)

    async def _handle_heartbeat(self):
        while True:
            await self._send_message('heartbeat')
            await asyncio.sleep(self.heartbeat_interval)

    async def _send_message_and_wait(self, name, arguments={}):
        msg_id = self._send_message(name, arguments)
        return await self._receive_message(msg_id)

    async def _receive_message(self, msg_id=None):
        while True:
            if msg_id is not None and msg_id in self._msg_responses:
                return self._msg_responses.pop(msg_id)

            msg = await self._ws.receive_json()
            if msg['name'] == '_response_':
                self._msg_responses[msg['id']] = msg
            elif msg_id is None:
                return msg

    async def _send_message(self, name, arguments={}):
        self._msg_id += 1
        await self._ws.send_json({
            'name': name,
            'arguments': arguments,
            'id': self._msg_id
        })
        return self._msg_id

    class ServerDisconnection(Exception):
        '''Raised when the server sends a `control_disconnection` message'''

    class MultipleConnectionError(ServerDisconnection):
        '''Raised when the server detects multiple connections to the same live stream'''

    class PaidProgramDisconnection(ServerDisconnection):
        '''Raised when the streamer switches the broadcast to a paid program'''

class FC2LiveStream():
    def __init__(self, session, channel_id):
        self._meta = None
        self._session = session
        self.channel_id = channel_id

    async def wait_for_online(self, interval):
        while not self.is_online():
            await asyncio.sleep(interval)

    async def is_online(self):
        meta = await self.get_meta(True)
        return len(meta['channel_data']['version']) > 0

    async def get_websocket_url(self):
        meta = await self.get_meta()
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
        if self._meta is not None and not force_refresh:
            return self._meta

        url = 'https://live.fc2.com/api/memberApi.php',
        data = {
            'channel': 1,
            'profile': 1,
            'user': 1,
            'streamid': self.channel_id,
        }
        async with self._session.post(url, data=data) as resp:
            data = await resp.json()
            self._meta = data['data']
            return data['data']

class FC2LiveDL():
    # Configuration
    FFMPEG_BIN = 'ffmpeg'

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
        'outtmpl': '%(channel_id)s-%(date)s-%(title)s.%(ext)s',
        'save_chat': False,
        'wait_for_live': False,
        'wait_poll_interval': 5,
    }

    _session = None
    _background_tasks = []

    def __init__(self, params={}):
        self.params.update(params)
        # Validate outtmpl
        self._format_outtmpl(self.params['outtmpl'])

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *err):
        await self._session.close()
        self._session = None

    async def download(self, channel_id):
        live = FC2LiveStream(self._session, channel_id)

        is_online = await live.is_online()
        if not is_online and self.params['wait_for_live']:
            while not await live.is_online():
                await asyncio.sleep(self.params['wait_poll_interval'])

        meta = await live.get_meta()
        ws_url = await live.get_websocket_url()
        async with FC2WebSocket(self._session, ws_url) as ws:
            pass

    def _format_mode(self, mode):
        def dict_search(haystack, needle):
            return list(haystack.keys())[list(haystack.values()).index(needle)]
        latency = dict_search(self.STREAM_LATENCY, mode % 10)
        quality = dict_search(self.STREAM_QUALITY, mode // 10 * 10)
        return quality, latency

    def _format_outtmpl(self, outtmpl, overrides={}):
        finfo = {
            'channel_id': self._channel_id,
            'channel_name': '',
            'date': datetime.now().strftime('%F_%H%M%S'),
            'title': '',
            'ext': ''
        }

        if self._stream_meta is not None:
            finfo['channel_name'] = sanitize_filename(self._stream_meta['profile_data']['name'])
            finfo['title'] = sanitize_filename(self._stream_meta['channel_data']['title'])

        finfo.update(overrides)
        return outtmpl % finfo

    '''
    -----------------------------------------
    '''

    async def _wait_and_download(self):
        # Wait until HLS info from websocket is available
        while len(self._hls_info) == 0:
            if self._is_live == False:
                return
            await asyncio.sleep(0.1)

        mode = 0
        mode += STREAM_QUALITY[self.params['quality']]
        mode += STREAM_LATENCY[self.params['latency']]

        playlist = None
        for p in self._hls_info:
            if p['mode'] == mode:
                playlist = p

        # Requested mode not found, fallback to the next best quality
        if playlist is None:
            print('[download] requested mode not available: {}'.format(mode))
            print('[download] available formats are: {}'.format(', '.join([str(x['mode']) for x in self._hls_info])))
            playlist = self._hls_info[0]
            print('[download] falling back to the next best quality: {}'.format(self._hls_info[0]['mode']))

        self._finfo['ext'] = 'ts'
        fname = self.params['outtmpl'] % self._finfo
        if fname.startswith('-'):
            fname = '_' + fname

        quality, latency = format_mode(playlist['mode'])
        print('[download] downloading {} at {} latency ({})'.format(quality, latency, playlist['mode']))
        print('[download] saving to {}'.format(fname))
        print('[download] starting...', end='')

        ffmpeg = await asyncio.create_subprocess_exec(
            FFMPEG_BIN,
            '-hide_banner', '-loglevel', 'fatal', '-stats',
            '-i', playlist['url'], '-c', 'copy', fname,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )

        while ffmpeg.returncode is None:
            try:
                stderr = (await ffmpeg.stderr.readuntil(b'\r')).decode('utf-8')
                if len(stderr) > 0:
                    # Parse ffmpeg's output
                    stats = parse_ffmpeg_stats(stderr)
                    clearline()
                    print('[download] {} {}'.format(stats['time'], stats['size']), end='')
                    if self.params['save_chat']:
                        print(', {} chat msg'.format(self._chat_msg_count), end='')
                    print('\r')
            except asyncio.IncompleteReadError:
                print('')
                break
            except asyncio.CancelledError:
                print('[download] stopping ffmpeg')
                ffmpeg.send_signal(signal.SIGINT)
                await ffmpeg.wait()
            except Exception as ex:
                print('')
                print(repr(ex))

        print('[download] ffmpeg closing\r', end='')
        if ffmpeg.returncode is None:
            await ffmpeg.wait()
        print('[download] ffmpeg exited with code {}'.format(ffmpeg.returncode))

    async def _prepare_for_download(self):
        print('[fc2] fetching member details')
        self._aiohttp_session = aiohttp.ClientSession()
        await self._get_member_details()
        print('[fc2] found channel {}'.format(self._finfo['channel_name']))

        while not self._is_live:
            if not self.params['wait_for_live']:
                print('[fc2] broadcast is not yet live')
                return

            clearline()
            for _ in range(10):
                print('[fc2] {} waiting for member to go live'.format(loadspin()), end='\r')
                await asyncio.sleep(self.params['wait_poll_interval'] / 10)
            print('[fc2] {} waiting for member to go live (checking...)'.format(loadspin()), end='\r')
            await self._get_member_details()

        if self.params['save_chat']:
            self._finfo['ext'] = 'fc2chat.json'
            chat_fname = self.params['outtmpl'] % self._finfo
            print('[fc2] saving chat to {}'.format(chat_fname))
            self._chat_file = open(chat_fname, 'w')
            self._chat_file.write(json.dumps({
                'file': 'fc2-live-chat',
                'version': '1',
                'metadata': {
                    'time_now_ms': int(time.time() * 1000)
                }
            }))
            self._chat_file.write('\n')

    async def start_download(self):
        tasks = []
        try:
            await self._prepare_for_download()
            tasks.append(asyncio.ensure_future(self._connect_to_websocket()))
            tasks.append(asyncio.ensure_future(self._wait_and_download()))
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            print('\n[fc2] Interrupted by user')
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Wait for cleanup
            await asyncio.wait(tasks)

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

def main(args):
    parser = argparse.ArgumentParser(formatter_class=SmartFormatter)
    parser.add_argument('url',
        help='A live.fc2.com URL.'
    )
    parser.add_argument(
        '--quality',
        choices=STREAM_QUALITY.keys(),
        default=FC2LiveDL.params['quality'],
        help='Quality of the stream to download. Default is {}.'.format(FC2LiveDL.params['quality'])
    )
    parser.add_argument(
        '--latency',
        choices=STREAM_LATENCY.keys(),
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
    date (string): current date and time in the format YYYY-MM-DD_HHMMSS
    ext (string): file extension
    title (string): title of the live broadcast'''.format(FC2LiveDL.params['outtmpl'].replace('%', '%%'))
    )

    parser.add_argument(
        '--save-chat',
        action='store_true',
        help='Save live chat into a json file.'
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

    # Init fc2-live-dl
    args = parser.parse_args(args[1:])
    fc2 = FC2LiveDL({
        'url': args.url,
        'quality': args.quality,
        'latency': args.latency,
        'outtmpl': args.output,
        'save_chat': args.save_chat,
        'wait_for_live': args.wait,
        'wait_poll_interval': args.poll_interval,
    })

    # Set up asyncio loop
    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(fc2.start_download())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        loop.run_until_complete(task)
    finally:
        # Give some time for aiohttp cleanup
        loop.run_until_complete(asyncio.sleep(0.250))
        loop.close()

if __name__ == '__main__':
    main(sys.argv)
