import sys
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QDesktopWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
import asyncio
import os
import re
import json

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.html")

class GuiEvent(QEvent):
	SHOW = QEvent.Type(QEvent.registerEventType())
	HIDE = QEvent.Type(QEvent.registerEventType())
	RELOAD = QEvent.Type(QEvent.registerEventType())
	UPDATE = QEvent.Type(QEvent.registerEventType())

	def __init__(self, eventType):
		super().__init__(eventType)

def read_css_var(html, var_name):
	pattern = f"--{var_name}: (\d+)(?:s|px);"
	match = re.search(pattern, html)
	return int(match.group(1))

class AssistantGuiWindow(QMainWindow):
	def __init__(self, parent = None):
		super().__init__(parent)
		self.setWindowTitle("Assistant")
		self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
		self.setAttribute(Qt.WA_TranslucentBackground)
		
		# Set focus policy to prevent window from taking focus
		self.setFocusPolicy(Qt.NoFocus)

		# Web view
		self.web = QWebEngineView(self)
		self.web.setAttribute(Qt.WA_TranslucentBackground)
		self.web.page().setBackgroundColor(Qt.transparent)
		self.json_data = {}

		# Closetimer
		self.fade_time = 3
		self.closeTimer = QTimer(self)
		self.closeTimer.setInterval(self.fade_time * 1000)
		self.closeTimer.timeout.connect(self.checkAndClose)

		self.installEventFilter(self)
		self.reload_html()
	
	@property
	def done(self):
		return self.json_data.get("is_done")

	def checkAndClose(self):
		if self.done:
			self.hide()

	def restartCloseTimer(self):
		if self.done:
			self.closeTimer.start()
			self.web.page().runJavaScript("restart_close_timer()")
	
	# ON HOVER HANDLER
	def eventFilter(self, source, event):
		if event.type() == QEvent.HoverMove:
			self.restartCloseTimer()
			return True
		return super(AssistantGuiWindow, self).eventFilter(source, event)
	
	def reload_html(self):
		with open(TEMPLATE_PATH, "r") as f:
			html = f.read()
		width = read_css_var(html, "window-width")
		height = read_css_var(html, "window-height")
		margin = read_css_var(html, "window-margin")
		self.fade_time = read_css_var(html, "window-fade-time")

		# Set fadetimer timeout
		self.closeTimer.setInterval(self.fade_time * 1000)
		
		# Set the window size and position
		self.web.setGeometry(0, 0, width, height)
		self.setGeometry(0, 0, width, height)
		
		screen = QDesktopWidget().screenGeometry()
		self.move(screen.width() - width - margin, margin)
		# Set html
		self.web.setHtml(html)
	
	def update(self):
		serialized = json.dumps(self.json_data)
		serialized = serialized.replace('"', '\\"')
		self.restartCloseTimer()
		self.web.page().runJavaScript(f"update(JSON.parse(\"{serialized}\"))")
		
	def start(self):
		self.web.show()
	
	def customEvent(self, event: GuiEvent):
		if event.type() == GuiEvent.SHOW:
			self.show()
		elif event.type() == GuiEvent.HIDE:
			self.hide()
		elif event.type() == GuiEvent.RELOAD:
			self.reload_html()
		elif event.type() == GuiEvent.UPDATE:
			self.update()

class AssistantGui():
	def __init__(self):
		self.app = QApplication(sys.argv)
		self.window = AssistantGuiWindow()
	
	def run_till_done(self):
		timer = QTimer()
		timer.timeout.connect(lambda: None)
		timer.start(1000) # This timer is a keep-alive thing so that we can close from terminal using Ctrl+C

		self.window.start()
		self.app.exec_()

	def show(self):
		QApplication.postEvent(self.window, GuiEvent(GuiEvent.SHOW))

	def hide(self):
		QApplication.postEvent(self.window, GuiEvent(GuiEvent.HIDE))
	
	def reload(self):
		QApplication.postEvent(self.window, GuiEvent(GuiEvent.RELOAD))

	def update(self, json_data: dict):
		self.window.json_data = json_data
		QApplication.postEvent(self.window, GuiEvent(GuiEvent.UPDATE))




# Hot reload the gui.html file for easy editing
def main():
	gui = AssistantGui()

	async def main_async():
		gui.show()
		await asyncio.sleep(2)
		last_loaded = None
		while True:
			last_modified = os.path.getmtime(TEMPLATE_PATH)
			if last_modified != last_loaded:
				last_loaded = last_modified
				FAKE_DATA = {
					"start_time": "something",
					"root_step": {
						"id": "example12",
						"name": "Thing",
						"icon": "fas fa-person-running",
						"classes": [],
						"child_steps": [
							{
								"id": "example12-1",
								"name": "Step 1",
								"icon": "fas fa-microphone",
								"classes": [],
							},
							{
								"id": "example12-2",
								"name": "Step 2",
								"icon": "fas fa-pencil",
								"classes": [ "loading" ],
							}
						]
					}
				}
				print("reload!")
				# Read the contents of the file
				gui.reload()
				await asyncio.sleep(0.5)
				gui.update(FAKE_DATA)
				await asyncio.sleep(0.5)
				FAKE_DATA["root_step"]["child_steps"][1]["classes"] = []
				FAKE_DATA["root_step"]["child_steps"].append({
					"id": "example12-3",
					"name": "Step 3",
					"icon": "fab fa-python",
					"classes": [ "loading" ],
				})
				gui.update(FAKE_DATA)
			await asyncio.sleep(1)

	def run_asyncio_loop(loop: asyncio.AbstractEventLoop):
		asyncio.set_event_loop(loop)
		loop.create_task(main_async())
		loop.run_forever()

	loop = asyncio.new_event_loop()
	thread = Thread(target=run_asyncio_loop, args=(loop,))
	thread.start()

	# run the gui on the main thread
	gui.run_till_done()

if __name__ == "__main__":
	main()
