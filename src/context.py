'''''
PROMPT:

[- Used So Far: 0.0¢ | 0 tokens -]
'''''
from __future__ import annotations
import asyncio
from collections import OrderedDict
import datetime
from enum import Enum
import typing
from openai import OpenAI
from apis.audio import AudioApi
from gui.gui import AssistantGui

from utils.settings import settings
from local_machine import LocalMachine
from obsidian import AssistantConfig
from utils.settings import Settings

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
	ASSISTANT_LOCAL = ("Assistant",       "fas fa-user-tie")
	THOUGHT_LOCAL = ("Record Thought",    "fas fa-lightbulb")
	ACTION_BUTTON = ("Action Button",     "fas fa-circle-play")
	WEB_ASSISTANT = ("Phone Assistant",   "fas fa-user-tie")
	WEB_THOUGHT = ("Phone Thought",       "fas fa-lightbulb")

	CODE_WRITER = ("Code Assistant",      "fas fa-pencil")
	OBSIDIAN_RUNNER = ("Obsidian Runner", "fas fa-file-lines")

	FUNCTION = ("Function",          "fas fa-terminal")
	AI_CHAT = ("OpenAI Chat",        "fas fa-cat")
	AI_INTERPRETER = ("OpenAI Chat", "fas fa-brain")
	LOCAL_RECORD = ("Listening",     "fas fa-microphone")
	TRANSCRIBE = ("Transcribing",    "fas fa-feather-pointed")
	TTS = ("TTS",                    "fas fa-comment-dots")
	def __init__(self, pretty_name: str, icon: str):
		self.pretty_name = pretty_name
		self.icon = icon

class LogMessage():
	def __init__(self, text: str):
		self.text = text
		self.timestamp = datetime.datetime.now()

# ADD STEP DEPTH HERE
class Step():
	logs: typing.List[str]
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

		self.logs = []
		self.logs.append(f"] Entering Step: {step_type.pretty_name}")
		print(f"] Entering Step: {step_type.pretty_name}")
	
	def done(self, exc_type, exc_val, exc_tb):
		self.time_end = datetime.datetime.now()
		if exc_type is not None:
			self.status = StepStatus.STOPPED
			self.final_state = StepFinalState.EXCEPTION # TODO: add thing here for StopException and propogating to do StepFinalState.CHILD_STOPPED and stopping for IGNORE etc.
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
		if self.status == StepStatus.RUNNING:
			if id_prefix != "": # don't put loading on the root step
				classes.append("loading")
		if self.final_state == StepFinalState.EXCEPTION:
			classes.append("error")
		return OrderedDict({
			"id": step_id,
			"name": self.step_type.pretty_name,
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
	def __init__(self, root_step: Step, openai_client: OpenAI, local_machine: LocalMachine, config: AssistantConfig, source: ContextSource):
		self.root_step = root_step
		self.root_step.ctx = self
		self.openai_client = openai_client
		self.local_machine = local_machine
		self.current_step = self.root_step
		self.ass_config = config
		self.audio_api = AudioApi(openai_client, config)
		self.converators: typing.List['chat.conversator.Conversator'] = []
		self.source = source
		self.final_state: StepFinalState = None
		self.target: str = None
		self.finish_audio_response: str = None
		self.say_log: typing.List[str] = []
	
	def get_conversator(self) -> 'chat.conversator.Conversator':
		import chat.conversator
		conversator = chat.conversator.Conversator(self)
		self.log(f"Created conversator #{len(self.converators)}")
		self.converators.append(conversator)
		return conversator
	
	def log(self, text: str):
		print(text)
		self.current_step.logs.append(LogMessage(text))
	
	async def _play_audio(self, filename: str):
		if self.source == ContextSource.LOCAL_MACHINE:
			await self.local_machine.play_wav(filename, False)

	async def say(self, text: str, is_finish=False):
		with self.step(StepType.TTS):
			self.log(f"> SAYING: '{text}'")
			self.say_log.append(text)
			filename = await self.audio_api.generate_tts(text)
		if is_finish:
			self.finish_audio_response = filename
		await self._play_audio(filename)
	
	async def play_sound(self, sound: AssSound):
		await self._play_audio(sound.filepath)
	
	def step(self, step_type: StepType, step_name: str = None) -> Step:
		step = Step(self, step_type, self.current_step, step_name)
		self.current_step.child_steps.append(step)
		self.current_step = step
		self.update_gui()
		return step
	
	def _exit_step(self):
		self.current_step = self.current_step.parent
		self.update_gui()

	def update_gui(self):
		self.local_machine.gui.update(self.toGuiJson())

	def toGuiJson(self):
		return {
			"is_done": self.final_state is not None,
			"start_time": self.root_step.time_start.isoformat(),
			"root_step": self.root_step.toGuiJson()
		}

	# START/END EVENTS
	async def on_finish(self):
		self.log("Done!")
		self.root_step.on_ctx_finish(self)
		self.log(f"Final state: {self.final_state}")
		if self.finish_audio_response is None:
			self.finish_audio_response = self.final_state.sound.filepath
			await self.play_sound(self.final_state.sound)
		self.update_gui()
	
	async def on_start(self):
		self.update_gui()
		self.local_machine.gui.show()
		pass
	
	# "WITH" implementation
	def __enter__(self) -> 'Context':
		asyncio.ensure_future(self.on_start())
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.root_step.done(exc_type, exc_val, exc_tb)
		asyncio.ensure_future(self.on_finish())
	


		
	



# def Context():
# 	def __init__():
