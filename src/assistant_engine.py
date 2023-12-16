import asyncio
import conversator as conv
import asyncio
import obsidian
import openai
import datetime
import elevenlabs
import re
from obsidian import ObsidianFile, AssistantConfig, AssOutput

from utils.settings import settings
import func_manager
from local_machine import LocalMachine
from apis.audio import AudioApi

conversator = None

openai_client = openai.OpenAI(api_key=settings.openai_key)
elevenlabs.set_api_key(settings.elevenlabs_key)

speech_file_lock = asyncio.Lock()
SPEECH_TEMP_FILE = settings.resource("sounds/_speech_input.mp3")

class AssEngine():
	local_machine: LocalMachine
	audio_api: AudioApi
	config: AssistantConfig

	def __init__(self, config: AssistantConfig):
		self.local_machine = LocalMachine()
		self.audio_api = AudioApi(openai_client, config)
		self.config = config

	async def log_conversation(self, conversation):
		conversation_file = obsidian.file(self.config.conversation_log)
		conversation_file.content = conversation.to_markdown()
		conversation_file.ass_output = None
		conversation_file.write()

	async def transcribe_microphone_stop(self):
		await self.local_machine.record_microphone_stop()

	async def transcribe_microphone(self):
		audio_data = await self.local_machine.record_microphone()
		if audio_data is None:
			return None

		async with speech_file_lock:
			audio_data.export(SPEECH_TEMP_FILE, format="wav")

			print("transcribing...")
			spoken_text = await self.audio_api.transcribe(SPEECH_TEMP_FILE)
			print("TRANSCRIPTION: " + spoken_text)

		spoken_text = spoken_text.strip()
		
		if spoken_text == "" or spoken_text == ".":
			print("ignoring: nothing was said")
			return None
		
		return spoken_text


	async def main_chat(self):
		self.config.reload()

		prompt_text = await self.transcribe_microphone()

		if prompt_text is None:
			return # nothing was said, so do nothing

		response = await self.prompt_assistant(prompt_text)
		
		filename = await self.audio_api.generate_tts(response)

		await self.local_machine.play_wav(filename)
	
	async def run_file(self):
		self.config.reload()

		prompt_file = obsidian.file(self.config.run_input)

		ass_config = prompt_file.metadata.get("assistant", {})
		action = ass_config.get("action", "default")
		use_functions = ass_config.get("functions", True)
		system_prompt_path = ass_config.get("system_prompt", None)
		if system_prompt_path:
			system_prompt_path = obsidian.fix_path(system_prompt_path)

		if not system_prompt_path:
			system_prompt_path = self.config.run_system_prompt

		if action == "default":
			system_prompt_file = obsidian.file(system_prompt_path)
			system_prompt = system_prompt_file.content.strip()
			prompt_text = prompt_file.content.strip()
			response = await self.prompt_assistant(prompt_text, system_prompt, as_ass_output=True)
		elif action == "run_convo":
			func_runner = func_manager.AssFunctionRunner(self.config.functions_dir)
			if not use_functions:
				func_runner.functions = []
			
			conversator = conv.Conversator(openai_client)
			pattern = "(?:\n|^)> (SYSTEM|USER|ASSISTANT)\n([\s\S]+?)(?=(?:\n> (?:SYSTEM|USER|ASSISTANT)|$))"
			for kind, content in re.findall(pattern, prompt_file.content):
				content = content.strip()
				if kind == "SYSTEM":
					conversator.input_system(content)
				elif kind == "USER":
					conversator.input_user(content)
				elif kind == "ASSISTANT":
					conversator.input_self(content)

			print("gpt...")
			response = await conversator.get_response()
			print(f"ASSISTANT> {response}")

			await self.log_conversation(conversator)

			response = AssOutput(response, conversator.get_token_count())
		else:
			response = f"ERROR: '{action}' is not a valid assistant actionaction"

		prompt_file.ass_output = response
		prompt_file.write()

	async def prompt_assistant_tts(self, prompt_text):
		response = await self.prompt_assistant(prompt_text)
		filename = await self.audio_api.generate_tts(response)
		return filename

	async def prompt_assistant(self, prompt_text, system_prompt=None, as_ass_output=False):
		self.config.reload()

		if not system_prompt:
			system_prompt_file = obsidian.file(self.config.run_system_prompt)
			system_prompt = system_prompt_file.content
			system_prompt = system_prompt.strip()

		ctx = conv.Context(prompt_text, system_prompt)

		func_runner = func_manager.AssFunctionRunner(self.config.functions_dir)
		superconversator = conv.SuperConversator(openai_client, ctx, func_runner)

		print("gpt...")
		response = await superconversator.run()
		print(f"ASSISTANT> {response}")

		await self.log_conversation(superconversator)

		if as_ass_output:
			return AssOutput(response, superconversator.get_token_count())
		else:
			return response
	
	async def run_function(self, name, args):
		print(f"> Running func: {name}")
		func_runner = func_manager.AssFunctionRunner(self.config.functions_dir)
		result = await func_runner.run(name, args, None)
		print(result.response)
		if not result.success:
			print(result.error)
		return result.response
	
	async def run_function_tts(self, name, args):
		response = await self.run_function(name, args)
		filename = await self.audio_api.generate_tts(response)
		return filename

	async def action_button(self):
		await self.run_file()
		# await self.run_function("write_thought", [ "a thought" ])
	
	async def on_startup(self):
		# await self.run_file()
		# await self.run_function("christmas_tree", [ "off" ])
		pass