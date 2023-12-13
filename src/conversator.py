import os
import openai
import functools
import asyncio
from openai import OpenAI
from  openai.types.chat import ChatCompletion
from func_manager import AssFunction, AssFunctionRunner
import typing
from collections import OrderedDict
import tiktoken
import datetime
import json
import traceback


import utils.utils as utils

MAX_TOKENS_STORED = 3300

class Conversator:
	openai_client: OpenAI
	def __init__(self, openai_client: openai.OpenAI):
		self.messages = []
		self.token_counts = []
		self.tokens_total = 0
		self.openai_client = openai_client
		self.tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")

	def _input_message(self, role, message):
		count = len(message.split(" "))
		self.messages.append({"role": role, "content": message})
		self.token_counts.append(count)
		self.tokens_total += count

		# make sure we don't go over the limit of tokens stored. delete non-system messages from beginning to allow for this.
		i = 0
		while self.tokens_total > MAX_TOKENS_STORED:
			if self.messages[i]["role"] == "system":
				i += 1
			else:
				self.tokens_total -= self.token_counts[i]
				del self.token_counts[i]
				del self.messages[i]

	def input_system(self, message):
		self._input_message("system", message)

	def input_user(self, message):
		self._input_message("user", message)

	def input_self(self, message):
		self._input_message("assistant", message)
	
	def _get_response(self, functions = None):
		if functions:
			return self.openai_client.chat.completions.create(
				model="gpt-3.5-turbo",
				messages=self.messages,
				functions=functions)
		else:
			return self.openai_client.chat.completions.create(
				model="gpt-3.5-turbo",
				messages=self.messages)

	def get_response_message(self, response: ChatCompletion):
		message = response.choices[0].message
		if response.choices[0].finish_reason == "function_call":
			func_name = message.function_call.name
			return f"FUNCTION CALL: {func_name} {message.function_call.arguments}"
		else:
			return message.content


	
	async def get_response(self, functions = None) -> str:
		response: ChatCompletion
		response = await utils.run_async(lambda: self._get_response(functions))
		
		message = self.get_response_message(response)
		self.input_self(message)
		return message

	async def get_response_raw(self, functions = None) -> ChatCompletion:
		loop = asyncio.get_event_loop()
		response: ChatCompletion
		response = await utils.run_async(lambda: self._get_response(functions))
		
		message = self.get_response_message(response)
		self.input_self(message)
		return response
	
	def to_markdown(self):
		entries = []
		for message in self.messages:
			entries.append(f"> {message['role'].upper()}\n\n{message['content']}\n")
		return "\n".join(entries)
	
	def get_token_count(self):
		counter = TokenCounter()
		for message in self.messages:
			if message["role"] == "assistant":
				counter.output_count += len(self.tokenizer.encode(message["content"]))
			else:
				counter.input_count += len(self.tokenizer.encode(message["content"]))
		return counter


# stores the state of the current conversation, which might result in multiple conversator instances
class Context():
	prompt: str
	system_prompt: str
	information: OrderedDict
	done: bool

	def __init__(self, prompt: str, system_prompt: str):
		self.prompt = prompt
		self.system_prompt = system_prompt
		today = datetime.datetime.now() - datetime.timedelta(hours=4) # anything before 4am is part of the previous day
		self.information = OrderedDict([
			("today", today.strftime("%Y-%m-%d (%A)"))
		])
		self.done = False

	def get_system_prompt(self):
		result = self.system_prompt.strip()
		result += "\n\n__CONTEXT:__\n"
		for key in self.information:
			result += f"\n{key}: {self.information[key]}"
		return result




# for handling more complex conversations involving functions. Note that typically this is 
class SuperConversator():
	error: str
	ctx: Context
	openai_client: openai.OpenAI
	conversators: typing.List[Conversator]
	func_runner: AssFunctionRunner

	def __init__(self, openai_client: openai.OpenAI, ctx: Context, func_runner: AssFunctionRunner):
		self.ctx = ctx
		self.openai_client = openai_client
		self.func_runner = func_runner
		self.conversators = []
		self.error = None
	
	def get_funcs_json(self):
		return list(map(lambda func: func.to_json(), self.func_runner.functions))

	def next_conversator(self):
		conversator = Conversator(self.openai_client)
		conversator.input_system(self.ctx.get_system_prompt())
		conversator.input_user(self.ctx.prompt)
		self.conversators.append(conversator)
		return conversator
	

	# runs the conversator until done, and returns a single string result which is the final response
	async def run(self):
		try:
			while not self.ctx.done:
				conversator = self.next_conversator()
				# TODO: funcs should be a thing the conversator holds, not a thing passed in on a response request
				response = await conversator.get_response_raw(self.get_funcs_json())
				response = response.choices[0]

				if response.finish_reason == "function_call":
					result = await self.func_runner.run_json(response.message.function_call, self.ctx)
					if result.success:
						if result.response is None:
							# TODO: implement info gathering funcs here
							raise Exception("IMPLEMENT INFO-GATHERING FUNCS HERE")
						else:
							self.ctx.done = True
							return result.response
					else:
						self.error = result.error
						return result.response
				else:
					self.ctx.done = True
					return response.message.content
		except Exception as e:
			self.error = traceback.format_exc()
			print(self.error)
			return "Whoops, I seem to have broken!"

	def to_markdown(self):
		result = ""
		for i in range(len(self.conversators)):
			result += F"# CONVO NUMBER {i + 1}:\n"
			result += f"`{self.get_token_count()}`\n\n"
			result += self.conversators[i].to_markdown()
		if self.error:
			result += "#### ERROR:\n"
			result += f"```\n{self.error}\n```"
		return result
	
	def get_token_count(self):
		counter = TokenCounter()
		for convo in self.conversators:
			counter.add_counter(convo.get_token_count())
		return counter


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
	
	def __repr__(self):
		cent_amount = self.shift_value(4)
		return f"{cent_amount}¢"

# 1 micro cent is 0.000001 cents. 
# chatgpt 3.5 input is $0.001 per 1k tokens, or 1 microcent per token
# output is 2 microcents per token

class TokenCounter():
	input_count: int
	output_count: int
	total_price: PreciseMoney
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