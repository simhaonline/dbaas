from flask import Flask, request, jsonify
from flask_script import Manager, Server
import pika
import json
import sys

import uuid
import threading
from time import sleep
from multiprocessing.pool import ThreadPool

pool = ThreadPool(processes=2)

from pymongo import MongoClient

myclient = MongoClient("orch_mongo")    
db = myclient['orch']
counts_col = db['counts']
containers_col = db['containers']

from kazoo.client import KazooClient, KazooState

# Zookeper setup
zk = KazooClient(hosts='zoo')
zk.start()

import docker
client = docker.from_env()

def pid_helper(myid):
    pid_arr = []
    with open("PID.file",) as oFile:
        pid_arr = json.load(oFile)
        for container in pid_arr:
            for field in container:
                if(str(myid) == str(field)):
                    return container[1]

class CustomServer(Server):
    def __call__(self, app, *args, **kwargs):
        return Server.__call__(self, app, *args, **kwargs)

app = Flask(__name__)
manager = Manager(app)
manager.add_command('runserver', CustomServer())

class ReadRpcClient(object):
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host='rmq'))

        self.channel = self.connection.channel()

        result = self.channel.queue_declare('', exclusive=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)
    
    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body
    
    def call(self, request):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key='read_rpc',
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
            ),
            body=request)
        while self.response is None:
            self.connection.process_data_events()
        print(" [rh] Response", self.response)
        return self.response
        
class WriteRpcClient(object):
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host='rmq'))

        self.channel = self.connection.channel()

        result = self.channel.queue_declare('', exclusive=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)
    
    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body
    
    def call(self, request):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key='write_rpc',
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
            ),
            body=request)
        while self.response is None:
            self.connection.process_data_events()
        print(" [rh] Response", self.response)
        return self.response

@app.route('/')   #demo function
def hello():
    return "Hello World! How are you?"

@app.route('/api/v1/db/write',methods = ['POST'])
def send_to_master():
    content = request.get_json()
    # print(content)

    write_rpc = WriteRpcClient()
    async_res = pool.apply_async(write_rpc.call, (json.dumps(content),))
    response = async_res.get().decode('utf8')

    master_pid = ""
    if(zk.exists("/election/master")):
        data, stat = zk.get("election/master")
        if(data):
            master_pid = str(data.decode('utf-8'))

    master_name = ""
    if(len(master_pid)!=0):
        master_name = str(pid_helper(master_pid))
    
    if(len(master_name)!=0):
        master_mongo = client.containers.get(master_name)
        output = master_mongo.exec_run('bash -c "mongodump --archive="/data/db-dump" --db=dbaas_db"')
        print(" [o] Dumped DB.")
        sleep(1)

    if(not response):
        return '', 204 
    else:
        return response, 200

@app.route('/api/v1/db/read', methods = ['POST'])
def send_to_slaves():
    content = request.get_json()
    # print(content)

    read_rpc = ReadRpcClient()
    async_res = pool.apply_async(read_rpc.call, (json.dumps(content),))
    response = async_res.get().decode('utf8')

    count = counts_col.find_one_and_update({"name": "default"}, {"$inc": {"count": 1}})
    if(not response):
        return '', 204 
    else:
        return response, 200

@app.route('/api/v1/worker/list', methods = ['GET'])
def worker_list():
    data = get_stats()
    arr = []

    for i in range(len(data)):
        if(data[i][2][:6]=="new_ms"):
            if(is_a_slave):  #implement
                arr.append(int(data[i][2]))
    arr.sort()
   
    # print(arr)
    return jsonify(arr), 200

@app.route('/api/v1/crash/master', methods = ['POST'])
def crash_master():
    data = get_stats()
    arr = []
    for i in range(len(data)):
        if(data[i][1][0:6]=="new_ms" and is_a_master): #implement
                pid=data[i][2]
                mongo_pid=get_associated_mongo_db(pid) #implement
                os.kill(pid, signal.SIGTERM)
                os.kill(mongo_pid,signal.SIGTERM)

    return 200

@app.route('/api/v1/crash/slave', methods = ['POST'])
def crash_slave():
    data = get_stats()
    arr = []
    for i in len(data):
        if(data[i][1][0:6]=="new_ms" and is_a_slave) #implement
            arr.append(int(data[i][2]))
    pid = max(arr) #highest pid is killed
    mongo_pid=get_associated_mongo_db(pid) #implement
    os.kill(pid, signal.SIGTERM)
    os.kill(mongo_pid,signal.SIGTERM)
    return 200

def get_stats():
    data = None
    with open('./PID.file') as iFile:
        try:
            data = json.load(iFile)
        except:
            pass
    return data

if __name__ == '__main__':
    # app.run(debug=True, host='0.0.0.0')
    manager.run()