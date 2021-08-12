# fc2-live-dl

> Tool to download FC2 live streams

## Requirements

- python 3.7
- ffmpeg
- aiohttp (`pip install -r requirements.txt`)

## Usage

```
python3 fc2_live_dl.py https://live.fc2.com/<...>
```

```
usage: fc2_live_dl.py [-h]
                      [--quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}]
                      [--latency {low,high,mid}] [-o OUTPUT] [--write-chat]
                      [--write-info-json] [--write-thumbnail] [--wait]
                      [--poll-interval POLL_INTERVAL]
                      [--log-level {silent,error,warn,info,debug,trace}]
                      url

positional arguments:
  url                   A live.fc2.com URL.

optional arguments:
  -h, --help            show this help message and exit
  --quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}
                        Quality of the stream to download. Default is 3Mbps.
  --latency {low,high,mid}
                        Stream latency. Select a higher latency if
                        experiencing stability issues. Default is mid.
  -o OUTPUT, --output OUTPUT
                        Set the output filename format. Supports formatting
                        options similar to youtube-dl. Default is
                        '%(channel_id)s-%(date)s-%(title)s.%(ext)s'
                        
                        Available format options:
                            channel_id (string): ID of the broadcast
                            channel_name (string): broadcaster's profile name
                        date (string): current date and time in the format
                        YYYY-MM-DD_HHMMSS
                            ext (string): file extension
                            title (string): title of the live broadcast
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

## Notes

- FC2 does not allow multiple connections, so you can't watch in the browser while downloading. You can instead preview the file being downloaded using `mpv` or `vlc`. Alternatively, log in with an account on your browser.
- Recordings are saved as `.ts` by default. You can remux it to `mp4` using `ffmpeg -i path/to/file.ts -c copy -movflags faststart output.mp4`
