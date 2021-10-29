# fc2-live-dl

> Tool to download FC2 live streams

## Requirements

- python 3.8
- ffmpeg
- aiohttp (`pip install -r requirements.txt`)

## Features

- Wait for a stream to start and automatically start recording
- Save comment/chat logs
- Authenticate with cookies (Netscape format, same one used with youtube-dl)
- Remux recordings to .mp4/.m4a after it's done
- Continuously monitor multiple streams in parallel and automatically start downloading when any of them goes online

## Usage

```
python3 fc2_live_dl.py https://live.fc2.com/<...>
```

```
usage: fc2_live_dl.py [-h] [-v]
                      [--quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}]
                      [--latency {low,high,mid}] [--threads THREADS]
                      [-o OUTPUT] [--no-remux] [-k] [--cookies COOKIES]
                      [--write-chat] [--write-info-json] [--write-thumbnail]
                      [--wait] [--poll-interval POLL_INTERVAL]
                      [--log-level {silent,error,warn,info,debug,trace}]
                      url

positional arguments:
  url                   A live.fc2.com URL.

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  --quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}
                        Quality of the stream to download. Default is 3Mbps.
  --latency {low,high,mid}
                        Stream latency. Select a higher latency if
                        experiencing stability issues. Default is mid.
  --threads THREADS     The size of the thread pool used to download segments.
                        Default is 1.
  -o OUTPUT, --output OUTPUT
                        Set the output filename format. Supports formatting
                        options similar to youtube-dl. Default is '%(date)s
                        %(title)s (%(channel_name)s).%(ext)s'
                        
                        Available format options:
                            channel_id (string): ID of the broadcast
                            channel_name (string): broadcaster's profile name
                            date (string): local date YYYY-MM-DD
                            time (string): local time HHMMSS
                            ext (string): file extension
                            title (string): title of the live broadcast
  --no-remux            Do not remux recordings into mp4/m4a after it is
                        finished.
  -k, --keep-intermediates
                        Keep the raw .ts recordings after it has been remuxed.
  --cookies COOKIES     Path to a cookies file.
  --write-chat          Save live chat into a json file.
  --write-info-json     Dump output stream information into a json file.
  --write-thumbnail     Download thumbnail into a file
  --wait                Wait until the broadcast goes live, then start
                        recording.
  --poll-interval POLL_INTERVAL
                        How many seconds between checks to see if broadcast is
                        live. Default is 5.
  --log-level {silent,error,warn,info,debug,trace}
                        Log level verbosity. Default is info.
```

## autofc2

> Monitor multiple channels at the same time, and automatically start downloading when any of them goes online

Create a file called `autofc2.json` following the example below, and place the file next to the `autofc2.py` script.

```json
{
  "default_params": {
    "quality": "3Mbps",
    "latency": "mid",
    "threads": 4,
    "outtmpl": "%(channel_name)s/%(date)s %(title)s.%(ext)s",
    "write_chat": false,
    "write_info_json": false,
    "write_thumbnail": false,
    "wait_for_live": true,
    "wait_poll_interval": 5,
    "cookies_file": null,
    "remux": true,
    "keep_intermediates": false
  },
  "channels": {
    "91544481": {
      "_name": "猫羽かりん",
      "quality": "sound",
      "write_thumbnail": true
    },
    "72364867": { "_name": "兎野さくら" },
    "40740626": { "_name": "狛江撫子" },
    "81840800": { "_name": "狼ノ宮ヒナギク" }
  }
}
```

The `default_params` object will be the parameters applied to all of the channels. Check the usage section above for more information on each parameter. Note that `wait_for_live` needs to be set to `true` for the script to work properly. You can also override the parameters per-channel. For organizational purposes, you can also write comments as arbitrary parameters. I'm using `_name` in the example above, but you can use anything as long as it doesn't conflict with the parameters.

Once configured, you can run the script:

```
python3 autofc2.py
```

If you need to change the config json, feel free to change it while the script is running. It will reload the file if it detects any changes. Note that parameters will not be updated for ongoing streams (i.e. if the script is recording a stream and you change its settings, it will continue recording with the old settings and will only apply the new configuration to future recordings).

## Notes

- FC2 does not allow multiple connections to the same stream, so you can't watch in the browser while downloading. You can instead preview the file being downloaded using `mpv` or `vlc`. Alternatively, log in with an account on your browser.
- Recording only starts from when you start the tool. This tool cannot "seek back" and record streams from the start.

## Known issues

- Tested to work under Linux. It should work on Windows, but no guarantees. If you're facing any issues on Windows, try running it under WSL.
- autofc2 will freak out over a private/paid streams.
