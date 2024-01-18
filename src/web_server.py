'''''
PROMPT:

[- Used So Far: 0.0¢ | 0 tokens -]
'''''
from aiohttp import web
from aiohttp.web_request import Request
import asyncio
from colorama import Fore

from assistant_engine import AssEngine

SERVER_PORT = 8080

class WebServer():
	engine: AssEngine
	def __init__(self, engine: AssEngine):
		self.engine = engine
	
	async def setup(self):
		app = web.Application()

		app.router.add_route('GET', '/{tail:.*}', self.handle_request)
		print("starting server...")

		# Create the server and run it
		runner = web.AppRunner(app)
		await runner.setup()
		site = web.TCPSite(runner, None, SERVER_PORT)
		await site.start()
		print(f"Server started on http://localhost:{SERVER_PORT}")

	async def handle_request(self, request: Request):
		print(f"{Fore.BLUE}WEB> {request.path_qs}{Fore.WHITE}")

		if request.path == "/mic_start":
			asyncio.ensure_future(self.engine.main_chat())
		if request.path == "/mic_start_thought":
			asyncio.ensure_future(self.engine.record_thought_local())
		elif request.path == "/mic_stop":
			await self.engine.transcribe_microphone_stop()
		elif request.path == "/run":
			file = request.query.get("file")
			asyncio.ensure_future(self.engine.action_button(file))
		elif request.path == "/prompt":
			query = request.query.get("q")
			filename = await self.engine.web_prompt(query)
			return web.FileResponse(filename)
		elif request.path == "/thought":
			text = request.query.get("text")
			filename = await self.engine.web_thought(text)
			return web.FileResponse(filename)
		else:
			return web.Response(text="Unknown Request!", status=404)

		return web.Response(text="done!")