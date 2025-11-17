#!/usr/bin/env python3
"""
-Leonardo Granados
-CS 4470
-Programming Assignment #2 Distance Vector
-11/11/25
"""
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

    #IV --- initialize routing core after topology is loaded ---
    try:
        from routing_core import init_core
        neighbor_costs = {}
        for (nid, _ip, _port, c) in state["neighbors"]:
            neighbor_costs[nid] = float('inf') if c == -1.0 else float(c)
        all_ids = sorted(state["all_servers"].keys())
        update_interval = int(state["interval"]) if state["interval"] else 1
        init_core(state["own_id"], all_ids, neighbor_costs, update_interval)
    except Exception as _e:
        # If routing_core isn’t present during early testing, do nothing.
        pass

    #IV --- start failure sweeper thread (calls expire_silent_neighbors) ---
    def _iv_failure_sweeper():
        try:
            from routing_core import expire_silent_neighbors
        except Exception:
            return
        period = max(1.0, float(state["interval"]) / 2.0) if state["interval"] else 1.0
        while True:
            try:
                expire_silent_neighbors()
            finally:
                threading.Event().wait(period)
    threading.Thread(target=_iv_failure_sweeper, daemon=True).start()
    #IV --- end core init additions ---

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

    #IV --- replace cost with snapshot from routing_core when available ---
    try:
        from routing_core import snapshot
        new_cost = {}
        # snapshot returns list of (dest, next_hop, cost)
        for (dest, _nh, c) in snapshot():
            # encode INF as -1.0 to match Leo’s original wire format
            new_cost[dest] = -1.0 if c == float('inf') else float(c)
        # ensure every known server is present
        for sid in state["all_servers"].keys():
            new_cost.setdefault(sid, -1.0)
        # self cost must be 0.0
        new_cost[state["own_id"]] = 0.0
        cost = new_cost
    except Exception:
        # if snapshot not available, keep Leo’s original neighbor-only vector
        pass
    #IV --- end snapshot substitution ---

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

            #IV --- parse packet and feed routing_core if available ---
            try:
                from routing_core import note_heartbeat, apply_neighbor_vector
                off = 0
                if len(data) < 4 + 2 + 4:
                    continue
                num_fields = struct.unpack_from("!I", data, off)[0]; off += 4
                snd_port   = struct.unpack_from("!H", data, off)[0]; off += 2
                snd_ip_raw = data[off:off+4]; off += 4
                _snd_ip    = socket.inet_ntoa(snd_ip_raw)

                vec = {}
                # Each entry: dest_ip(4) dest_port(H) zero(B) dest_id(I) cost(f)
                for _ in range(num_fields):
                    if off + 4 + 2 + 1 + 4 + 4 > len(data):
                        break
                    _dip = data[off:off+4]; off += 4
                    _dport = struct.unpack_from("!H", data, off)[0]; off += 2
                    _zero  = data[off]; off += 1
                    dest_id = struct.unpack_from("!I", data, off)[0]; off += 4
                    c = struct.unpack_from("!f", data, off)[0]; off += 4
                    vec[dest_id] = float('inf') if c == -1.0 else float(c)

                if sender is not None:
                    note_heartbeat(sender)
                    apply_neighbor_vector(sender, vec)
            except Exception:
                # If core isn't available or parsing fails, keep original behavior
                pass
            #IV --- end core feed ---

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