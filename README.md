# fc2-live-dl

> Tool to download FC2 live streams

## Requirements

- Python 3.8
- ffmpeg

## Features

- Wait for a stream to start and automatically start recording
- Save comment/chat logs
- Authenticate with cookies (Netscape format, same one used with youtube-dl)
- Remux recordings to .mp4/.m4a after it's done
- Continuously monitor multiple streams in parallel and automatically start
  downloading when any of them goes online

## Installation

```
pip install fc2-live-dl
```

## Usage

```
fc2-live-dl https://live.fc2.com/<...>
```

```
usage: fc2-live-dl [-h] [-v]
                   [--quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}]
                   [--latency {low,high,mid}] [--threads THREADS] [-o OUTPUT]
                   [--no-remux] [-k] [-x] [--cookies COOKIES] [--write-chat]
                   [--write-info-json] [--write-thumbnail] [--wait]
                   [--poll-interval POLL_INTERVAL]
                   [--log-level {silent,error,warn,info,debug,trace}]
                   [--dump-websocket]
                   url

positional arguments:
  url                   A live.fc2.com URL.

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  --quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}
                        Quality of the stream to download. Default is 3Mbps.
  --latency {low,high,mid}
                        Stream latency. Select a higher latency if experiencing
                        stability issues. Default is mid.
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
  -x, --extract-audio   Generate an audio-only copy of the stream.
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
  --dump-websocket      Dump all websocket communication to a file for
                        debugging
```

## autofc2

> Monitor multiple channels at the same time, and automatically start
> downloading when any of them goes online

```
autofc2 --config autofc2.json
```

Where the `autofc2.json` file looks like this:

```json
{
  "default_params": {
    "quality": "3Mbps",
    "latency": "mid",
    "threads": 4,
    "outtmpl": "%(channel_name)s %(_en_name)s/%(date)s %(title)s.%(ext)s",
    "write_chat": false,
    "write_info_json": false,
    "write_thumbnail": false,
    "wait_for_live": true,
    "wait_poll_interval": 5,
    "cookies_file": null,
    "remux": true,
    "keep_intermediates": false,
    "extract_audio": true
  },
  "channels": {
    "91544481": {
      "_en_name": "Necoma Karin",
      "quality": "sound",
      "write_thumbnail": true
    },
    "72364867": { "_en_name": "Uno Sakura" },
    "40740626": { "_en_name": "Komae Nadeshiko" },
    "81840800": { "_en_name": "Ronomiya Hinagiku" }
  }
}
```

The `default_params` object will be the parameters applied to all of the
channels. Check the usage section above for more information on each parameter.
Note that `wait_for_live` needs to be set to `true` for the script to work
properly. You can also override the parameters per-channel.

Arbitrary parameters can be specified by prefixing them with `_`, and will be
accessible in `outtmpl`. This is useful for specifying custom filenames just
like in the example above. In the example I'm using `_en_name`, but you can use
anything as long as it starts with `_`.

**NOTE Windows users**: When specifying a file path (e.g. for cookies) in the
json, double up your backslashes, for example:
`"cookies_file": "C:\\Documents\\cookies.txt"`.

Once configured, you can run the script:

```
autofc2 --config autofc2.json
```

If you need to change the config json, feel free to change it while the script
is running. It will reload the file if it detects any changes. Note that
parameters will not be updated for ongoing streams (i.e. if the script is
recording a stream and you change its settings, it will continue recording with
the old settings and will only apply the new configuration to future
recordings).

## Notes

- FC2 does not allow multiple connections to the same stream, so you can't watch
  in the browser while downloading. You can instead preview the file being
  downloaded using `mpv` or `vlc`. Alternatively, log in with an account on your
  browser.
- Recording only starts from when you start the tool. This tool cannot "seek
  back" and record streams from the start.
- If you can't run `fc2-live-dl` or `autofc2`, try uninstalling and reinstalling
  with `pip uninstall fc2-live-dl`.

## Known issues

- Tested to work under Linux. It should work on Windows, but no guarantees. If
  you're facing any issues on Windows, try running it under WSL.
- autofc2 will freak out over a private/paid streams.
- `--wait` doesn't work sometimes because FC2 would announce that the stream is
  live before the playlist is available. Use `autofc2` if you want to make sure
  streams get saved.
- When monitoring many channels with `autofc2`, if you face any 5xx errors, try
  increasing the `wait_poll_interval` to something higher.
