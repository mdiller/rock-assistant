import asyncio
import signal
from threading import Thread

from assistant_engine import AssEngine
from gui.gui import AssistantGui
from web_server import WebServer
from obsidian import AssistantConfig

from utils.settings import settings

config = AssistantConfig(settings.obsidian_config_path)

signal.signal(signal.SIGINT, signal.SIG_DFL)

gui = AssistantGui()

async def main_async():
	engine = AssEngine(config)
	web_server = WebServer(engine)

	engine.local_machine.gui = gui

	await web_server.setup()

	await engine.on_startup()
	# Keep the application running
	while True:
		await asyncio.sleep(3600)  # Sleep to keep the application alive

def run_asyncio_loop(loop: asyncio.AbstractEventLoop):
	asyncio.set_event_loop(loop)
	loop.create_task(main_async())
	loop.run_forever()

def main():
	loop = asyncio.new_event_loop()

	thread = Thread(target=run_asyncio_loop, args=(loop,))
	thread.start()

	# run the gui on the main thread
	gui.run_till_done()
	thread.join()
	print("hello")


if __name__ == '__main__':
	main()