/*
PROMPT:

[- Used So Far: 0.0387¢ | 294 tokens -]
*/
#Persistent
#SingleInstance force
SetBatchLines, -1

print(text)
{
	logFile := "C:\dev\projects\assistant\_temp\ahk_log.txt"
	FormatTime, now,, yyyy-MM-ddTHH:mm:ss
	line := now . "." . A_MSec . "|" . text
	
	FileAppend, `n%line%, %logFile%
}

GetOpenFile()
{
	print("GetOpenFile()")
	temp := ClipboardAll ; Store all clipboard contents in temp
	Clipboard := ""
	Send, +!c ; Send Shift+Alt+C to run vscode/obsidian copy active filepath to clipboard
	ClipWait, 2
	result := Clipboard ; Store new clipboard contents in result
	Clipboard := temp ; Restore original clipboard contents
	return result
}

Trigger_Assistant(url_end)
{
	print("Trigger_Assistant()")
	WinGet, activeWin, ID, A ; Get the active window ID
    WinGetTitle, title, ahk_id %activeWin% ; Get the title of the active window

	filename := ""
    if InStr(title, "Visual Studio Code") or InStr(title, "- Obsidian") {
		filename := GetOpenFile()
    }
	try {
		url := "http://localhost:8080/" url_end
		if (filename != "") {
			url := url . "?file=" . filename
		}
		oWhr := ComObjCreate("WinHttp.WinHttpRequest.5.1")
		oWhr.Open("GET", url, false)
		oWhr.SetRequestHeader("Content-Type", "application/json")
		print("SendingWebRequest")
		oWhr.Send()
		print("WebRequestFinished")
	}
}

global not_pressing := true

; +F14::
; 	if not_pressing
; 	{
; 		not_pressing := false
; 		Trigger_Assistant("mic_start_continue")
; 	}
; 	return

F13::Trigger_Assistant("run")

F14::
	if not_pressing
	{
		not_pressing := false
		Trigger_Assistant("mic_start")
	}
	return


+F14 up::
F14 up::
	not_pressing := true
	Trigger_Assistant("mic_stop")
	return

F15::
if not_pressing
{
	not_pressing := false
	Trigger_Assistant("mic_start_thought")
}
return


+F15 up::
F15 up::
	not_pressing := true
	Trigger_Assistant("mic_stop")
	return

