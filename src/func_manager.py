from collections import OrderedDict
import typing
import os
import re
import datetime
import traceback
import json
import inspect
from  openai.types.chat.chat_completion_message import FunctionCall


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
	file: ObsidianFile
	exec: typing.Callable
	args: typing.List[AssFunctionArg]
	def __init__(self, file: ObsidianFile):
		self.file = file
		self.args = []
		self.exec = None
	
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

class AssFunctionRunner():
	funcs_dir: str
	functions: typing.List[AssFunction]

	def __init__(self, funcs_dir: str):
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

	async def run_json(self, function_call: FunctionCall, ctx):
		try:
			args_dict = json.loads(function_call.arguments)
		except Exception as e:
			return AssFunctionResult.error(f"Couldn't parse function args json:\n```json\n{function_call.arguments}\n```")
		
		selected_func: AssFunction
		selected_func = next((func for func in self.functions if func.name == function_call.name), None)
		if selected_func is None:
			return AssFunctionResult.error(f"Attempted to call fictional function {function_call.name}")
		
		args_list = []
		for arg in selected_func.args:
			if arg.name in args_dict:
				args_list.append(args_dict[arg.name])
			else:
				if arg.optional:
					break
				else:
					return AssFunctionResult.error(f"Missing required arg {arg.name} for function {function_call.name}")
		
		return await self.run(function_call.name, args_list, ctx)
		
	async def run(self, func_name: str, args_list: typing.List, ctx):
		args_list.insert(0, ctx)

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

