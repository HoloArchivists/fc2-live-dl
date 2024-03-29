# fc2-live-dl

> Tool to download FC2 live streams

[![PyPI](https://img.shields.io/pypi/v/fc2-live-dl)](https://pypi.org/project/fc2-live-dl/ "PyPI")

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
- Get notifications when streams come online via
  [Apprise](https://github.com/caronc/apprise)
- Prometheus-compatible metrics

## Installation

### Using pip

To install the latest stable version:

```
pip install --upgrade fc2-live-dl
```

To install the latest development version:

```
pip install --upgrade git+https://github.com/HoloArchivists/fc2-live-dl.git#egg=fc2-live-dl
```

### Using docker

```
docker pull ghcr.io/holoarchivists/fc2-live-dl:latest
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
                   [--wait-for-quality-timeout WAIT_FOR_QUALITY_TIMEOUT]
                   [--poll-interval POLL_INTERVAL]
                   [--log-level {silent,error,warn,info,debug,trace}]
                   [--trust-env-proxy] [--dump-websocket]
                   url

positional arguments:
  url                   A live.fc2.com URL.

options:
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
  -x, --extract-audio   Generate an audio-only copy of the stream.
  --cookies COOKIES     Path to a cookies file.
  --write-chat          Save live chat into a json file.
  --write-info-json     Dump output stream information into a json file.
  --write-thumbnail     Download thumbnail into a file
  --wait                Wait until the broadcast goes live, then start
                        recording.
  --wait-for-quality-timeout WAIT_FOR_QUALITY_TIMEOUT
                        If the requested quality is not available, keep
                        retrying up to this many seconds before falling back
                        to the next best quality. Default is 15 seconds.
  --poll-interval POLL_INTERVAL
                        How many seconds between checks to see if broadcast is
                        live. Default is 5.
  --log-level {silent,error,warn,info,debug,trace}
                        Log level verbosity. Default is info.
  --trust-env-proxy     Trust environment variables for proxy settings.
  --dump-websocket      Dump all websocket communication to a file for
                        debugging

```

### Using proxies

To use a HTTP proxy, pass the `--trust-env-proxy` flag and set your proxy
settings in the `HTTP_PROXY`, `HTTPS_PROXY`, `WS_PROXY` or `WSS_PROXY`
environment variables. If not present, proxy settings are taken from the
[`~/.netrc` file](https://www.gnu.org/software/inetutils/manual/html_node/The-_002enetrc-file.html).

For more information, check
[aiohttp's documentation](https://docs.aiohttp.org/en/stable/client_advanced.html#proxy-support).

## autofc2

> Monitor multiple channels at the same time, and automatically start
> downloading when any of them goes online

```
autofc2 --config autofc2.json
```

Where the `autofc2.json` file looks like this:

```json
{
  "autofc2": {
    "log_level": "info",
    "debounce_time": 300,
    "metrics": {
      "host": "0.0.0.0",
      "port": 9090,
      "path": "/metrics"
    }
  },
  "default_params": {
    "quality": "3Mbps",
    "latency": "mid",
    "threads": 4,
    "outtmpl": "%(channel_name)s %(_en_name)s/%(date)s %(title)s.%(ext)s",
    "write_chat": false,
    "write_info_json": false,
    "write_thumbnail": false,
    "wait_for_live": true,
    "wait_for_quality_timeout": 15,
    "wait_poll_interval": 5,
    "cookies_file": null,
    "remux": true,
    "keep_intermediates": false,
    "extract_audio": true,
    "trust_env_proxy": false
  },
  "notifications": [
    {
      "url": "discord://{WebhookID}/{WebhookToken}",
      "message": "%(channel_name)s is live!\nhttps://live.fc2.com/%(channel_id)s"
    }
  ],
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

For notifications, the URL follows the
[Apprise syntax](https://github.com/caronc/apprise#supported-notifications). For
example, if you want to use Discord webhooks, use the `discord://` like so:

- Original URL: `https://discord.com/api/webhooks/12341234/abcdabcd`
- Turns into: `discord://12341234/abcdabcd`

You can find out more about the different types of notifiers and how to
configure them on
[Apprise's GitHub](https://github.com/caronc/apprise#supported-notifications).

The `message` of the notifications follow the same syntax as `outtmpl`.

Prometheus-compatible metrics is optionally configurable with `autofc2.metrics`.
If you don't want a metrics webserver, remove the `autofc2.metrics` key.

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

## Running autofc2 with Docker

You can run autofc2 using the Docker image by mounting your config json and your
output directory, as well as overriding the default `cmd` with `autofc2` like
so:

```bash
# The following mounts `./autofc2.json` into the correct location in the docker
# container, as well as an `/recordings` folder for the recordings. You'll need to
# set the `outtmpl` to something like `/recordings/%(channel_name)s ...`
docker run --rm \
  -v $(pwd)/autofc2.json:/app/autofc2.json:ro \
  -v $(pwd)/recordings:/recordings \
  -e TZ=Asia/Tokyo \
  ghcr.io/holoarchivists/fc2-live-dl:latest \
  autofc2 --config /app/autofc2.json
```

The above command runs the container in the foreground. If you want it to keep
running in the background, you can replace the `--rm` flag with `-d`. The `TZ`
environment can be set to your local timezone, and will affect the timestamps in
the logs.

**⚠️ IMPORTANT NOTE**: Make sure you set your `outtmpl` properly to match the
bind mounts (`-v`), and test that the files are properly saved to your computer.
**You will lose your recordings** if you don't configure this properly!

You can also use docker-compose to keep your config in a single file:

- Download the
  [`docker-compose.autofc2.yml`](https://raw.githubusercontent.com/HoloArchivists/fc2-live-dl/main/docker-compose.autofc2.yml)
  file into some folder, and name it `docker-compose.yml`.
- Place your `autofc2.json` in the same folder and modify the `outtmpl` so it
  starts with `/recordings/`:

  ```
  "outtmpl": "/recordings/%(channel_name)s %(_en_name)s/%(date)s %(title)s.%(ext)s"
  ```

- Run it!

  ```bash
  # Prepare the recordings directory with the right permissions
  mkdir ./recordings && chown 1000:1000 ./recordings

  # Run the thing
  docker-compose up -d

  # Check the logs
  docker-compose logs -f

  # If you wanna kill it
  docker-compose down
  ```

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
  you're facing any issues on Windows, please
  [file an issue](https://github.com/HoloArchivists/fc2-live-dl/issues/new).
- autofc2 will freak out over a private/paid streams.
- `--wait` doesn't work sometimes because FC2 would announce that the stream is
  live before the playlist is available. Use `autofc2` if you want to make sure
  streams get saved.
- When monitoring many channels with `autofc2`, if you face any 5xx errors, try
  increasing the `wait_poll_interval` to something higher.
