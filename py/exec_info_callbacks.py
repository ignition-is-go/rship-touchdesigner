# me - this DAT.
# webClientDAT - The connected Web Client DAT
# statusCode - The status code of the response, formatted as a dictionary with two key-value pairs: 'code', 'message'.
# headerDict - The header of the response from the server formatted as a dictionary. Only sent once when streaming.
# data - The data of the response
# id - The request's unique identifier


def onConnect(webClientDAT, id):
	me.parent().ext.RshipExt.OnExecInfoClientConnect(id)
	return
	
def onDisconnect(webClientDAT, id):
	me.parent().ext.RshipExt.OnExecInfoClientDisconnect(id)
	return

def onResponse(webClientDAT, statusCode, headerDict, data, id):
	decoded = data.decode('utf-8')

	me.parent().ext.RshipExt.OnExecInfoUpdate(decoded, id)
	return
	