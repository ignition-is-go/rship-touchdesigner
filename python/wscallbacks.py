from touch import handleConnect, handleMessage, handleDisconnect

def onConnect(dat):
	handleConnect(dat)


def onDisconnect(dat):
	handleDisconnect(dat)
	pass

def onReceiveText(dat, rowIndex, message):
	handleMessage(dat, message)
	return

def onReceiveBinary(dat, contents):
	return

def onReceivePing(dat, contents):
	dat.sendPong(contents) # send a reply with same message
	return

def onReceivePong(dat, contents):
	return

def onMonitorMessage(dat, message):
	print(message)
	return