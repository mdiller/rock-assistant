# git_watcher.py
import asyncio
import subprocess
import kewi

REPO_DIR = kewi.globals.Obsidian.VAULT_ROOT  # Set this to the absolute path of your git repository
SECONDS_POLL_DEFAULT = 10  # Time interval for polling the git status

class GitManager:
	def __init__(self):
		self.repo_dir = REPO_DIR
		self.is_watching = False
	
	def start_watching(self):
		if not self.is_watching:
			asyncio.create_task(self.check_poll())
			self.is_watching = True

	def status(self) -> bool:
		# Run the git status --porcelain command
		result = subprocess.run(
			["git", "status", "--porcelain"],
			cwd=self.repo_dir,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
    		creationflags=subprocess.CREATE_NO_WINDOW
		)

		# If the output contains any changes, return True
		return bool(result.stdout.strip())

	def save(self, reason: str = "default_reason"):
		commit_msg = f"AUTO_SAVE: {reason}"
		print(commit_msg)

		# Add all changes
		add_result = subprocess.run(["git", "add", "."],
			cwd=self.repo_dir,
			stdout=subprocess.DEVNULL,  # Suppress stdout
			stderr=subprocess.PIPE,     # Capture stderr
    		creationflags=subprocess.CREATE_NO_WINDOW,     
		)
		# Check for errors in git add
		if add_result.returncode != 0:
			print(f"Error running git add: {add_result.stderr.strip()}")
			return

		# Commit the changes
		commit_result = subprocess.run(["git", "commit", "-m", commit_msg],
			cwd=self.repo_dir,
			stdout=subprocess.DEVNULL,  # Suppress stdout
			stderr=subprocess.PIPE,     # Capture stderr
    		creationflags=subprocess.CREATE_NO_WINDOW,     
		)

		# Check for errors in git commit
		if commit_result.returncode != 0:
			print(f"Error running git commit: {commit_result.stderr.strip()}")

	async def check_poll(self):
		while True:
			if self.status():
				self.save(reason="polling_check")
			await asyncio.sleep(SECONDS_POLL_DEFAULT)

GIT_MANAGER = GitManager()

async def main():
	await GIT_MANAGER.check_poll()

if __name__ == "__main__":
	asyncio.run(main())