# fc2-live-dl

> Tool to download FC2 live streams

## Dependencies

- ffmpeg
- requests, websockets (`pip install -r requirements.txt`)

## Usage

```
python3 fc2_live_dl.py https://live.fc2.com/<...>
```

```
usage: fc2_live_dl.py [-h] [--quality QUALITY] [--latency LATENCY] [-o OUTPUT] url

positional arguments:
  url                   A live.fc2.com URL.

optional arguments:
  -h, --help            show this help message and exit
  --quality {150Kbps,400Kbps,1.2Mbps,2Mbps,3Mbps,sound}
                        Quality of the stream to download. Default is 3Mbps.
  --latency {low,high,mid}
                        Stream latency. Select a higher latency if experiencing stability issues.
                        Default is mid.
  -o OUTPUT, --output OUTPUT
                        Set the output filename INCLUDING the extension. Supports formatting options
                        similar to youtube-dl. Default is '%(channel_id)s-%(date)s-%(title)s.ts'

                        Available format options:
                            channel_id (string): ID of the broadcast
                            channel_name (string): broadcaster's profile name
                            date (string): current date and time in the format YYYY-MM-DD_HHMMSS
                            title (string): title of the live broadcast
```

## Notes

- FC2 does not allow multiple connections, so you can't watch in the browser while downloading. You can instead preview the file being downloaded using `mpv` or `vlc`. Alternatively, log in with an account on your browser.
- Recordings are saved as `.ts` by default. You can remux it to `mp4` using `ffmpeg -i path/to/file.ts -c copy -movflags faststart output.mp4`
