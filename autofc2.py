from fc2_live_dl import FC2LiveDL
import asyncio
import copy
import json

last_valid_config = None
def get_config():
    global last_valid_config
    try:
        with open('autofc2.json', 'r') as f:
            last_valid_config = json.load(f)
    except:
        print("Warning: unable to load config, using last valid one")
    return last_valid_config

def get_channels():
    config = get_config()
    return config['channels'].keys()

def get_channel_params(channel_id):
    config = get_config()
    params = config['default_params']
    params.update(config['channels'][channel_id])
    return params

def reload_channels_list(tasks):
    async def noop():
        pass

    channels = get_channels()
    for channel_id in channels:
        if channel_id not in tasks:
            tasks[channel_id] = asyncio.create_task(noop())

    for channel_id in tasks.keys():
        if channel_id not in channels:
            tasks[channel_id].cancel()

async def handle_channel(channel_id):
    params = get_channel_params(channel_id)
    async with FC2LiveDL(params) as fc2:
        await fc2.download(channel_id)

async def main():
    print("[autofc2]")

    tasks = {}
    while True:
        reload_channels_list(tasks)
        task_arr = [
            asyncio.create_task(asyncio.sleep(1))
        ]
        for channel in tasks.keys():
            if tasks[channel].done():
                tasks[channel] = asyncio.create_task(
                        handle_channel(channel)
                )
            task_arr.append(tasks[channel])

        await asyncio.wait(task_arr, return_when=asyncio.FIRST_COMPLETED)

if __name__ == '__main__':
    # Set up asyncio loop
    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(main())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
    finally:
        # Give some time for aiohttp cleanup
        loop.run_until_complete(asyncio.sleep(0.250))
        loop.close()
