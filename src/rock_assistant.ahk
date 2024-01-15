#Persistent
#SingleInstance force
SetBatchLines, -1

Trigger_Assistant(url_end)
{
	try {
		url := "http://localhost:8080/" url_end
		oWhr := ComObjCreate("WinHttp.WinHttpRequest.5.1")
		oWhr.Open("GET", url, false)
		oWhr.SetRequestHeader("Content-Type", "application/json")
		oWhr.Send()
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

