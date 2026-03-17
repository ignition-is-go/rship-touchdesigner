def onConnect(dat):

	if not parent().extensionsReady:
		return
	me.ext.RshipExt.OnRshipConnect()

def onDisconnect(dat):
	me.ext.RshipExt.OnRshipDisconnect()

def onReceiveText(dat, rowIndex, message):
	me.ext.RshipExt.OnRshipReceiveText(message)
	return

def onReceiveBinary(dat, contents):
	op.RS_LOG.Debug('[Rship WS]: Ignoring binary frame; TouchDesigner executor is JSON-only')
	return

def onReceivePing(dat, contents):
	dat.sendPong(contents)
	me.ext.RshipExt.OnRshipReceivePing()

	return

def onReceivePong(dat, contents):
	me.ext.RshipExt.OnRshipReceivePing()
	return

def onMonitorMessage(dat, message):
	op.RS_LOG.Debug("[Rship WS]:", message)
	return

