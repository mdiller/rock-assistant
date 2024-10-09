'''''
PROMPT:

[- Used So Far: 0.1383¢ | 1420 tokens -]
'''''
from aiohttp import web
from aiohttp.web_request import Request
import asyncio
from colorama import Fore
import os
from utils.settings import settings
from utils.git_watcher import GIT_MANAGER

from context import WebArgs, StepFinalState
from assistant_engine import AssEngine

from aiohttp import FormData

SERVER_PORT = 8080

FILE_MAX_SIZE_MB = 100

WEB_FILES_PATH = settings.resource("web_files")

if not os.path.exists(WEB_FILES_PATH):
	os.makedirs(WEB_FILES_PATH)

class WebServer():
	engine: AssEngine
	def __init__(self, engine: AssEngine):
		self.engine = engine
		self.git_manager = None
	
	async def setup(self):
		app = web.Application(client_max_size=FILE_MAX_SIZE_MB*1024*1024)

		app.router.add_static("/files/", WEB_FILES_PATH, name="static", show_index=False)
		app.router.add_route('GET', '/{tail:.*}', self.handle_request)
		app.router.add_route('POST', '/upload_recording', self.handle_upload)\
		
		if self.git_manager is None:
			print("starting GitManager()...")
			self.git_manager = GIT_MANAGER
			self.git_manager.start_watching()


		print("starting server...")


		# Create the server and run it
		runner = web.AppRunner(app)
		await runner.setup()
		site = web.TCPSite(runner, None, SERVER_PORT)
		await site.start()
		print(f"Server started on http://localhost:{SERVER_PORT}")

	async def handle_request(self, request: Request):
		print(f"{Fore.BLUE}WEB> {request.path_qs}{Fore.WHITE}")

		modifiers = request.query.get("modifiers")

		web_args = WebArgs(request)

		if request.path == "/mic_stop":
			await self.engine.transcribe_microphone_stop()
			return web.Response(text="done!")
		
		if self.engine.is_busy():
			print(f"{Fore.YELLOW}ignored (busy)")
			return web.Response(text="we're busy")

		filename = None
		response_code = 200

		if request.path == "/mic_start":
			if modifiers:
				if "Shift" in modifiers:
					asyncio.ensure_future(self.engine.mic_to_clipboard(web_args))
				elif modifiers == "Control":
					asyncio.ensure_future(self.engine.save_last_transcription())
			else:
				asyncio.ensure_future(self.engine.main_chat())
		if request.path == "/mic_start_thought":
			if modifiers and modifiers == "Control":
				asyncio.ensure_future(self.engine.dashboard(web_args))
			else:
				asyncio.ensure_future(self.engine.record_thought_local(web_args))
		elif request.path == "/run":
			asyncio.ensure_future(self.engine.action_button(web_args))
		elif request.path == "/prompt":
			ctx = await self.engine.web_prompt(web_args)
			filename = ctx.finish_audio_response
			if ctx.final_state != StepFinalState.SUCCESS:
				response_code = 500
		elif request.path == "/thought":
			ctx = await self.engine.web_thought(web_args)
			filename = ctx.finish_audio_response
			if ctx.final_state != StepFinalState.SUCCESS:
				response_code = 500
		elif request.path == "/dashboard":
			return web.FileResponse(filename)
		else:
			return web.Response(text="Unknown Request!", status=404)
		
		if filename:
			return web.FileResponse(filename, status=response_code)

		return web.Response(text="done!", status=response_code)

	async def handle_upload(self, request: Request):
		print(f"{Fore.BLUE}WEB_POST> {request.path_qs}{Fore.WHITE}")

		reader = await request.multipart()
		file = await reader.next()

		while file and not file.filename:
			file = await reader.next()
		
		if file is None:
			return web.Response(text="No file uploaded ya dingus", status=400)
		
		file_extension = "mp3" # file.filename.split('.')[-1] (just hardcoding this for now cuz stupid mp4 stuff)
		filepath = settings.resource(f"sounds/_uploaded.{file_extension}")
		filepath = os.path.abspath(filepath)

		with open(filepath, 'wb+') as f:
			while True:
				chunk = await file.read_chunk()  # Default chunk size is 8192 bytes
				if not chunk:
					break
				f.write(chunk)

		out_filename = await self.engine.write_thought_recording(filepath)

		return web.FileResponse(out_filename)