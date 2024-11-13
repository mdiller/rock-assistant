import asyncio
import signal
from threading import Thread

from assistant_engine import AssEngine
from gui.gui import AssistantGui
from web_server import WebServer
from obsidian import AssistantConfig
import os
import importlib

from utils.settings import settings

config = AssistantConfig(settings.obsidian_config_path)

signal.signal(signal.SIGINT, signal.SIG_DFL)

gui = AssistantGui()

def run_custom_modules(loop: asyncio.AbstractEventLoop):
	custom_modules_dirname = "services"
	# Path to the custom modules directory
	script_dir = os.path.dirname(os.path.abspath(__file__))
	custom_modules_path = os.path.join(script_dir, custom_modules_dirname)

	for filename in os.listdir(custom_modules_path):
		if filename.endswith(".py"):
			module_name = filename[:-3]

			module = importlib.import_module(f"{custom_modules_dirname}.{module_name}")

			start_async_method = getattr(module, "START_ASYNC", None)
			if start_async_method:
				loop.create_task(start_async_method())

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
	run_custom_modules(loop)
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