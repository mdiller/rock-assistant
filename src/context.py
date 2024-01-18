'''''
PROMPT:

[- Used So Far: 0.0¢ | 0 tokens -]
'''''
from __future__ import annotations
import asyncio
import datetime
from enum import Enum
import typing
from openai import OpenAI
from apis.audio import AudioApi

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
	
class StepType(Enum):
	ASSISTANT_LOCAL = ("Assistant")
	THOUGHT_LOCAL = ("Record Thought")
	ACTION_BUTTON = ("Action Button")
	WEB_ASSISTANT = ("Phone Assistant")
	WEB_THOUGHT = ("Phone Thought")

	CODE_WRITER = ("Code Assistant")
	OBSIDIAN_RUNNER = ("Obsidian Runner")

	FUNCTION = ("Function")
	AI_CHAT = ("OpenAI Chat")
	AI_INTERPRETER = ("OpenAI Chat")
	LOCAL_RECORD = ("Listening")
	TRANSCRIBE = ("Transcribing")
	TTS = ("TTS")
	def __init__(self, pretty_name: str):
		self.pretty_name = pretty_name

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
			step.on_ctx_finish()


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
		self.last_played_audio_file: str = None
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
		self.last_played_audio_file = filename
		if self.source == ContextSource.LOCAL_MACHINE:
			await self.local_machine.play_wav(filename, False)

	async def say(self, text: str):
		with self.step(StepType.TTS):
			self.log(f"> SAYING: '{text}'")
			self.say_log.append(text)
			filename = await self.audio_api.generate_tts(text)
		await self._play_audio(filename)
	
	async def play_sound(self, sound: AssSound):
		await self._play_audio(sound.filepath)
	
	def step(self, step_type: StepType, step_name: str = None) -> Step:
		step = Step(self, step_type, self.current_step, step_name)
		self.current_step = step
		return step
	
	def _exit_step(self):
		self.current_step = self.current_step.parent

	def on_finish(self):
		self.log("Done!")
		self.root_step.on_ctx_finish(self)
		self.log(f"Final state: {self.final_state}")
		if self.last_played_audio_file is None:
			self.last_played_audio_file = self.final_state.sound.filepath
			asyncio.ensure_future(self.play_sound(self.final_state.sound))

	def __enter__(self) -> 'Context':
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.root_step.done(exc_type, exc_val, exc_tb)
		self.on_finish()
	


		
	



# def Context():
# 	def __init__():
