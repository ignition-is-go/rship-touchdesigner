# me - this DAT.
# webClientDAT - The connected Web Client DAT
# statusCode - The status code of the response, formatted as a dictionary with two key-value pairs: 'code', 'message'.
# headerDict - The header of the response from the server formatted as a dictionary. Only sent once when streaming.
# data - The data of the response
# id - The request's unique identifier

def onConnect(webClientDAT, id):
	me.ext.RshipExt.OnRshipUrlClientConnect(id)
	return
	
def onDisconnect(webClientDAT, id):
	me.ext.RshipExt.OnRshipUrlClientDisconnect(id)
	return

def onResponse(webClientDAT, statusCode, headerDict, data, id):
	decoded = data.decode('utf-8')
	me.ext.RshipExt.OnRshipUrlUpdate(decoded, id)

	return
	