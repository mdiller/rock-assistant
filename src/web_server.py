'''''
PROMPT:

[- Used So Far: 0.1383¢ | 1420 tokens -]
'''''
import json
import re
from aiohttp import web
from aiohttp.web_request import Request
import asyncio
from colorama import Fore
import os
from utils.settings import settings
import kewi

import traceback
import importlib
# from kewi.web_backend.web_server import KewiWebBackend

from context import WebArgs, StepFinalState
from assistant_engine import AssEngine

from aiohttp import FormData

SERVER_PORT = 8080

FILE_MAX_SIZE_MB = 100

WEBJSON_PREFIX = "webjson.json_"

WEB_FILES_PATH = settings.resource("web_files")

if not os.path.exists(WEB_FILES_PATH):
	os.makedirs(WEB_FILES_PATH)

class WebServer():
	engine: AssEngine
	def __init__(self, engine: AssEngine):
		# self.kewi_web_backend = KewiWebBackend()
		self.engine = engine
		self.git_manager = None
	
	async def set_cors_headers(self, request, response):
		# Check if the request's origin is localhost with any port
		origin = request.headers.get('Origin')
		if response is None:
			print("INSERTING OK RESPONSE CUZ STUPID RESPONSE IS NONE")
			response = web.Response(status=200)
		if origin and re.match(r"http://localhost:\d+", origin):
			response.headers['Access-Control-Allow-Origin'] = origin
			response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
			response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
			response.headers['Access-Control-Allow-Credentials'] = 'true'
		return response
			

	async def cors_middleware_factory(self, app, handler):
		async def cors_middleware(request):
			# Process the request and get the response from the next handler
			response = await handler(request)
			response = await self.set_cors_headers(request, response)
			return response
		return cors_middleware
	
	# catch-all handler for options shit
	async def handle_options(self, request: Request):
		response = web.Response(status=200)
		response = await self.set_cors_headers(request, response)
		return response

	async def setup(self):
		app = web.Application(client_max_size=FILE_MAX_SIZE_MB*1024*1024)

		app = web.Application(middlewares=[self.cors_middleware_factory])

		app.router.add_static("/files/", WEB_FILES_PATH, name="static", show_index=False)
		app.router.add_route('GET', '/kewi/{endpoint}/{target:.*}', self.handle_kewi)
		app.router.add_route('GET', '/kewi/{endpoint}', self.handle_kewi)
		app.router.add_route('GET', '/readjson/{jsonname}', self.handle_readjson)
		app.router.add_route('POST', '/writejson/{jsonname}', self.handle_writejson)
		app.router.add_route('GET', '/{tail:.*}', self.handle_request)
		app.router.add_route('POST', '/upload_recording', self.handle_upload)
		app.router.add_route('OPTIONS', '/{tail:.*}', self.handle_options)

		print("starting server...")

		# Create the server and run it
		runner = web.AppRunner(app)
		await runner.setup()
		site = web.TCPSite(runner, None, SERVER_PORT)
		await site.start()
		print(f"Server started on http://localhost:{SERVER_PORT}")
		
		# Keep the application running
		while True:
			await asyncio.sleep(3600)  # Sleep to keep the application alive

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
		ctx = None

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
		
		if web_args.is_forced_text_response and ctx is not None:
			response_text = "ERROR: NOTHING IN ctx.say_log"
			if len(ctx.say_log) > 0:
				response_text = ctx.say_log[-1]
			return web.Response(text=response_text, status=response_code)

		if filename:
			return web.FileResponse(filename, status=response_code)

		return web.Response(text="done!", status=response_code)

	async def handle_readjson(self, request: Request):
		print(f"{Fore.BLUE}WEB_POST> {request.path_qs}{Fore.WHITE}")
		uri = f"{WEBJSON_PREFIX}{request.match_info.get('jsonname')}"
		data = kewi.cache.get(uri, "json")
		return web.json_response(data)

	async def handle_writejson(self, request: Request):
		print(f"{Fore.BLUE}WEB_POST> {request.path_qs}{Fore.WHITE}")
		uri = f"{WEBJSON_PREFIX}{request.match_info.get('jsonname')}"
		data = await request.json()
		filename = kewi.cache.new(uri, "json")
		with open(filename, "w+") as f:
			f.write(json.dumps(data, indent="\t"))

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

	async def handle_kewi(self, request: Request):
		print(f"{Fore.BLUE}WEB> {request.path_qs}{Fore.WHITE}")
		try:
			module = importlib.import_module("kewi.web_backend.web_server")
			importlib.reload(module)
			kewi_web_backend = module.KewiWebBackend()
			return await kewi_web_backend.handle_request(request)

			# return await self.kewi_web_backend.handle_request(endpoint, request)
		except Exception as e:
			error_message = str(e)
			stack_trace = traceback.format_exc()
			response_message = f"ERROR: {error_message}:\nSTACK TRACE:\n{stack_trace}"
			return web.Response(text=response_message, status=500)

