# me - this DAT
# 
# frame - the current frame
# state - True if the timeline is paused
# 
# Make sure the corresponding toggle is enabled in the Execute DAT.

from touch import refresh
from registry import client

def onStart():
	return

def onCreate():
	return

def onExit():
	return

def onFrameStart(frame):
	return

def onFrameEnd(frame):
	return

def onPlayStateChange(state):
	return

def onDeviceChange():
	return

def onProjectPreSave():
	return

def onProjectPostSave():
	if(client.clientId):
		refresh()
	return

	