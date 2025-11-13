#!/usr/bin/env python3

import socket
import struct
import threading
import sys
import argparse

#LG
# state to hold information
state = {
    "own_id":   None,
    "own_ip":   None,
    "own_port": None,
    "all_servers": {},   # dictonary of id -> (ip, port)
    "neighbors":   [],   # list of (id, ip, port, cost)
    "sock":        None,
    "timer":       None,
    "interval":    None,
}

#LG
# function to parse the topology file for server startup
def parse_topology(topology_file):
    file = open(topology_file, "r")
    lines = []

    for line in file:               # for loop to check the each line in the file and put it in the lines array
        line = line.strip()

        if line:
            lines.append(line)

    file.close()

    idx = 0
    total_servers = int(lines[idx]) # index set at 0 to grab the total server and increments idx
    idx = idx + 1
    num_neighbors = int(lines[idx]) # index at 1 to grab the neighbors and increments idx
    idx = idx + 1

    all_servers = {}                # server array to grab the info in the lines array
    i = 0

    while i < total_servers:        # while loop to go through total servers
        parts = lines[idx].split()  # if topology file is setup correctly all parts will be gathered correctly
        sid   = int(parts[0])
        ip    = parts[1]
        port  = int(parts[2])
        all_servers[sid] = (ip, port)
        idx = idx + 1
        i = i + 1

    links = []                      # links topology array 
    i = 0

    while i < num_neighbors:        # while loop to go through neighbors
        parts = lines[idx].split()  # if topology file is setup correctly all parts will be gathered correctlu
        a = int(parts[0])
        b = int(parts[1])
        c = parts[2]
        if c.lower() == "inf":
            cost = -1.0
        else:
            cost = float(c)
        links.append((a, b, cost))
        idx = idx + 1
        i = i + 1

    ## commented out for testing local only for now
    #local_ip = socket.gethostbyname(socket.gethostname())   # gets self ip
    
    #this is only for testing locally
    local_ip = "127.0.0.1"

    state["sock"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    own_id   = None
    own_port = None
    for sid in all_servers:                                 # for loop to check if self ip is in the file
        ip, port = all_servers[sid]
        if ip == local_ip:                                  # if found grabs the id, and port
            try:
                state["sock"].bind((ip,port))
                own_id   = sid
                own_port = port
                break
            except OSError:
                pass
    if own_id is None:                                      # if ip is not found or if file is not setup correctly stops program and error msg
        sys.exit("ERROR: local IP not found in topology file")

    neighbors = []                                          
    for a, b, cost in links:                                # for loop to create the links and neighbors and puts them in the list
        if a == own_id:
            ip, port = all_servers[b]
            neighbors.append((b, ip, port, cost))
        elif b == own_id:
            ip, port = all_servers[a]
            neighbors.append((a, ip, port, cost))

    # places all found elements in public state (own_id, own_ip, own_port, all_servers, neighbors)
    state["own_id"]      = own_id
    state["own_ip"]      = local_ip
    state["own_port"]    = own_port
    state["all_servers"] = all_servers
    state["neighbors"]   = neighbors


    # prints out the self as server and prints out the neighbors from the file
    print("--> Server %d @ %s:%d" % (own_id, local_ip, own_port))
    neigh_ids = []
    for n in neighbors:
        neigh_ids.append(str(n[0]))
    print("--> Neighbors: " + ", ".join(neigh_ids))

#LG
# helper function to create udp packets to update the neighbors with
def build_update_packet():
    cost = {}
    cost[state["own_id"]] = 0.0
    for nid, _, _, c in state["neighbors"]:         # for loop to place cost from neighbors to new dict cost
        cost[nid] = c
    for sid in state["all_servers"]:                # for loop to make the unreachable servers infinity
        if sid not in cost:
            cost[sid] = -1.0                     

    pkt = struct.pack("!I", len(cost))              # number of update fields, !I means network int 4 byte 
    pkt += struct.pack("!H", state["own_port"])     # own port, means network, !H meants network short 2 byte
    pkt += socket.inet_aton(state["own_ip"])        # own IP 4 byte

    
    for sid in cost:                                # for loop to prepare udp packet to send the info to all neighbors
        ip, port = state["all_servers"][sid]
        pkt += socket.inet_aton(ip)             # dest IP
        pkt += struct.pack("!H", port)          # dest port
        pkt += struct.pack("B", 0)              # 0x0
        pkt += struct.pack("!I", sid)           # dest ID
        pkt += struct.pack("!f", cost[sid])     # cost

    return pkt

#LG
# function to send the packets
def send_update():
    if state["sock"] is None:                           # if statement to check if socket is live
        return

    pkt = build_update_packet()                         # use the build packet function to create packet
    for nid, ip, port, _ in state["neighbors"]:         # for loop to try and send packets
        try:
            state["sock"].sendto(pkt, (ip, port))
        except Exception as e:
            print("--> [SEND ERROR] to %d: %s" % (nid, str(e)))
        except:
            pass

    schedule_next_update()                              # runs schedule function to reset timer

#LG
# function to start the timer and reset it when needed
def schedule_next_update():
    if state["timer"]:                                  # if statement to check if its the first time running
        state["timer"].cancel()
    t = threading.Timer(state["interval"], send_update) # creates tread using the time set by the user
    t.daemon = True
    t.start()                                           # timer starts
    state["timer"] = t                                  # timer placed in public state

#LG
# function to recieve packets from neighbors
def receive_loop():
    s = state["sock"]                                   # creates socket
    while True:                                         # while loop to continously look out for data
        try:
            data, (src_ip, src_port) = s.recvfrom(1024) # tries to get the data in the packet
            # find sender ID
            sender = None
            for sid in state["all_servers"]:            # for loop to see if sender of packet is indeed in the topology file
                ip, port = state["all_servers"][sid]
                if ip == src_ip and port == src_port:
                    sender = sid
                    break
            if sender is not None:                      # if state to print out msg of rcvd msg from server, else state to print unknown sender
                print("--> RECEIVED A MESSAGE FROM SERVER",sender,"(%s:%d)" % (src_ip,src_port))
            else:
                print("--> RECEIVED from unknown %s:%d" % (src_ip, src_port))
        except:                                         # if error break from program
            break

#LG
# function to start the server
def server(topo_file, interval):
    global state                                                        # creates the state
    state["interval"] = interval                                        

    parse_topology(topo_file)                                           # parse topology function called
    #bind_socket()                                                       # bind socket function called

    recv_thread = threading.Thread(target=receive_loop, daemon=True)    # start reciever thread
    recv_thread.start()

    schedule_next_update()                                              # start the udp packet update timer


    try:                                        
        while True:                                                     # continuos while loop to keep server up
            pass
    except KeyboardInterrupt:
        print("--> exiting ")

#LG
# main function of entire program
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Distance Vector Routing Server Group 7"
    )                                   # uses argparse to grab user inputs
    parser.add_argument("-t", required=True, help="path of Topology file ex: topo.txt")      # following -t grabs info for file path, and layout for help
    parser.add_argument("-i", type=float, required=True, help="Update interval (seconds) ex: 5 (for 5 secs)\n") # following -i grabs info for interval and layout for help
    config = parser.parse_args()        # places -t and -i into config

    server(config.t, config.i)          # runs the server