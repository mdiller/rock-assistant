'''''
PROMPT:

[- Used So Far: 0.033¢ | 239 tokens -]
'''''
from collections import OrderedDict
import typing
import os
import re
import datetime
import traceback
import json
import inspect
from  openai.types.chat.chat_completion_message import FunctionCall
from chat.conversator import ConvGenArgs
from context import Context, StepFinalState, StepType
import custom_funcs
from importlib import reload

from obsidian import ObsidianFile, AssistantConfig
import obsidian

class AssFunctionArg():
	def __init__(self, name: str, description: str):
		self.name = name
		self.description = description
		self.type: typing.Type = None
		self.type_name: str = None
		self.optional: bool = False
	
	def toDoc(self):
		typestr = str(self.type).split("'")[1]
		result =  f"{self.name}: {typestr}"
		if self.optional:
			result += f" = None"
		return result

	@classmethod
	def try_convert_type(cls, argtype):
		if argtype == str:
			return "string"
		else:
			return None

class AssFunction():
	def __init__(self, func: typing.Callable):
		self.func = func
		self.name: str = func.__name__
		self.description: str = func.__doc__
		self.exec = func
		self.args: typing.List[AssFunctionArg] = []
	
	def toDoc(self):
		return f"{self.name.upper()}({', '.join(map(lambda a: a.toDoc(), self.args))}) ; {self.description}"
	
	def try_load(self):
		self.args = []
		problems = []

		if self.description is None or self.description == "":
			problems.append("missing description")
		
		signature = inspect.signature(self.func)
		args = list(signature.parameters.keys())
		if args[0] != "ctx":
			problems.append("Missing ctx arg")
		else:
			args = args[1:]
			for argname in args:
				arg = AssFunctionArg(argname, "")
				param = signature.parameters[argname]
				if not param.default == inspect._empty:
					arg.optional = True
				argtype = arg.try_convert_type(param.annotation)
				if argtype:
					arg.type = param.annotation
					arg.type_name = argtype
				else:
					problems.append(f"Invalid param type on func arg: '{argname}'")
				self.args.append(arg)
		
		if len(problems) == 0:
			return True
		else:
			error_str = f"ERROR LOADING {self.name}"
			for problem in problems:
				error_str += f"\n - {problem}"
			error_str = f"```\n{error_str}\n```"
			print(error_str)
			return False

class SpecialFuncArgType():
	def __init__(self, name: str, description: str):
		self.name = name
		self.description = description
	
	def toDoc(self):
		return f"{self.name} ; {self.description}"

class SpecialVariable():
	def __init__(self, name: str, description: str, get_value):
		self.name = name
		self.description = description
		self.get_value = get_value
	
	def toDoc(self):
		return f"{self.name} ; {self.description}"


class FunctionCall():
	def __init__(self, func_name: str, args_list: typing.List = []):
		self.func_name = func_name
		self.args_list = args_list

class FunctionsRunner():
	funcs_dir: str
	functions: typing.List[AssFunction]
	ctx: Context
	extra_func_arg_types: typing.List[SpecialFuncArgType]
	special_variables: typing.List[str]

	def __init__(self, funcs_dir: str, ctx: Context):
		self.ctx = ctx
		self.funcs_dir = obsidian.fix_path(funcs_dir)
		self.reload()
	
	# re-loads the functions
	def reload(self):
		reload(custom_funcs)
		self.functions = []
		
		for func in custom_funcs.CUSTOM_FUNCS:
			func = AssFunction(func)
			if func.try_load():
				self.functions.append(func)
	
		self.extra_func_arg_types = [
			SpecialFuncArgType("day", "a string representing a day, in the format YYYY-MM-DD")
		]
		self.special_variables = [
			# SpecialVariable("CLIPBOARD", "The user's clipboard contents as text", lambda: "<clipdata>")
		]
	
	def get_system_prompt(self):
		template_file = os.path.join(os.path.dirname(__file__), "functions_template.md")
		with open(template_file, "r") as f:
			text = f.read()
		repl_dict = {}
		today = datetime.datetime.now() - datetime.timedelta(hours=4) # anything before 4am is part of the previous day
		repl_dict["ADDITIONAL_INFO"] = "today: " + today.strftime("%Y-%m-%d (%A)")
		repl_dict["ARG_TYPES"] = "\n".join(map(lambda f: f.toDoc(), self.extra_func_arg_types))
		repl_dict["SPECIAL_VARIABLES"] = "\n".join(map(lambda f: f.toDoc(), self.special_variables))
		repl_dict["COMMANDS"] = "\n".join(map(lambda f: f.toDoc(), self.functions))
		for key in repl_dict:
			text = text.replace(f"{{{key}}}", repl_dict[key])
		return text
	
	def parse_func_call(self, text: str) -> FunctionCall:
		self.special_variables = []
		arg_pattern = f"(\"[^\"]*\"|{'|'.join(map(lambda v: v.name, self.special_variables))})"
		args_pattern = f"(?:|{arg_pattern}|{arg_pattern}(?:, ?{arg_pattern})+)"
		pattern = f"^([A-Z_]+)(?:\({args_pattern}\)|)$"
		match = re.search(pattern, text)
		if not match:
			return None
		func_name = match.group(1)
		unparsed_args = []
		# TODO: update this to be arg-based parsing
		groups = match.groups()
		for i in range(1, len(groups)):
			val = groups[i]
			if val is None:
				continue
			if val and val[0] == '"' and val[-1] == '"':
				val = val[1:-1]
			unparsed_args.append(val)
		# TODO: properly parse args (should have nice extensible system for this)
		return FunctionCall(func_name, unparsed_args)

	# interprets the prompt 
	async def interpret_prompt(self, prompt: str) -> FunctionCall:
		conversator = self.ctx.get_conversator()
		conversator.input_system(self.get_system_prompt())
		self.ctx.original_prompt = prompt
		conversator.input_user(f"Create a function call for this prompt: \"{prompt}\"")
		responses = await conversator.get_responses(
			ConvGenArgs(
				step_name="Interpret Func",
				response_count=3,
				output_limit=75)
		)
		
		for response in responses:
			func_call = self.parse_func_call(response)
			if func_call is not None:
				return func_call
		
		return FunctionCall("GIVE_UP", [])

	# interpret the prompt and then runs the resulting function
	async def run_prompt(self, prompt: str):
		func_call = await self.interpret_prompt(prompt)
		return await self._run_func(func_call)
	
	async def run_func(self, func_name: str, args_list: typing.List):
		return await self._run_func(FunctionCall(func_name, args_list))

	async def _run_func(self, func_call: FunctionCall):
		with self.ctx.step(StepType.FUNCTION, func_call.func_name.upper() + "()") as step:
			final_state = await self._run_func_internal(func_call)
			step.final_state = final_state

	async def _run_func_internal(self, func_call: FunctionCall) -> StepFinalState:
		func_name = func_call.func_name
		args_list = func_call.args_list
		args_list.insert(0, self.ctx)

		selected_func: AssFunction
		selected_func = next((func for func in self.functions if func.name.upper() == func_name.upper()), None)
		if selected_func is None:
			return StepFinalState.CHAT_ERROR # Attempted to call fictional function
		
		for i in range(len(selected_func.args)):
			arg = selected_func.args[i]
			if i != 0 and not isinstance(args_list[i], arg.type):
				try:
					args_list[i] = arg.type(args_list[i])
				except Exception as e:
					return StepFinalState.CHAT_ERROR # Un-fixable type '{type(args_list[i])}' passed to arg {arg.name} of {func_name}

		try:
			# TODO: make this so it works on async and non-async stuff
			response = selected_func.exec(*args_list)
			if inspect.iscoroutine(response):
				response = await response

		except Exception as e:
			# TODO: make a specific exception type that we can call to indicate bad input vs bad func calling maybe.
			error = traceback.format_exc()
			pretty_args = ", ".join(map(lambda arg: str(arg), args_list))
			error = f"ERROR ON: {selected_func.name}({pretty_args})\n```\n{error}```"
			selected_func.file.ass_output = error
			selected_func.file.write()
			raise
		if response is not None:
			if isinstance(response, StepFinalState):
				return response
			elif isinstance(response, str):
				await self.ctx.say(response, is_finish=True)
		else:
			return StepFinalState.SUCCESS

