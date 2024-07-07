import asyncio
import typing
from code_writer.CodeFile import CodeLanguage
from context import AssSound, Context, ContextSource, Step, StepFinalState, StepType, WebArgs
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
import shutil

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
	current_context: Context

	def __init__(self, config: AssistantConfig):
		self.local_machine = LocalMachine()
		self.audio_api = AudioApi(openai_client, config)
		self.config = config
		self.current_context = None
		self.temp_lock = None
	
	def is_busy(self):
		if self.current_context is None:
			return False
		return self.current_context.final_state is None
	
	def new_ctx(self, step_type: StepType, source: ContextSource, step_name: str = None, web_args: WebArgs = None) -> Context:
		# TODO: fix this root step bullshit to be better
		ctx = Context(
			Step(None, step_type, name = step_name),
			openai_client,
			self.local_machine,
			self.config,
			source,
			audio_api=self.audio_api,
			web_args=web_args)
		self.current_context = ctx
		return ctx

	async def transcribe_microphone_stop(self):
		if self.temp_lock and self.temp_lock.locked():
			self.temp_lock.release()
		await self.local_machine.record_microphone_stop()

	async def transcribe_microphone(self, ctx: Context):
		with ctx.step(StepType.LOCAL_RECORD) as step:
			await ctx.play_sound(AssSound.WAKE)
			audio_data = await self.local_machine.record_microphone(ctx)
			if audio_data is None:
				ctx.log("audio record cancelled")
				step.final_state = StepFinalState.NOTHING_DONE
				return None
		
		await ctx.play_sound(AssSound.UNWAKE)

		async with speech_file_lock:
			audio_data.export(SPEECH_TEMP_FILE, format="wav")

			
			with ctx.step(StepType.TRANSCRIBE):
				spoken_text = await self.audio_api.transcribe(SPEECH_TEMP_FILE)
				ctx.log(f"TRANSCRIPTION: \"{spoken_text}\"")

		spoken_text = spoken_text.strip()
		
		if spoken_text == "" or spoken_text == ".":
			ctx.log("ignoring: nothing was said")
			return None
		
		return spoken_text

	async def write_thought_recording(self, filename):
		with self.new_ctx(StepType.THOUGHT_LOCAL, ContextSource.WEB, "Long Thought") as ctx:
			file_extension = filename.split('.')[-1]
			timestamp = datetime.datetime.now()
			attach_filename = timestamp.strftime('%Y-%m-%d_%H-%M-%S') + "." + file_extension
			attach_fullpath = os.path.join(settings.obsidian_root, "_vault/Attachments", attach_filename)
			shutil.copy(filename, attach_fullpath)

			with ctx.step(StepType.TRANSCRIBE):
				spoken_text = await self.audio_api.transcribe(filename)
				ctx.log(f"TRANSCRIPTION: \"{spoken_text}\"")

			if spoken_text is None:
				spoken_text = ""
			
			spoken_text = f"![[{attach_filename}]]\n{spoken_text}"

			await self.run_function(ctx, "write_down", [ spoken_text ])
		return ctx.finish_audio_response

	async def record_thought_local(self, web_args: WebArgs):
		with self.new_ctx(StepType.THOUGHT_LOCAL, ContextSource.LOCAL_MACHINE, web_args = web_args) as ctx:
			prompt_text = await self.transcribe_microphone(ctx)

			if prompt_text is None:
				return # nothing was said, so do nothing

			await self.run_function(ctx, "write_down", [ prompt_text ])

	async def main_chat(self):
		with self.new_ctx(StepType.ASSISTANT_LOCAL, ContextSource.LOCAL_MACHINE) as ctx:
			prompt_text = await self.transcribe_microphone(ctx)

			if prompt_text is None:
				return # nothing was said, so do nothing

			await self.prompt_assistant(ctx, prompt_text)
	
	async def run_file(self, ctx: Context, file: str = None):
		with ctx.step(StepType.OBSIDIAN_RUNNER):
			if file is None:
				prompt_file = obsidian.file(self.config.run_input)
			else:
				prompt_file = obsidian.file(file)

			special_actions = [ "run_convo", "assistant", "command" ]
			valid_actions = []
			valid_actions.extend(special_actions)

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
			if action not in special_actions:
				system_prompt_path = os.path.join(system_prompts_root, f"{action}.md")

			if action == "assistant":
				prompt_text = prompt_file.content.strip()
				await self.prompt_assistant(ctx, prompt_text)
				response = "`response didnt include text`"
				if len(ctx.say_log) > 0:
					response = ctx.say_log[0]
				response = AssOutput(response, ctx.conversators[0].get_token_count())
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
			elif action == "command":
				command = prompt_file.metadata["assistant"].get("command")
				if command:
					args = []
					content = prompt_file.content.strip()
					if content:
						args.append(content)
					await self.run_function(ctx, command, args)
					if len(ctx.say_log) == 0:
						response = AssOutput("done!")
					else:
						response = AssOutput(ctx.say_log[-1])
				else:
					response = AssOutput("specify a 'command' arg")
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
		func_runner = functions.FunctionsRunner(ctx)

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
		func_runner = functions.FunctionsRunner(ctx)
		return await func_runner.run_func(name, args)
	
	async def web_prompt(self, web_args: WebArgs):
		with self.new_ctx(StepType.WEB_ASSISTANT, ContextSource.WEB, web_args = web_args) as ctx:
			await self.prompt_assistant(ctx, web_args.text)
		return ctx.finish_audio_response

	async def web_thought(self, web_args: WebArgs):
		with self.new_ctx(StepType.WEB_ASSISTANT, ContextSource.WEB, web_args = web_args) as ctx:
			await self.run_function(ctx, "write_down", [ web_args.text ])
		return ctx.finish_audio_response

	async def mic_to_clipboard(self, web_args: WebArgs):
		do_paste = "Control" in web_args.modifiers
		step_name = "Mic To Clipboard"
		if do_paste:
			step_name += " & Paste"
		with self.new_ctx(StepType.MIC_ACTION, ContextSource.LOCAL_MACHINE, step_name, web_args = web_args) as ctx:
			text = await self.transcribe_microphone(ctx)

			if text is None:
				return # nothing was said, so do nothing
			with ctx.step(StepType.CUSTOM, "Copy To Clipboard"):
				ctx.local_machine.set_clipboard_text(text)
			
			if do_paste:
				with ctx.step(StepType.CUSTOM, "Pasting"):
					ctx.local_machine.paste_and_enter()
			
	async def save_last_transcription(self):
		with self.new_ctx(StepType.MIC_ACTION, ContextSource.LOCAL_MACHINE, "Save Last Transcription") as ctx:
			out_folder = settings.resource("saved_transcriptions")
			if not os.path.exists(out_folder):
				os.makedirs(out_folder)
			speechfile = settings.resource("sounds/_speech_input.mp3")
			out_path = os.path.join(out_folder, datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S.mp3"))
			with ctx.step(StepType.CUSTOM, "Copy File"):
				shutil.copy(speechfile, out_path)
			
			file_extension = "mp3"
			timestamp = datetime.datetime.now()
			attach_filename = timestamp.strftime('%Y-%m-%d_%H-%M-%S') + "." + file_extension
			attach_fullpath = os.path.join(settings.obsidian_root, "_vault/Attachments", attach_filename)
			shutil.copy(speechfile, attach_fullpath)
			
			spoken_text = f"![[{attach_filename}]]"

			await self.run_function(ctx, "write_down", [ spoken_text ])
		return ctx.finish_audio_response
			
	async def _action_button(self, ctx: Context, file: str = None):
		if file is None:
			raise Exception("Action button pressed not on a file")
		else:
			if CodeLanguage.is_code_file(file):
				return await self.code_writer(ctx, file)
			elif file.endswith(".md"):
				return await self.run_file(ctx, file)
			elif file.startswith("https://chatgpt.com/") or file.startswith("http://localhost:3000/c/"):
				return await self.do_voice_to_paste(ctx, file)
			else:
				raise Exception(f"Unknown file type for action button: {file}")
		# await self.run_function("write_down", [ "a thought" ])
	
	async def do_voice_to_paste(self, ctx: Context, url: str):
		text = await self.transcribe_microphone(ctx)
		if text is None:
			return # nothing was said, so do nothing
		with ctx.step(StepType.CUSTOM, "Copy To Clipboard"):
			ctx.local_machine.set_clipboard_text(text)
		
		with ctx.step(StepType.CUSTOM, "Pasting"):
			ctx.local_machine.paste_and_enter()

	async def action_button(self, web_args: WebArgs):
		file = web_args.target
		with self.new_ctx(StepType.ACTION_BUTTON, ContextSource.LOCAL_MACHINE, web_args = web_args) as ctx:
			await ctx.play_sound(AssSound.TASK_START)
			await self._action_button(ctx, file)

	async def dashboard(self, web_args: WebArgs):
		with self.new_ctx(StepType.SHOW_DASHBOARD, ContextSource.LOCAL_MACHINE, web_args = web_args) as ctx:
			if self.temp_lock:
				self.temp_lock.release()
				self.temp_lock = None
			self.temp_lock = asyncio.Lock()
			await self.temp_lock.acquire()
			with ctx.step(StepType.CUSTOM, "Get Dashboard"):
				ctx.dashboard_data["status"] = await self.run_function(ctx, "_get_dashboard_status", [])
			# wait till user is done
			await self.temp_lock.acquire()
			self.temp_lock = None

	
	async def on_startup(self):
		# result = test_thing()
		# print(result)
		# await self.run_file()
		# await self.run_function("christmas_tree", [ "off" ])
		# with self.new_ctx(StepType.ACTION_BUTTON) as ctx:
		# 	response = await self.prompt_assistant(ctx, "Write down that I'm thinking about bananas")
		# 	print("done!", response.response)
		pass
