from __future__ import annotations
from enum import Enum
from context import Context, PreciseMoney, StepType
import typing
from collections import OrderedDict
import tiktoken

from openai import OpenAI
from openai.types.chat import ChatCompletion

import utils.utils as utils

class ConversatorRole(Enum):
	SYSTEM = ("system")
	USER = ("user")
	ASSISTANT = ("assistant")
	def __init__(self, data_name: str):
		self.data_name = data_name

class ConversatorMessage:
	def __init__(self, text: str, role: ConversatorRole, options: typing.List[str] = None):
		self.text = text
		self.role = role
		if options is None:
			options = [ self.text ]
		self.options = options
	
	def toJson(self):
		return {
			"role": self.role.data_name,
			"content": self.text
		}
	
	def toMarkdown(self):
		if len(self.options) > 1:
			text = ""
			for i, opt in enumerate(self.options):
				text += f"#### OPTION {i}:\n{opt}\n\n"
		else:
			text = self.text

		return f"> {self.role.data_name.upper()}\n\n{text}\n"

# TODO: add good support for serializing this and for having model as an arg for this
# arguments for the generation of new content
class ConvGenArgs():
	def __init__(self, step_name: str = None, response_count: int = 1, output_limit: int = None):
		self.step_name = step_name
		self.response_count = response_count
		self.output_limit = output_limit

class Conversator:
	def __init__(self, ctx: Context):
		self.ctx = ctx
		self.messages: typing.List[ConversatorMessage] = []
		self.token_counts = []
		self.tokens_total = 0
		self.openai_client = ctx.openai_client
		self.tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")

	def _input_message(self, role: ConversatorRole, message: str):
		self.messages.append(ConversatorMessage(message, role))

	def input_system(self, message):
		self._input_message(ConversatorRole.SYSTEM, message)

	def input_user(self, message):
		self._input_message(ConversatorRole.USER, message)

	def input_self(self, message):
		self._input_message(ConversatorRole.ASSISTANT, message)
	
	def _get_response(self, args: ConvGenArgs):
			return self.openai_client.chat.completions.create(
				model="gpt-3.5-turbo",
				messages=list(map(lambda m: m.toJson(), self.messages)),
				n=args.response_count,
				max_tokens=args.output_limit,
				timeout=30)
	
	async def get_response(self, args: ConvGenArgs = None) -> str:
		messages = await self.get_responses(args)
		return messages[0]

	async def get_responses(self, args: ConvGenArgs = None) -> typing.List[str]:
		if args is None:
			args = ConvGenArgs()
		response: ChatCompletion
		with self.ctx.step(StepType.AI_CHAT, args.step_name):
			response = await utils.run_async(lambda: self._get_response(args))
			messages = list(map(lambda c: c.message.content, response.choices))

			counter = self.get_token_count()
			tokens = counter.input_count + counter.output_count
			for message in messages:
				tokens += len(self.tokenizer.encode(message))
			self.ctx.current_step.price = counter.get_total_price().micro_cents
			self.ctx.current_step.tokens += tokens
		
		self_message = ConversatorMessage(messages[0], ConversatorRole.ASSISTANT, messages)
		self.messages.append(self_message)

		return messages
	
	def to_markdown(self):
		return "\n".join(map(lambda m: m.toMarkdown(), self.messages))
	
	def get_token_count(self):
		counter = TokenCounter()
		for message in self.messages:
			if message.role == ConversatorRole.ASSISTANT:
				counter.output_count += len(self.tokenizer.encode(message.text))
			else:
				counter.input_count += len(self.tokenizer.encode(message.text))
		return counter


# 1 micro cent is 0.000001 cents. 
# chatgpt 3.5 input is $0.001 per 1k tokens, or 1 microcent per token
# output is 2 microcents per token

class TokenCounter():
	input_count: int
	output_count: int
	def __init__(self):
		self.input_count = 0
		self.output_count = 0
	
	def get_total_price(self):
		# 1 micro cent is 0.000001 cents. 
		# chatgpt 3.5 input is $0.001 per 1k tokens, or 1 microcent per token
		# output is 2 microcents per token
		return PreciseMoney(self.input_count + (self.output_count * 2))
	
	def __repr__(self):
		price = self.get_total_price()
		return f"{price} | {self.input_count + self.output_count} tokens"
	
	def add_counter(self, counter):
		self.input_count = counter.input_count
		self.output_count = counter.output_count