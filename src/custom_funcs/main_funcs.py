'''''
PROMPT:

[- Used So Far: 0.1918¢ | 1327 tokens -]
'''''
import datetime
import os
import re
import traceback
import typing
from chat.conversator import ConvGenArgs
from code_writer.CodeFile import CodeSnippet
from context import Context, StepFinalState, StepType
import requests
from dillerbase import Dillerbase
from utils.settings import settings

async def ask_chatgpt(ctx: Context, prompt: str):
	"""Request help with dealing with the user's request"""
	conversator = ctx.get_conversator()
	conversator.input_system("Keep your responses brief, at most two sentances.")
	conversator.input_user(ctx.original_prompt)
	return await conversator.get_response(
		ConvGenArgs(output_limit=60)
	)

async def christmas_tree(ctx: Context, state: str):
	"""Turns on/off the christmas tree"""
	action = "turn_on"
	if state.lower() == "off":
		action = "turn_off"
	
	device_id = "switch.christmas_tree_switch_2"
	url = f"{settings.homeassistant_url}/api/services/switch/{action}"
	headers = {
	    "Authorization": f"Bearer {settings.homeassistant_key}",
	    "content-type": "application/json",
	}
	body = {
		"entity_id": device_id
	}
	
	response = requests.post(url, json=body, headers=headers)


async def clipboard_mod(ctx: Context, prompt_description: str):
	"""Modify my clipboard in some way. Pass the full user prompt to this command."""
	clip_text = ctx.local_machine.get_clipboard_text()
	in_file = settings.resource("cache/clipmod_input.txt")
	out_file = settings.resource("cache/clipmod_out.txt")
	out_script = settings.resource("cache/clipmod_script.py")
	
	current_dir = os.getcwd()
	in_file = os.path.relpath(in_file, start=current_dir)
	out_file = os.path.relpath(out_file, start=current_dir)

	system_prompt = f"""Write the user a python script to accomplish the given task.
- The input clipboard should be read from \"{in_file}\", and not directly from the clipboard.
- The output should be saved to \"{out_file}\". Use w+ to overwrite if it already exists.
- Read and write the input/output as utf-8
- The script should be as concise as possible.
- Your response should just include a single ```py script block
- You are allowed to use basic python libraries
Here is an example of what the input data from the clipboard could look like:
```txt
{clip_text}
```"""
	with open(in_file, "w+") as f:
		f.write(clip_text)
	conversator = ctx.get_conversator()
	conversator.input_system(system_prompt)
	conversator.input_user(f"Write a python script to do this: \"{prompt_description}\"")
	response = await conversator.get_response()
	match = re.search(f"```(?:py|python)\n(.*)\n```", response, re.MULTILINE | re.DOTALL)

	if not match:
		ctx.current_step.final_state = StepFinalState.CHAT_ERROR
		response = f"'''''\nCOULDN'T FIND CODE IN THE FOLLOWING:\n{response}\n'''''"
		with open(out_script, "w+") as f:
			f.write(response)
	else:
		code = match.group(1)
		with ctx.step(StepType.RUNNING_CODE):
			try:
				ctx.log("running code!")
				exec(code)
				with open(out_file, "r") as f:
					result = f.read()
				ctx.log("result: " + result)
				ctx.local_machine.set_clipboard_text(result)
				ctx.log("clipboard set")
			except Exception as e:
				ctx.current_step.final_state = StepFinalState.CHAT_ERROR
				traceback_str = traceback.format_exc()
				code = f"'''''\nERRORED:\n{traceback_str}\n'''''\n{code}"
				ctx.log(traceback_str)
			with open(out_script, "w+") as f:
				f.write(code)

async def repeat_me(ctx: Context, text: str):
	"""Repeats back to the user what they just said"""
	await ctx.say(text)

async def ask_database(ctx: Context, prompt: str):
	"""Ask my personal database a question. This DB has information about dota games, bike rides, skiing, and song ive listened to"""
	with Dillerbase() as db:
		system_prompt = """Write a postgreSQL query to answer the user's request. The query should be the only thing contained in the response, and should be enclosed in a markdown-style ```sql code block. After I run the query, I'll give you the results and you can format the output for me, but don't worry about that until the user asks for it.

Remember that this is how you do conversions
- ms to minutes: value_ms / (1000.0 * 60.0)
- ms to hours: value_ms / (1000.0 * 60.0 * 60.0)
- seconds to minutes: value_seconds / 60.0
- seconds to hours: value_seconds / (60.0 * 60.0)
Make sure you dont multiply by 24 or 7, unless the user is asking for a value in days or weeks.

The database you are writing this query for has schema matching the following:"""
		system_prompt += f"\n```sql\n{db.get_db_table_schema()}\n```"
		conversator = ctx.get_conversator()
		conversator.input_system(system_prompt)
		conversator.input_user(f"Write me an sql query to satisfy this prompt: \"{prompt}\"")
		responses = await conversator.get_responses(
			ConvGenArgs(
				response_count=3,
				step_name="Create Query"
			)
		)
		code_snippets: typing.List[CodeSnippet]
		code_snippets = []

		for response in responses:
			code_snippets.append(CodeSnippet.parse(response))
		
		if all(item is None for item in code_snippets):
			ctx.log(f"No valid queries found!")
			return StepFinalState.CHAT_ERROR

		successful_query = None
		result_table = None
		with ctx.step(StepType.QUERY_DATABASE):
			for i in range(len(responses)):
				if code_snippets[i] is None:
					ctx.log(f"No DB Query found for {i + 1} / {len(responses)}")
					continue # skip this one
				ctx.log(f"Running DB Query {i + 1} / {len(responses)}")
				try:
					result_table = db.query_as_table(code_snippets[i].code, lines_max=15)
					successful_query = code_snippets[i]
					break
				except Exception as e:
					ctx.log(f"DB Query Failed with exception: {e}")
		if not successful_query:
			return StepFinalState.CHAT_ERROR
		
		conversator = ctx.get_conversator()
		conversator.input_user(prompt)
		conversator.input_system(f"The postgres database has been queried via this query:\n{successful_query}\n The response to this query was:\n{result_table}\n")
		last_system_prompt = "Respond to the user's initial question in a single sentance using the provided data. Round any numbers to the nearest integer, unless the number is less than 10."
		if ctx.web_args.is_forced_text_response:
			last_system_prompt = "Respond to the user's initial question in a concise markdown format. note that tables are not supported, so make do with lists and using quotes, parenthesis, bolding, underlining, and italicizing values as best you can."
		conversator.input_system(last_system_prompt)
		response = await conversator.get_response(
			ConvGenArgs(step_name="Interpret Results")
		)
		return response
