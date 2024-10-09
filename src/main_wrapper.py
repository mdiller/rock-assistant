# background_script.py

import os
import sys
import subprocess
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem, Icon

# Get the path to the main.py file in the parent directory
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SRC_DIR)
main_script_path = os.path.join(SRC_DIR, 'main.py')
log_dir = os.path.join(ROOT_DIR, 'LOG_VAULT')
log_file_path = os.path.join(log_dir, 'wrapperlog.txt')

# Create LOG_VAULT directory if it doesn't exist
if not os.path.exists(log_dir):
	os.makedirs(log_dir)

# Global variable to track the server process
server_process = None

def create_image(width, height):
	image = Image.new('RGB', (width, height), (255, 255, 255))
	dc = ImageDraw.Draw(image)
	dc.ellipse((width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=(0, 0, 255))
	return image

def exit_action(icon, item):
	icon.stop()
	if server_process is not None:
		server_process.terminate()  # Terminate the server process
	sys.exit()

def start_server_process():
	global server_process
	with open(log_file_path, 'w+') as log_file:
		server_process = subprocess.Popen(
			["C:\Program Files\Python310\pythonw.exe", "-u", main_script_path],
			cwd=ROOT_DIR,
			stdout=log_file,
			stderr=log_file
		)

def restart_action(icon, item):
	global server_process
	print("Restarting server...")
	if server_process is not None:
		server_process.terminate()  # Terminate the existing server process
	start_server_process()


def view_log(icon, item):
	# Open the log file in the default editor
	os.startfile(log_file_path)

def watch_log(icon, item):
	# Open a new console window and run the equivalent of `tail -f` in PowerShell
	subprocess.Popen(["tail", "-f", log_file_path], creationflags=subprocess.CREATE_NEW_CONSOLE)


icon = Icon("test_icon", create_image(64, 64), "Rock Assistant", menu=pystray.Menu(
	MenuItem("Exit", exit_action),
	MenuItem("Restart Server", restart_action),
	MenuItem("Open Log", view_log),
	MenuItem("Watch Log", watch_log)
))

if __name__ == "__main__":
	print("starting wrapper")
	# Start the server initially, redirecting stdout and stderr to the log file
	start_server_process()
	icon.run()  # Start the icon without any lambda function
