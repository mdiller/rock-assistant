from collections import OrderedDict
import typing
import os
import re
import datetime
import traceback
import json
import inspect
from  openai.types.chat.chat_completion_message import FunctionCall
from context import Context, StepType


from obsidian import ObsidianFile, AssistantConfig
import obsidian

class AssFunctionArg():
	name: str
	description: str
	type: typing.Type
	type_name: str
	optional: bool
	def __init__(self, name, description):
		self.name = name
		self.description = description
		self.type = None
		self.type_name = None
		self.optional = False
	
	@classmethod
	def try_convert_type(cls, argtype):
		if argtype == str:
			return "string"
		else:
			return None

class AssFunction():
	name: str
	file: ObsidianFile
	exec: typing.Callable
	args: typing.List[AssFunctionArg]
	def __init__(self, file: ObsidianFile):
		self.file = file
		self.args = []
		self.exec = None
	
	def toDoc(self):
		return f"{self.name.upper()}({', '.join(map(lambda a: a.toDoc(), self.args))})"

	# deprecated
	def to_json(self):
		result = OrderedDict([
			("name", self.name),
			("description", self.description)
		])
		args = OrderedDict()
		for arg in self.args:
			args[arg.name] = OrderedDict([
				("type", arg.type_name),
				("description", arg.description)
			])
		result["parameters"] = OrderedDict([
			("type", "object"),
			("properties", args)
		])
		return result
	
	# returns False if this function is invalid / improper syntax
	def try_load(self):
		problems = []
		props = [ "name", "description", "args" ]
		for prop in props:
			if prop in self.file.metadata:
				value = self.file.metadata[prop]
				if value is None or value == "":
					problems.append(f"Property '{prop}' requires actual value")
			else:
				problems.append(f"Missing property '{prop}'")
		
		# load args from metadata
		for arg_name in self.file.metadata["args"]:
			self.args.append(AssFunctionArg(arg_name, self.file.metadata["args"][arg_name]))
		
		# load code
		code_match = re.search("```python\n([\s\S]+?)\n```", self.file.content, re.MULTILINE | re.DOTALL)
		if code_match:
			code_text = code_match.group(1)
			ns = {}
			exec(code_text, globals(), ns)
			ns_values = list(ns.values())
			if len(ns_values) < 1 or not callable(ns_values[-1]):
				problems.append("Code block is missing a function")
			else:
				self.exec = ns_values[-1]
				signature = inspect.signature(self.exec)
				args = list(signature.parameters.keys())
				if args[0] != "ctx":
					problems.append("Missing ctx arg")
				else:
					args = args[1:]
					# TODO: implement better error checking here
					# if len(args) > len(self.args):
					# 	arg_list = ", ".join(list(filter(lambda arg: arg in map(lambda a: a.name, self.args), args)))
					# 	problems.append(f"Undocumented func args: {arg_list}")
					# 	 # TODO: in future, add docs for params that dont have doc, and then make it empty so user has to fill
					# if len(args) < len(self.args):
					# 	arg_list = ", ".join(list(filter(lambda arg: arg.name in args, self.args)))
					# 	problems.append(f"Args missing from code: {arg_list}")
					
					if len(args) != len(self.args):
						problems.append(f"Args count mismatch between code and docs")
					else:
						for i in range(len(self.args)):
							param = signature.parameters[args[i]]
							if not param.default == inspect._empty:
								self.args[i].optional = True
							argtype = self.args[i].try_convert_type(param.annotation)
							if argtype:
								self.args[i].type = param.annotation
								self.args[i].type_name = argtype
							else:
								problems.append(f"Invalid param type on func arg: '{args[i]}'")
					
		else:
			problems.append("Missing a code block")

		if len(problems) == 0:
			if self.file.ass_output:
				self.file.ass_output = None
				self.file.write()
			return True
		else:
			error_str = f"ERROR LOADING {self.file.name}"
			for problem in problems:
				error_str += f"\n - {problem}"
			error_str = f"```\n{error_str}\n```"
			print(error_str)
			
			self.file.ass_output = error_str
			self.file.write()
	
	@property
	def name(self):
		return self.file.metadata["name"]
		
	@property
	def description(self):
		return self.file.metadata["description"]

class AssFunctionResult():
	success: bool
	response: str
	error: str

	@classmethod
	def create(cls, response):
		result = AssFunctionResult()
		result.success = True
		result.response = response 
		result.error = None 
		return result
	
	@classmethod
	def error(cls, error, response = "It seems I've broken!"):
		result = AssFunctionResult()
		result.success = False
		result.response = response 
		result.error = error 
		return result


class SpecialFuncArgType():
	def __init__(self, name: str, description: str):
		self.name = name
		self.description = description
	
	def __repl__(self):
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
		self.functions = []
		files = os.listdir(self.funcs_dir)
		files = [f for f in files if os.path.isfile(os.path.join(self.funcs_dir, f))]
		for file in files:
			file = ObsidianFile(os.path.join(self.funcs_dir, file))
			func = AssFunction(file)
			if func.try_load():
				self.functions.append(func)
	
		self.extra_func_arg_types = [
			SpecialFuncArgType("DayFormat", "a string representing a day, in the format YYYY-MM-DD")
		]
		self.special_variables = [
			SpecialVariable("CLIPBOARD", "The user's clipboard contents as text", lambda: "<clipdata>")
		]
	
	def get_system_prompt(self):
		template_file = os.path.join(os.path.dirname(__file__), "functions_template.md")
		with open(template_file, "r") as f:
			text = f.read()
		repl_dict = {}
		today = datetime.datetime.now() - datetime.timedelta(hours=4) # anything before 4am is part of the previous day
		repl_dict["ADDITIONAL_INFO"] = "today: " + today.strftime("%Y-%m-%d (%A)")
		repl_dict["ARG_TYPES"] = "\n".join(map(str, self.extra_func_arg_types))
		repl_dict["COMMANDS"] = "\n".join(map(lambda f: f.toDoc(), self.functions))
		for key in repl_dict:
			text = text.replace(f"{{{key}}}", repl_dict[key])
		return text
	
	def parse_func_call(self, text: str) -> FunctionCall:
		arg_pattern = f"(\"[^\"]*\"|{'|'.join(map(lambda v: v.name, self.special_variables))})"
		args_pattern = f"(?:|{arg_pattern}|{arg_pattern}(?:, ?{arg_pattern}){1, 10})"
		pattern = f"^([A-Z_]+)\({args_pattern}\)$"
		match = re.search(pattern, text)
		if not match:
			return None
		func_name = match.group(1)
		unparsed_args = []
		for i in range(2, 10):
			val = match.group(i)
			if i is None:
				break
			unparsed_args.append(val)
		# TODO: properly parse args (should have nice extensible system for this)
		return FunctionCall(func_name, unparsed_args)

	# interprets the prompt 
	async def interpret_prompt(self, prompt: str) -> FunctionCall:
		conversator = self.ctx.get_conversator()
		conversator.input_system(self.get_system_prompt())
		conversator.input_user(prompt)
		responses = await conversator.get_responses(3)
		
		for response in responses:
			func_call = self.parse_func_call(response)
			if func_call is not None:
				return func_call
		
		raise Exception("just throw this for now to see whats goin on")
		return None

	# interpret the prompt and then runs the resulting function
	async def run_prompt(self, prompt: str) -> AssFunctionResult:
		func_call = await self.interpret_prompt(prompt)
		return await self._run_func(func_call)
	
	async def run_func(self, func_name: str, args_list: typing.List) -> AssFunctionResult:
		return await self._run_func(FunctionCall(func_name, args_list))

	async def _run_func(self, func_call: FunctionCall) -> AssFunctionResult:
		func_name = func_call.func_name
		args_list = func_call.args_list
		with self.ctx.step(StepType.FUNCTION, func_name.upper() + "()"):
			args_list.insert(0, self.ctx)

			selected_func: AssFunction
			selected_func = next((func for func in self.functions if func.name == func_name), None)
			if selected_func is None:
				return AssFunctionResult.error(f"Attempted to call fictional function {func_name}")
			
			for i in range(len(selected_func.args)):
				arg = selected_func.args[i]
				if not isinstance(args_list[i], arg.type):
					try:
						args_list[i] = arg.type(args_list[i])
					except Exception as e:
						return AssFunctionResult.error(f"Un-fixable type '{type(args_list[i])}' passed to arg {arg.name} of {func_name}")

			try:
				response = selected_func.exec(*args_list)
			except Exception as e:
				# TODO: make a specific exception type that we can call to indicate bad input vs bad func calling maybe.
				error = traceback.format_exc()
				pretty_args = ", ".join(map(lambda arg: str(arg), args_list))
				error = f"ERROR ON: {selected_func.name}({pretty_args})\n```\n{error}```"
				selected_func.file.ass_output = error
				selected_func.file.write()
				return AssFunctionResult.error(error, f"Exception in function {func_name}!")
			if response is not None:
				return AssFunctionResult.create(response)
			else:
				return AssFunctionResult.create(None)

