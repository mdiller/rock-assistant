'''''
PROMPT:

[- Used So Far: 0.1679¢ | 1130 tokens -]
'''''
import datetime
import os
import re
import traceback
from chat.conversator import ConvGenArgs
from context import Context, StepFinalState, StepType
import requests
from utils.settings import settings

async def request_help(ctx: Context, prompt: str):
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

				

