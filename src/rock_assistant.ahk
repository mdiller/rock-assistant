/*
PROMPT:

[- Used So Far: 0.0163¢ | 214 tokens -]
*/
#Persistent
#SingleInstance force
SetBatchLines, -1
#Include ..\_temp\gdip\Gdip_All.ahk
; above gdip library downloaded from https://www.autohotkey.com/boards/viewtopic.php?t=6517

print(text)
{
	logFile := "C:\dev\projects\assistant\_temp\ahk_log.txt"
	FormatTime, now,, yyyy-MM-ddTHH:mm:ss
	line := now . "." . A_MSec . "|" . text
	
	FileAppend, `n%line%, %logFile%
}

GetTarget()
{
	print("GetTarget()")
	WinGet, active_exe, ProcessName, A
		
	if ((SubStr(active_exe, -8) = "Code.exe") or (SubStr(active_exe, -12) = "Obsidian.exe")) {
		temp := ClipboardAll ; Store all clipboard contents in temp
		Clipboard := ""
		Send, ^+e ; Send Ctrl+Shift+E to run vscode/obsidian copy active filepath to clipboard
		ClipWait, 2
		result := Clipboard ; Store new clipboard contents in result
		Clipboard := temp ; Restore original clipboard contents
		return result
	}
	if ((SubStr(active_exe, -11) = "firefox.exe")) {
		temp := ClipboardAll ; Store all clipboard contents in temp
		Clipboard := ""
		Send, ^+{F12} ; Send Ctrl+Shift+E to run firefox extension copy active url to clipboard
		ClipWait, 2
		result := Clipboard ; Store new clipboard contents in result
		Clipboard := temp ; Restore original clipboard contents
		return result
	}
	return ""
}

SimpleUriEncode(text) {
    ; Replace most common URL-unsafe characters
    text := StrReplace(text, "%", "%25") ; Percent must be replaced first
    text := StrReplace(text, " ", "%20")
    text := StrReplace(text, "&", "%26")
    text := StrReplace(text, "=", "%3D")
    text := StrReplace(text, "+", "%2B")
    return text
}

Trigger_Assistant(url_end)
{
	print("Trigger_Assistant()")
	WinGet, activeWin, ID, A ; Get the active window ID
	WinGetTitle, title, ahk_id %activeWin% ; Get the title of the active window
	WinGet, exename, ProcessName, A
	
	; PROMPT
	args := {}
	args.exe := exename
	if (GetKeyState("Shift", "P")) {
		args.modifiers := "Shift"
		if (url_end == "mic_start_thought") {
			; Sleep, 50
			; Send !{PrintScreen}
			; Sleep, 50
			; args.attachment := "CLIPBOARD_IMAGE"
			args.attachment := SaveScreenshot()
		}
	}
	if (GetKeyState("Control", "P"))
		if (args.HasKey("modifiers"))
			args.modifiers .= "+Control"
		else
			args.modifiers := "Control"

	target := GetTarget()
	if (target != "") {
		args.target := target
	}

	; define the url
	url := "http://localhost:8080/" url_end
	

	; wait_paste_enter := (url_end == "mic_start" && GetKeyState("Control", "P") && GetKeyState("Shift", "P"))
	; if (wait_paste_enter) {
	; 	args.wait := "true"
	; }

	; add arguments
	if (args.Count() > 0) {
		url := url . "?"
		for key, value in args {
			encodedValue := SimpleUriEncode(value)
			url := url . key . "=" . encodedValue . "&"
		}
		url := SubStr(url, 1, StrLen(url)-1) ; Remove the last "&"
	}

	try {
		oWhr := ComObjCreate("WinHttp.WinHttpRequest.5.1")
		oWhr.Open("GET", url, false)
		oWhr.SetRequestHeader("Content-Type", "application/json")
		print("SendingWebRequest")
		oWhr.Send()
		print("WebRequestFinished")
		; MsgBox "hello"
	}
}

global not_pressing := true

*F13::
	if not_pressing
	{
		not_pressing := false
		Trigger_Assistant("run")
	}
	return

*F14::
	if not_pressing
	{
		not_pressing := false
		Trigger_Assistant("mic_start")
	}
	return


*F15::
	if not_pressing
	{
		not_pressing := false
		Trigger_Assistant("mic_start_thought")
	}
	return


*F15 up::
*F14 up::
*F13 up::
	not_pressing := true
	Trigger_Assistant("mic_stop")
	return




#NoEnv
SendMode Input
SetWorkingDir %A_ScriptDir%

; Function to take a screenshot of the currently focused window and upload it
SaveScreenshot() {
    ; Take a screenshot of the active window
    WinGet, activeHwnd, ID, A
    screenshotPath := "C:\dev\projects\assistant\_temp\screenshot.png"
    CaptureWindow(activeHwnd, screenshotPath)

    return screenshotPath
}

; ; Function to capture a window and save as an image
; CaptureWindow(hwnd, outputPath) {
;     ; Initialize GDI+
;     pToken := Gdip_Startup()
;     hTargetWnd := hwnd
;     WinGetPos, X, Y, Width, Height, ahk_id %hTargetWnd%
;     hDC := DllCall("GetWindowDC", "Ptr", hTargetWnd)
;     hGDIPGraphics := Gdip_GraphicsFromHDC(hDC)
;     hBitmap := Gdip_CreateBitmap(Width, Height)
;     Gdip_GraphicsFromImage(hBitmap)
;     Gdip_DrawImage(hBitmap, 0, 0, Width, Height)
;     Gdip_SaveBitmapToFile(hBitmap, outputPath)
;     ; Clean up resources
;     Gdip_DisposeImage(hBitmap)
;     Gdip_DeleteGraphics(hGDIPGraphics)
;     DllCall("ReleaseDC", "Ptr", hTargetWnd, "Ptr", hDC)
;     Gdip_Shutdown(pToken)
; }


; Function to capture a window and save as an image
CaptureWindow(hwnd, outputPath) {
    ; Initialize GDI+
    pToken := Gdip_Startup()
    hTargetWnd := hwnd
	; hBitmap = Gdip_BitmapFromHWND(hwnd)

    ; Get the virtual screen coordinates
    SysGet, VirtualScreenLeft, 76  ; SM_XVIRTUALSCREEN = 76
    SysGet, VirtualScreenTop, 77   ; SM_YVIRTUALSCREEN = 77

	
	; MsgBox, The position of the window is X: %VirtualScreenLeft% and Y: %VirtualScreenTop%

    ; Get the position and size of the window
    WinGetPos, X, Y, Width, Height, ahk_id %hwnd%

	
	; MsgBox, The position of the window is X: %X% and Y: %Y% w: %Width% h: %Height%
	
	; account for stupid fullscreen window logic
	if (X = -8) {
		X := X + 8
		Width := Width - 16
	}
	if (Y = -8) {
		Y := Y + 8
		Height := Height - 16
	}

    ; Adjust window coordinates based on the virtual screen's top-left corner
    X := X - VirtualScreenLeft
    Y := Y - VirtualScreenTop

	; account for stupid fullscreen window logic
	if (X = -8) {
		X := X + 8
		Width := Width - 16
	}
	if (Y = -8) {
		Y := Y + 8
		Height := Height - 16
	}

	; MsgBox, The position of the window is X: %X% and Y: %Y% w: %Width% h: %Height%


	raster:=0x40000000 + 0x00CC0020
	pBitmap:=Gdip_BitmapFromScreen(0,raster)
	pBitmap_part:=Gdip_CloneBitmapArea(pBitmap, X, Y, Width, Height)

	Gdip_SaveBitmapToFile(pBitmap_part, outputPath)
    Gdip_DisposeImage(pBitmap)
	Gdip_Shutdown(pToken)
}

