import asyncio

from assistant_engine import AssEngine
from web_server import WebServer
from obsidian import AssistantConfig

from utils.settings import settings

config = AssistantConfig(settings.obsidian_config_path)

async def setup():
	engine = AssEngine(config)
	web_server = WebServer(engine)

	await web_server.setup()

	await engine.on_startup()
	# Keep the application running
	while True:
		await asyncio.sleep(3600)  # Sleep to keep the application alive

async def test():
	pass

if __name__ == '__main__':
	asyncio.run(setup())