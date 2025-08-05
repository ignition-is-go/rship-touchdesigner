import json

def onConnect(dat):
	me.ext.RshipExt.OnRshipConnect()

def onDisconnect(dat):
	me.ext.RshipExt.OnRshipDisconnect()

def onReceiveText(dat, rowIndex, message):
	me.ext.RshipExt.OnRshipReceiveText(message)
	return

def onReceiveBinary(dat, contents):
	return

def onReceivePing(dat, contents):
	dat.sendPong(contents)
	me.ext.RshipExt.OnRshipReceivePing()

	return

def onReceivePong(dat, contents):
	me.ext.RshipExt.OnRshipReceivePing()
	return

def onMonitorMessage(dat, message):
	# print("[Rship WS]:", message)
	return

