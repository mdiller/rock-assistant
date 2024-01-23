'''''
PROMPT:

[- Used So Far: 0.0¢ | 0 tokens -]
'''''
from __future__ import annotations
import asyncio
from collections import OrderedDict
import datetime
from enum import Enum
import os
import yaml
import typing
from openai import OpenAI
from apis.audio import AudioApi
from gui.gui import AssistantGui

from utils.settings import settings
from local_machine import LocalMachine
import obsidian
from utils.settings import Settings
from utils.utils import print_color

# make a thing to move the decimal place manually for me
class PreciseMoney():
	micro_cents: int
	def __init__(self, micro_cents):
		self.micro_cents = micro_cents

	# the value with the decimal shifted to the left the given number of times
	def shift_value(self, shifts: int):
		value = str(self.micro_cents)
		if shifts > len(value):
			value = ("0" * (shifts - len(value))) + value
			return "0." + value
		elif shifts == len(value):
			return "0." + value
		else:
			index = len(value) - shifts
			return value[:index] + "." + value[index:]
	
	@property
	def cent_amount(self):
		return self.shift_value(4)

	def __repr__(self):
		return f"{self.cent_amount}¢"

class AssSound(Enum):
	SUCCESS = ("success.wav")
	ERROR = ("error.wav")
	IGNORE = ("ignore.wav")
	TASK_START = ("task_start.wav")
	WAKE = ("wake.wav")
	UNWAKE = ("unwake.wav")
	def __init__(self, filename: str):
		self.filepath = settings.resource(f"sounds/{filename}")

class ContextSource(Enum):
	LOCAL_MACHINE = ("Local Machine")
	WEB = ("Web / Phone")
	def __init__(self, pretty_name: str):
		self.pretty_name = pretty_name

class StepStatus(Enum):
	RUNNING = ("Running") # step currently running
	COMPLETED = ("Completed") # step finished running fully
	STOPPED = ("Stopped") # step stopped before finishing
	def __init__(self, pretty_name: str):
		self.pretty_name = pretty_name

class StepFinalState(Enum):
	SUCCESS = ("Success", AssSound.SUCCESS, 0) # all good
	NOTHING_DONE = ("Do Nothing", AssSound.IGNORE, 1) # stopped early for a normal reason
	CHILD_STOPPED = ("Child Stopped", None, 2) # child raised a StopException, see the child for its status. for sound see child
	CHAT_ERROR = ("Chat Interpreter Error", AssSound.ERROR, 3) # chatgpt interpreter no-workie
	EXCEPTION = ("Exception", AssSound.ERROR, 4) # Exception thrown from within this step
	def __init__(self, 
			pretty_name: str, 
			sound: AssSound, 
			priority: int):
		self.pretty_name = pretty_name
		self.sound = sound
		self.priority = priority

# could use <font-awesome-icon :icon="['fas', 'user-secret']" /> as our main assistant icon
class StepType(Enum):
	ASSISTANT_LOCAL = ("Assistant",       "fas fa-user")
	THOUGHT_LOCAL = ("Record Thought",    "fas fa-lightbulb")
	ACTION_BUTTON = ("Action Button",     "fas fa-circle-play")
	WEB_ASSISTANT = ("Phone Assistant",   "fas fa-user")
	WEB_THOUGHT = ("Phone Thought",       "fas fa-lightbulb")

	CODE_WRITER = ("Code Assistant",      "fas fa-pencil")
	OBSIDIAN_RUNNER = ("Obsidian Runner", "fas fa-file-lines")

	RUNNING_CODE = ("Running Code",  "fas fa-terminal")
	FUNCTION = ("Function",          "fas fa-terminal")
	AI_CHAT = ("OpenAI Chat",        "fas fa-robot")
	LOCAL_RECORD = ("Listening",     "fas fa-microphone")
	TRANSCRIBE = ("Transcribing",    "fas fa-feather-pointed")
	TTS = ("TTS",                    "fas fa-comment-dots")
	SPEAKING = ("Speaking",          "fas fa-person-harassing")
	def __init__(self, pretty_name: str, icon: str):
		self.pretty_name = pretty_name
		self.icon = icon

class LogMessage():
	def __init__(self, text: str, timestamp: datetime.datetime = None):
		self.text = text
		self.timestamp = timestamp
		if self.timestamp is None:
			self.timestamp = datetime.datetime.now()
	
	def __repr__(self):
		return f"{self.timestamp.isoformat()} | {self.text}"

# ADD STEP DEPTH HERE
class Step():
	def __init__(self, ctx: Context, step_type: StepType, parent: 'Step' = None, name: str = None):
		self.ctx = ctx
		self.step_type = step_type
		self.parent = parent
		self.name = name
		if self.name is None:
			self.name = step_type.pretty_name
		
		self.status = StepStatus.RUNNING
		self.final_state = None
		self.time_start = datetime.datetime.now()
		self.time_end = None
		self.price = 0
		self.tokens = 0
		self.child_steps: typing.List[Step] = []

		self.logs: typing.List[LogMessage] = []
		log_message = f"Step: {step_type.pretty_name}"
		if name:
			log_message += f": {self.name}"
		self.log(log_message)
		print(log_message)
	
	def log(self, text: str):
		self.logs.append(LogMessage(text))
	
	def get_log_postfix(self):
		duration_ms = int((self.time_end - self.time_start).total_seconds() * 1000)
		items = [ f"{duration_ms:,} ms" ]
		if self.price:
			items.append(PreciseMoney(self.price).cent_amount + " cents")
		items = ", ".join(items)
		return f"[{items}]"
	
	def done(self, exc_type, exc_val, exc_tb):
		self.time_end = datetime.datetime.now()
		if exc_type is not None:
			self.status = StepStatus.STOPPED
			child_errors = list(filter(lambda s: s.final_state == StepFinalState.EXCEPTION, self.child_steps))
			if child_errors:
				self.final_state = StepFinalState.CHILD_STOPPED
			else:
				self.final_state = StepFinalState.EXCEPTION # TODO: add thing here for StopException and stopping for IGNORE etc.
		else:
			self.status = StepStatus.COMPLETED
		if self.final_state is None:
			self.final_state = StepFinalState.SUCCESS
	
	def on_ctx_finish(self, ctx: Context):
		if ctx.final_state is None or ctx.final_state.priority < self.final_state.priority:
			ctx.final_state = self.final_state
		for step in self.child_steps:
			step.on_ctx_finish(ctx)
	
	@property
	def css_id(self):
		if self.parent:
			return self.parent.css_id + "-" + self.name
		else:
			return self.name

	def toGuiJson(self, id_prefix=""):
		step_id = f"{id_prefix}{self.step_type.pretty_name}"
		child_jsons = []
		for i, step in enumerate(self.child_steps):
			child_jsons.append(step.toGuiJson(f"{step_id}-{i}"))
		classes = []
		if self.status == StepStatus.RUNNING and len(self.child_steps) == 0:
			classes.append("loading")
		if self.final_state == StepFinalState.EXCEPTION:
			classes.append("error")
		return OrderedDict({
			"id": step_id,
			"name": self.step_type.pretty_name if self.name is None else self.name,
			"icon": self.step_type.icon,
			"classes": classes,
			"child_steps": child_jsons,
		})


	def __enter__(self) -> Step:
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.done(exc_type, exc_val, exc_tb)
		self.ctx._exit_step()

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	import chat.conversator
# TODO: replace localmachine etc below with interfaces in future
class Context():
	def __init__(self, root_step: Step, openai_client: OpenAI, local_machine: LocalMachine, config: obsidian.AssistantConfig, source: ContextSource):
		self.root_step = root_step
		self.root_step.ctx = self
		self.openai_client = openai_client
		self.local_machine = local_machine
		self.current_step = self.root_step
		self.ass_config = config
		self.audio_api = AudioApi(openai_client, config)
		self.conversators: typing.List['chat.conversator.Conversator'] = []
		self.source = source
		self.final_state: StepFinalState = None
		self.target: str = None
		self.finish_audio_response: str = None
		self.say_log: typing.List[str] = []
		self.original_prompt: str = None
	
	# METHODS FOR STEPS TO USE
	def get_conversator(self) -> 'chat.conversator.Conversator':
		import chat.conversator
		conversator = chat.conversator.Conversator(self)
		self.log(f"Created conversator #{len(self.conversators)}")
		self.conversators.append(conversator)
		return conversator
	
	def log(self, text: str, color = None):
		print_color(text, color)
		self.current_step.log(text)

	async def say(self, text: str, is_finish=False):
		if len(text) > 500:
			raise Exception(f"Too many characters {len(text)} passed to tts")
		with self.step(StepType.TTS):
			self.log(f"TEXT: \"{text}\"")
			self.say_log.append(text)
			filename = await self.audio_api.generate_tts(text)
		if is_finish:
			self.finish_audio_response = filename
		await self._play_audio(filename, is_finish)
	
	async def play_sound(self, sound: AssSound):
		await self._play_audio(sound.filepath)
	
	async def _play_audio(self, filename: str, is_finish=False):
		if self.source == ContextSource.LOCAL_MACHINE:
			if is_finish:
				with self.step(StepType.SPEAKING):
					await self.local_machine.play_wav(filename, True)
			else:
				await self.local_machine.play_wav(filename, False)
	
	# STEP MANAGEMENT
	def step(self, step_type: StepType, step_name: str = None) -> Step:
		step = Step(self, step_type, self.current_step, step_name)
		self.current_step.child_steps.append(step)
		self.current_step = step
		self.update_gui()
		return step
	
	def _exit_step(self):
		self.current_step = self.current_step.parent
		self.update_gui()

	# GUI STUFF
	def update_gui(self):
		if self.source == ContextSource.LOCAL_MACHINE:
			self.local_machine.gui.update(self.toGuiJson())

	def toGuiJson(self):
		return {
			"is_done": self.final_state is not None,
			"start_time": self.root_step.time_start.isoformat(),
			"root_step": self.root_step.toGuiJson()
		}
	
	# START/END EVENTS
	def on_start(self):
		self.update_gui()
		if self.source == ContextSource.LOCAL_MACHINE:
			self.local_machine.gui.show()

	
	def on_finish(self):
		self.log("Done!")
		self.root_step.on_ctx_finish(self)
		self.log(f"Final state: {self.final_state}")
		if self.finish_audio_response is None:
			self.finish_audio_response = self.final_state.sound.filepath
			asyncio.ensure_future(self.play_sound(self.final_state.sound))
		self.update_gui()
		self.saveLog()
	
	def __enter__(self) -> 'Context':
		self.on_start()
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.root_step.done(exc_type, exc_val, exc_tb)
		self.on_finish()

	def getLogLines(self, indent_str="\t", step: Step = None, indent_level = 0) -> typing.List[LogMessage]:
		if step is None:
			# root step: do final sorting etc here
			lines = self.getLogLines(indent_str, self.root_step, indent_level)
			lines.sort(key=lambda line: line.timestamp)
			return lines
		else:
			lines = []
			# TODO: add some timing info etc to the first line in the step's log
			step_prefix = "> "
			for i, line in enumerate(step.logs):
				text_prefix = indent_str * indent_level
				text_postfix = ""
				if i == 0 and indent_level > 0:
					text_prefix = text_prefix[:0 - len(step_prefix)] + step_prefix
					text_postfix = " " + step.get_log_postfix()
				text = f"{text_prefix}{line.text}{text_postfix}"
				lines.append(LogMessage(text, line.timestamp))
			for child in step.child_steps:
				lines.extend(self.getLogLines(indent_str, child, indent_level + 1))
			return lines
		
	def getFullPrice(self, step: Step = None):
		if step is None:
			price = self.getFullPrice(self.root_step)
			return PreciseMoney(price)
		price = 0
		if step.price:
			price += step.price
		for child in step.child_steps:
			price += self.getFullPrice(child)
		return price
	
	def toMarkdown(self):
		result = ""
		timestamp = self.root_step.time_start.isoformat()
		duration = (self.root_step.time_end - self.root_step.time_start).total_seconds()
		metadata = dict(OrderedDict([
			("date", str(self.root_step.time_start.strftime('%Y-%m-%d'))),
			("timestamp", str(timestamp)),
			("duration", f"{duration:.4f}s"),
			("price", self.getFullPrice().cent_amount),
			("source", self.source.name),
			("final_state", self.final_state.name),
			("target", self.target),
			("root_step_type", self.root_step.step_type.name),
		]))
		conversators_md = []
		for i, conversator in enumerate(self.conversators):
			header = f"<div class=\"rock-assistant-out\"><span>Conversator #{i}</span><span></span></div>"
			conversators_md.append(f"{header}\n\n{conversator.to_markdown()}\n")
		conversators_md = "\n".join(conversators_md)
		log_lines = "\n".join(map(str, self.getLogLines("      ")))
		result = f"---\n{yaml.safe_dump(metadata, sort_keys=False).strip()}\n---\n"
		result += f"```\n{log_lines}\n```\n"
		result += conversators_md
		return result
	
	def saveLog(self):
		logs_dir = os.path.join(obsidian.ROOT_DIR, self.ass_config.functions_dir, "../logs")
		if not os.path.exists(logs_dir):
			os.makedirs(logs_dir)
		markdown = self.toMarkdown()
		log_filename = f"{self.root_step.time_start.strftime('%Y-%m-%d_%H-%M-%S')}_{self.root_step.step_type}.md"
		log_filepath = os.path.join(logs_dir, log_filename)
		with open(log_filepath, "w+", encoding="utf-8") as f:
			f.write(markdown)
		log_filepath = os.path.join(logs_dir, "latest_log.md")
		with open(log_filepath, "w+", encoding="utf-8") as f:
			f.write(markdown)

	


		
	



# def Context():
# 	def __init__():
