import asyncio
from code_writer.CodeFile import CodeLanguage
from context import Context, Step, StepType
import chat.conversator as conv
import asyncio
import obsidian
import openai
import datetime
import elevenlabs
import re
from obsidian import ObsidianFile, AssistantConfig, AssOutput
from importlib import reload
import os

from utils.settings import settings
import chat.functions as functions
from local_machine import LocalMachine
from apis.audio import AudioApi

loaded_thing = False

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
	
	def new_ctx(self, step_type: StepType, step_name: str = None):
		return Context(
			Step(step_type, None, step_name),
			openai_client,
			self.local_machine,
			self.config)

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

	async def record_thought_local(self):
		self.config.reload()

		prompt_text = await self.transcribe_microphone()

		if prompt_text is None:
			return # nothing was said, so do nothing
		
		filename = await self.run_function_tts("write_thought", [ prompt_text ])
		await self.local_machine.play_wav(filename)

	async def main_chat(self):
		self.config.reload()
		
		with self.new_ctx(StepType.ASSISTANT_LOCAL) as ctx:
			prompt_text = await self.transcribe_microphone()

			if prompt_text is None:
				return # nothing was said, so do nothing

			response = await self.prompt_assistant(ctx, prompt_text)
			
			filename = await self.audio_api.generate_tts(response)

			await self.local_machine.play_wav(filename)
	
	async def run_file(self, ctx: Context, file: str = None):
		self.config.reload()
		
		with ctx.step(StepType.OBSIDIAN_RUNNER):
			if file is None:
				prompt_file = obsidian.file(self.config.run_input)
			else:
				prompt_file = obsidian.file(file)

			valid_actions = [ "run_convo" ]

			system_prompts_root = os.path.join(obsidian.ROOT_DIR, self.config.system_prompts_dir)
			for file in os.listdir(system_prompts_root):
				filename_without_extension = os.path.splitext(file)[0]
				valid_actions.append(filename_without_extension)


			default_config = {
				"action": f"VALID_ACTIONS: {', '.join(valid_actions)}",
				"functions": False
			}
			if prompt_file.metadata is None or prompt_file.metadata.get("assistant", None) is None:
				if prompt_file.metadata is None:
					prompt_file.metadata = {}
				prompt_file.metadata["assistant"] = {}
				for key in default_config:
					if not key in prompt_file.metadata["assistant"]:
						prompt_file.metadata["assistant"][key] = default_config[key]
				prompt_file.generate_metadata()
				prompt_file.write()
				print("Wrote default args")
				return False
			
			if prompt_file.metadata["assistant"].get("action") not in valid_actions:
				print("Invalid action given")
				return False

			ass_config = prompt_file.metadata.get("assistant", {})
			action = ass_config.get("action", default_config["action"])
			use_functions = ass_config.get("functions", default_config["functions"])

			system_prompt_path = None
			if action != "run_convo":
				system_prompt_path = os.path.join(system_prompts_root, f"{action}.md")
				action = "run"

			if action == "run":
				system_prompt_file = obsidian.file(system_prompt_path)
				system_prompt = system_prompt_file.content.strip()
				prompt_text = prompt_file.content.strip()
				response = await self.prompt_assistant(prompt_text, system_prompt, as_ass_output=True, use_functions=use_functions)
			elif action == "run_convo":
				func_runner = functions.AssFunctionRunner(self.config.functions_dir)
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

				functions = func_runner.functions
				if not use_functions:
					functions = None
				print("gpt...")
				response = await conversator.get_response(functions)
				print(f"ASSISTANT> {response}")

				await self.log_conversation(conversator)

				response = AssOutput(response, conversator.get_token_count())
			else:
				response = f"ERROR: '{action}' is not a valid assistant actionaction"

			prompt_file.ass_output = response
			prompt_file.write()

	async def prompt_assistant_tts(self, ctx: Context, prompt_text: str):
		response = await self.prompt_assistant(ctx, prompt_text)
		filename = await self.audio_api.generate_tts(response)
		return filename

	async def prompt_assistant(self, ctx: Context, prompt_text: str):
		self.config.reload()

		func_runner = functions.FunctionsRunner(self.config.functions_dir, ctx)

		response = await func_runner.run_prompt(prompt_text)

		return response
		
	async def code_writer(self, ctx: Context, file):
		global loaded_thing
		from code_writer import writer_entry, CodeFile
		if loaded_thing:
			reload(CodeFile)
			reload(writer_entry)
		loaded_thing = True
		with ctx.step(StepType.CODE_WRITER):
			return await writer_entry.run_thing(ctx, file)
	
	async def run_function(self, name, args):
		print(f"> Running func: {name}")
		func_runner = functions.FunctionsRunner(self.config.functions_dir)
		result = await func_runner.run_func(name, args, None)
		print("Response: ", result.response)
		if not result.success:
			print(result.error)
		return result.response
	
	async def run_function_tts(self, name, args):
		response = await self.run_function(name, args)
		filename = await self.audio_api.generate_tts(response)
		return filename

	async def _action_button(self, ctx: Context, file: str = None):
		if file is None:
			raise Exception("Action button pressed not on a file")
		else:
			if CodeLanguage.is_code_file(file):
				return await self.code_writer(ctx, file)
			elif file.endswith(".md"):
				return await self.run_file(ctx, file)
			else:
				raise Exception(f"Unknown file type for action button: {file}")
		# await self.run_function("write_thought", [ "a thought" ])

	async def action_button(self, file: str = None):
		await self.local_machine.play_wav(settings.resource("sounds/task_start.wav"), wait=False)
		try:
			with self.new_ctx(StepType.ACTION_BUTTON) as ctx:
				result = await self._action_button(ctx, file)
			if result == False:
				await self.local_machine.play_wav(settings.resource("sounds/ignore.wav"))
			else:
				await self.local_machine.play_wav(settings.resource("sounds/success.wav"))
		except:
			await self.local_machine.play_wav(settings.resource("sounds/error.wav"))
			raise
	
	async def on_startup(self):
		# result = test_thing()
		# print(result)
		# await self.run_file()
		# await self.run_function("christmas_tree", [ "off" ])
		with self.new_ctx(StepType.ACTION_BUTTON) as ctx:
			await self.prompt_assistant(ctx, "Write down that I'm thinking about bananas")
		pass
