'''''
PROMPT:

[- Used So Far: 0.0¢ | 0 tokens -]
'''''
import asyncio
import typing
from code_writer.CodeFile import CodeLanguage
from context import AssSound, Context, ContextSource, Step, StepFinalState, StepType
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
	
	def new_ctx(self, step_type: StepType, source: ContextSource) -> Context:
		# TODO: fix this root step bullshit to be better
		return Context(
			Step(None, step_type),
			openai_client,
			self.local_machine,
			self.config,
			source)

	async def transcribe_microphone_stop(self):
		await self.local_machine.record_microphone_stop()

	async def transcribe_microphone(self, ctx: Context):
		with ctx.step(StepType.LOCAL_RECORD) as step:
			await ctx.play_sound(AssSound.WAKE)
			audio_data = await self.local_machine.record_microphone(ctx)
			if audio_data is None:
				ctx.log("audio record cancelled")
				step.final_state = StepFinalState.NOTHING_DONE
				return None
			ctx.log(f"{audio_data.duration_seconds:.2f} seconds of audio recorded")
		
		await ctx.play_sound(AssSound.UNWAKE)

		async with speech_file_lock:
			audio_data.export(SPEECH_TEMP_FILE, format="wav")

			
			with ctx.step(StepType.TRANSCRIBE):
				spoken_text = await self.audio_api.transcribe(SPEECH_TEMP_FILE)
				ctx.log("TRANSCRIPTION: " + spoken_text)

		spoken_text = spoken_text.strip()
		
		if spoken_text == "" or spoken_text == ".":
			ctx.log("ignoring: nothing was said")
			return None
		
		return spoken_text

	async def record_thought_local(self):
		with self.new_ctx(StepType.THOUGHT_LOCAL, ContextSource.LOCAL_MACHINE) as ctx:
			self.config.reload()

			prompt_text = await self.transcribe_microphone(ctx)

			if prompt_text is None:
				return # nothing was said, so do nothing
			
			await self.run_function(ctx, "write_thought", [ prompt_text ])

	async def main_chat(self):
		self.config.reload()
		
		with self.new_ctx(StepType.ASSISTANT_LOCAL, ContextSource.LOCAL_MACHINE) as ctx:
			prompt_text = await self.transcribe_microphone(ctx)

			if prompt_text is None:
				return # nothing was said, so do nothing

			await self.prompt_assistant(ctx, prompt_text)
	
	async def run_file(self, ctx: Context, file: str = None):
		self.config.reload()
		
		with ctx.step(StepType.OBSIDIAN_RUNNER):
			if file is None:
				prompt_file = obsidian.file(self.config.run_input)
			else:
				prompt_file = obsidian.file(file)

			valid_actions = [ "run_convo", "assistant" ]

			system_prompts_root = os.path.join(obsidian.ROOT_DIR, self.config.system_prompts_dir)
			for file in os.listdir(system_prompts_root):
				filename_without_extension = os.path.splitext(file)[0]
				valid_actions.append(filename_without_extension)


			default_config = {
				"action": f"VALID_ACTIONS: {', '.join(valid_actions)}"
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
				ctx.log("Wrote default args")
				return False
			
			if prompt_file.metadata["assistant"].get("action") not in valid_actions:
				ctx.log("Invalid action given")
				return False

			ass_config = prompt_file.metadata.get("assistant", {})
			action = ass_config.get("action", default_config["action"])

			system_prompt_path = None
			if action not in [ "run_convo", "assistant" ]:
				system_prompt_path = os.path.join(system_prompts_root, f"{action}.md")

			if action == "assistant":
				prompt_text = prompt_file.content.strip()
				await self.prompt_assistant(ctx, prompt_text)
				response = "`response didnt include text`"
				if len(ctx.say_log) > 0:
					response = ctx.say_log[0]
				response = AssOutput(response, ctx.converators[0].get_token_count())
			elif action == "run_convo":
				conversator = ctx.get_conversator()
				pattern = "(?:\n|^)> (SYSTEM|USER|ASSISTANT)\n([\s\S]+?)(?=(?:\n> (?:SYSTEM|USER|ASSISTANT)|$))"
				for kind, content in re.findall(pattern, prompt_file.content):
					content = content.strip()
					if kind == "SYSTEM":
						conversator.input_system(content)
					elif kind == "USER":
						conversator.input_user(content)
					elif kind == "ASSISTANT":
						conversator.input_self(content)

				ctx.log("gpt...")
				response = await conversator.get_response()
				ctx.log(f"ASSISTANT> {response}")

				response = AssOutput(response, conversator.get_token_count())
			else:
				system_prompt_path = os.path.join(system_prompts_root, f"{action}.md")
				system_prompt_file = obsidian.file(system_prompt_path)
				system_prompt = system_prompt_file.content.strip()
				prompt_text = prompt_file.content.strip()

				conversator = ctx.get_conversator()
				conversator.input_system(system_prompt)
				conversator.input_user(prompt_text)
				response = await conversator.get_response()
				response = AssOutput(response, conversator.get_token_count())

			prompt_file.ass_output = response
			prompt_file.write()

	async def prompt_assistant(self, ctx: Context, prompt_text: str):
		self.config.reload()

		func_runner = functions.FunctionsRunner(self.config.functions_dir, ctx)

		response = await func_runner.run_prompt(prompt_text)

		if response and isinstance(response, str):
			await ctx.say(response, is_finish=True)
		
	async def code_writer(self, ctx: Context, file):
		global loaded_thing
		from code_writer import writer_entry, CodeFile
		if loaded_thing:
			reload(CodeFile)
			reload(writer_entry)
		loaded_thing = True
		with ctx.step(StepType.CODE_WRITER) as step:
			step.final_state = await writer_entry.run_thing(ctx, file)
	
	async def run_function(self, ctx: Context, name: str, args: typing.List[str]):
		ctx.log(f"Running func: {name}")
		func_runner = functions.FunctionsRunner(self.config.functions_dir, ctx)
		await func_runner.run_func(name, args)
	
	async def web_prompt(self, prompt: str):
		with self.new_ctx(StepType.WEB_ASSISTANT, ContextSource.WEB) as ctx:
			await self.prompt_assistant(ctx, prompt)
		return ctx.finish_audio_response

	async def web_thought(self, thought: str):
		with self.new_ctx(StepType.WEB_ASSISTANT, ContextSource.WEB) as ctx:
			await self.run_function(ctx, "write_thought", [ thought ])
		return ctx.finish_audio_response

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
		with self.new_ctx(StepType.ACTION_BUTTON, ContextSource.LOCAL_MACHINE) as ctx:
			await ctx.play_sound(AssSound.TASK_START)
			await self._action_button(ctx, file)

	
	async def on_startup(self):
		# result = test_thing()
		# print(result)
		# await self.run_file()
		# await self.run_function("christmas_tree", [ "off" ])
		# with self.new_ctx(StepType.ACTION_BUTTON) as ctx:
		# 	response = await self.prompt_assistant(ctx, "Write down that I'm thinking about bananas")
		# 	print("done!", response.response)
		pass
