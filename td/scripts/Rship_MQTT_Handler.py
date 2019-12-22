# Rocketship Touchdesigner MQTT Adapter 
# Ignition Enterprises Â© 2019
# K Bjordahl

import json

class Router:
    def getStatus(self, payload):
        # TODO: implement status monitor
        return { "status": "ACTIVE" }

    def getSource(self, payload):
        path = op.RshipAdapter.Sources[payload['id']]
        sourceOp = op(path)
        return sourceOp.GetRshipSource()

    def getSources(self, payload):
        sources = []
        for _, path in op.RshipAdapter.Sources.items():
            sourceOp = op(path)
            sources.append(sourceOp.GetRshipSource())
        return sources

    def getChannel(self, payload):
        path = op.RshipAdapter.Channels[payload['id']]
        channelOp = op(path)
        return channelOp.GetRshipChannel()

        return channels
    def getChannels(self, payload):
        channels = []
        for _, path in op.RshipAdapter.Channels.items():
            channelOp = op(path)
            channels.append(channelOp.GetRshipChannel())

        return channels

        
    
def init(systemId, instanceId, mqtt):
    # set up initial subscriptions for mqtt here
    commission_topic= '/'.join([systemId, instanceId])

    # get the endpoints from the router object and subscribe to them
    router = Router()
    endpoints = [method_name for method_name in dir(router)
                  if callable(getattr(router, method_name)) and 
                  method_name[0] is not '_']

    for endpoint in endpoints:
        print('subscribing to /'+endpoint)
        mqtt.subscribe(commission_topic+'/'+endpoint)

# Called when new content received from server
# dat - the mqtt OP which is cooking
# topic - topic name of the incoming message
# payload - payload of the incoming message
# qos - qos flag for of the incoming message
# retained - retained flag of the incoming message
# dup - dup flag of the incoming message
def mqtt_inbound_router(dat, topic, payload, qos, retained, dup):
    
    pruned_topic = topic.split('/')[-1]

    # call the routed function by name
    try:
        router = Router()
        if(len(payload) > 0):
            data = json.loads(payload.decode())
        else:
            data = {}

        result = getattr(router, pruned_topic)(data)
        dat.publish(topic+'/result', json.dumps(result).encode())
    except Exception as e:
        print('plugin error: ', e)
        dat.publish(topic+'/error', (pruned_topic + ' is not a valid api topic').encode())

