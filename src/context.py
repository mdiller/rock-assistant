from __future__ import annotations
import datetime
from enum import Enum
import typing
from openai import OpenAI
from apis.audio import AudioApi


from local_machine import LocalMachine
from obsidian import AssistantConfig

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

class StepStatus(Enum):
	SUCCESS = ("Success")
	EXCEPTION = ("Exception")
	FAIL = ("Fail")
	IGNORE = ("Ignore")
	RUNNING = ("Running")
	def __init__(self, pretty_name: str):
		self.pretty_name = pretty_name
	
class StepType(Enum):
	ASSISTANT_LOCAL = ("Assistant")
	THOUGHT_LOCAL = ("Record Thought")
	ACTION_BUTTON = ("Action Button")

	CODE_WRITER = ("Code Assistant")
	OBSIDIAN_RUNNER = ("Obsidian Runner")

	FUNCTION = ("Function")
	AI_CHAT = ("OpenAI Chat")
	AI_INTERPRETER = ("OpenAI Chat")
	def __init__(self, pretty_name: str):
		self.pretty_name = pretty_name

class LogMessage():
	def __init__(self, text: str):
		self.text = text
		self.timestamp = datetime.datetime.now()

class Step():
	logs: typing.List[str]
	def __init__(self, step_type: StepType, parent: 'Step' = None, name: str = None):
		self.step_type = step_type
		self.parent = parent
		self.name = name
		if self.name is None:
			self.name = step_type.pretty_name
		
		self.status = StepStatus.RUNNING
		self.time_start = datetime.datetime.now()
		self.time_end = None
		self.price = 0
		self.tokens = 0

		self.logs = []
	
	def done(self):
		self.time_end = datetime.datetime.now()

class LambdaWithManager:
	def __init__(self, exit_lambda):
		if not callable(exit_lambda):
			raise ValueError("exit_lambda must be a callable")
		self.exit_lambda = exit_lambda

	def __enter__(self):
		pass

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.exit_lambda(exc_type is not None)

# TODO: replace localmachine etc below with interfaces in future
class Context():
	def __init__(self, root_step: Step, openai_client: OpenAI, local_machine: LocalMachine, config: AssistantConfig):
		self.root_step = root_step
		self.openai_client = openai_client
		self.local_machine = local_machine
		self.current_step = self.root_step
		self.ass_config = config
		self.audio_api = AudioApi(openai_client, config)
		self.converators: typing.List['chat.conversator.Conversator'] = []
	
	def get_conversator(self) -> 'chat.conversator.Conversator':
		import chat.conversator
		conversator = chat.conversator.Conversator(self)
		self.log(f"Created conversator #{len(self.converators)}")
		self.converators.append(conversator)
		return conversator
	
	def log(self, text: str):
		print(text)
		self.current_step.logs.append(LogMessage(text))
	
	async def say(self, text: str):
		filename = await self.audio_api.generate_tts(text)

		await self.local_machine.play_wav(filename)
	
	def step(self, step_type: StepType, step_name: str = None):
		self.log(f"] Entering Step: {step_type.pretty_name}")
		step = Step(step_type, self.current_step, step_name)
		self.current_step = step
		return LambdaWithManager(lambda was_exception: self._exit_step(was_exception))
	
	def _exit_step(self, was_exception: bool):
		if was_exception:
			self.current_step.status = StepStatus.EXCEPTION
		if self.current_step.status == StepStatus.RUNNING:
			self.current_step.status = StepStatus.FAIL
		self.current_step.done()
		self.current_step = self.current_step.parent
	
	def on_finish(self):
		self.root_step.done()

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		self.on_finish()
	


		
	



# def Context():
# 	def __init__():
