import os
import openai
import functools
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

MAX_TOKENS_STORED = 3300

class Conversator:
	openai_client: OpenAI
	def __init__(self, loop, openai_client):
		self.messages = []
		self.token_counts = []
		self.tokens_total = 0
		self.loop = loop
		self.openai_client = openai_client

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

	
	async def get_response(self, functions = None):
		response = await self.loop.run_in_executor(ThreadPoolExecutor(), lambda: self._get_response(functions))
		
		message = response.choices[0].message
		if message.content is None and message.function_call:
			message = message.function_call.json()
		else:
			message = message.content
		
		self.input_self(message)
		return message

	async def get_response_raw(self, functions = None):
		response = await self.loop.run_in_executor(ThreadPoolExecutor(), lambda: self._get_response(functions))
		
		# message = response.choices[0].message
		# if message.content is None and message.function_call:
		# 	message = message.function_call.json()
		# else:
		# 	message = message.content
		# self.input_self(message)

		return response

