from kazoo.client import KazooClient, KazooState
from time import sleep
import json
import uuid

# Zookeper setup
zk = KazooClient(hosts='zoo')
zk.start()

def id_helper(myid):
    pid_arr = []
    with open("PID.file",) as zFile:
        pid_arr = json.load(zFile)
        for container in pid_arr:
            for field in container:
                if(myid in field):
                    return container[2]

def conduct_election():
    print(" [z] Conducting election.")

    children = zk.get_children("/slave")
    print(children)

    dec_pid = str(0)

    zk.create("/election/master", dec_pid.encode('utf-8'), ephemeral=True, makepath=True)

if __name__ == "__main__":
    retry_count = 0
    while True:
        try:
            data, stat = zk.get("/election/master")
            print(" [z] Master is", data.decode("utf-8"))
        except:
            retry_count += 1
            print(" [z] Retrying. Count", retry_count)

            if(retry_count==5):
                conduct_election()
                retry_count = 0

        sleep(10)