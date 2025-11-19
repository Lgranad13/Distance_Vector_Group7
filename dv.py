#!/usr/bin/env python3
"""
-Leonardo Granados, Cooper Palmer
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

    "packets_received": 0,
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
    local_ip = socket.gethostbyname(socket.gethostname())   # gets self ip
    local_ip = socket.gethostbyname(socket.gethostname())   # gets self ip

    #this is only for testing locally
    #local_ip = "127.0.0.1"

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

# *** NEW HELPER: check if a server is still an active neighbor ***
def _is_active_neighbor(server_id: int) -> bool:
    for (nid, _ip, _port, _cost) in state["neighbors"]:
        if nid == server_id:
            return True
    return False

#LG
# function to recieve packets from neighbors
def receive_loop():
    s = state["sock"]                                   # creates socket
    while True:                                         # while loop to continuously look out for data
        try:
            data, (src_ip, src_port) = s.recvfrom(1024) # tries to get the data in the packet
            # find sender ID
            sender = None
            for sid in state["all_servers"]:            # for loop to see if sender of packet is indeed in the topology file
                ip, port = state["all_servers"][sid]
                if ip == src_ip and port == src_port:
                    sender = sid
                    break

            # Ignore packets from unknown senders or from servers that are no
            # longer in our neighbor list (e.g., after 'disable').
            if sender is None or not _is_active_neighbor(sender):
                continue

            # RECEIVED A MESSAGE FROM SERVER <server-ID>
            print(f"RECEIVED A MESSAGE FROM SERVER {sender}")

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

                note_heartbeat(sender)
                apply_neighbor_vector(sender, vec)
                # *** ADDED FOR PART 5: count packets for 'packets' command ***
                state["packets_received"] += 1
            except Exception:
                # If core isn't available or parsing fails, keep original behavior
                pass
            #IV --- end core feed ---

        # *** MODIFIED FOR WINDOWS UDP BEHAVIOR (ConnectionResetError) ***
        except ConnectionResetError:
            # On Windows, sending to a UDP port with no listener causes recvfrom()
            # to raise ConnectionResetError(10054). We just ignore this and keep listening.
            continue
        except Exception:
            # other fatal error: break out of loop
            break


# =====================================================================
#  COMMAND HANDLERS (PART 4 + PART 5)
# =====================================================================

def cmd_update(tokens):
    """
    Handle: update <server-ID1> <server-ID2> <Link Cost>

    This updates the local neighbor cost (if this server is one of the
    endpoints) and notifies routing_core so the distance-vector table
    is recomputed.
    """
    cmd_str = tokens[0]

    # Expect exactly 4 tokens: update s1 s2 cost
    if len(tokens) != 4:
        print(f"{cmd_str} ERROR: wrong number of arguments")
        return

    # Parse server IDs
    try:
        s1 = int(tokens[1])
        s2 = int(tokens[2])
    except ValueError:
        print(f"{cmd_str} ERROR: server IDs must be integers")
        return

    # Parse cost (may be a number or 'inf')
    cost_tok = tokens[3].strip()
    if cost_tok.lower() == "inf":
        new_cost_core = float("inf")   # for routing_core
        new_cost_wire = -1.0           # for our wire format (build_update_packet)
    else:
        try:
            new_cost_core = float(cost_tok)
            new_cost_wire = new_cost_core
        except ValueError:
            print(f"{cmd_str} ERROR: invalid link cost")
            return

    # See if THIS server is one of the endpoints
    my_id = state["own_id"]
    if my_id not in (s1, s2):
        # Valid command, but this particular process does nothing.
        # Spec says still print "<command-string> SUCCESS".
        print(f"{cmd_str} SUCCESS")
        return

    # Determine the neighbor ID on the other side of the link
    neighbor_id = s2 if my_id == s1 else s1

    # --- update neighbor list (id, ip, port, cost) -> set new cost ---
    updated = False
    new_neighbors = []
    for (nid, ip, port, c) in state["neighbors"]:
        if nid == neighbor_id:
            new_neighbors.append((nid, ip, port, new_cost_wire))
            updated = True
        else:
            new_neighbors.append((nid, ip, port, c))

    if not updated:
        print(f"{cmd_str} ERROR: server {neighbor_id} is not a neighbor")
        return

    state["neighbors"] = new_neighbors

    # --- notify routing_core so DV tables update ---
    try:
        from routing_core import set_direct_cost
        set_direct_cost(s1, s2, new_cost_core)
    except Exception:
        # If routing_core isn’t present (during early testing), ignore
        pass

    # Optionally send an immediate update reflecting the new cost
    send_update()

    print(f"{cmd_str} SUCCESS")


def cmd_step(tokens):
    cmd_str = tokens[0]
    send_update()
    print(f"{cmd_str} SUCCESS")


def cmd_packets(tokens):
    cmd_str = tokens[0]
    count = state.get("packets_received", 0)
    print(f"{cmd_str} SUCCESS")
    # spec allows additional output; print the count on its own line
    print(count)
    state["packets_received"] = 0


def cmd_display(tokens):
    cmd_str = tokens[0]
    print(f"{cmd_str} SUCCESS")

    # First try to display using routing_core snapshot if available
    used_core = False
    try:
        from routing_core import snapshot
        entries = snapshot()  # list of (dest, next_hop, cost)
        # sort by destination id
        entries = sorted(entries, key=lambda t: t[0])
        print("dest-id  next-hop  cost-of-path")
        for dest, nh, c in entries:
            cost_str = "inf" if c == float('inf') else f"{c:.3f}"
            nh_str = "-1" if nh is None else str(nh)
            print(f"{dest:7d}  {nh_str:8s}  {cost_str}")
        used_core = True
    except Exception:
        used_core = False

    if not used_core:
        # fallback: derive something simple from neighbor list
        print("dest-id  next-hop  cost-of-path")
        for sid in sorted(state["all_servers"].keys()):
            if sid == state["own_id"]:
                print(f"{sid:7d}  {sid:8d}  0.000")
            else:
                nh = None
                cost = float('inf')
                for (nid, _ip, _port, c) in state["neighbors"]:
                    if nid == sid and c != -1.0:
                        nh = nid
                        cost = c
                        break
                cost_str = "inf" if cost == float('inf') else f"{cost:.3f}"
                nh_str = "-1" if nh is None else str(nh)
                print(f"{sid:7d}  {nh_str:8s}  {cost_str}")


def cmd_disable(tokens):
    """
    Handle: disable <server-ID>

    Close the link to a given server:
    - stop sending updates to that server
    - mark the direct cost to INF in routing_core
    """
    cmd_str = tokens[0]

    if len(tokens) != 2:
        print(f"{cmd_str} ERROR: wrong number of arguments")
        return

    # parse the server ID to disable
    try:
        target_id = int(tokens[1])
    except ValueError:
        print(f"{cmd_str} ERROR: invalid server ID")
        return

    my_id = state["own_id"]
    if target_id == my_id:
        print(f"{cmd_str} ERROR: cannot disable self")
        return

    # --- remove target from neighbor list so we no longer SEND to it ---
    found = False
    new_neighbors = []
    for (nid, ip, port, cost) in state["neighbors"]:
        if nid == target_id:
            found = True
            # do NOT append – effectively closing the local link
        else:
            new_neighbors.append((nid, ip, port, cost))

    if not found:
        print(f"{cmd_str} ERROR: server {target_id} is not a neighbor")
        return

    state["neighbors"] = new_neighbors

    # --- tell routing_core the direct cost is now INF ---
    try:
        from routing_core import set_direct_cost
        set_direct_cost(my_id, target_id, float("inf"))
    except Exception:
        # if routing_core isn't available for some reason, ignore
        pass

    print(f"{cmd_str} SUCCESS")



def cmd_crash(tokens):
    cmd_str = tokens[0]
    # spec doesn't require SUCCESS string here; just close and exit
    print(f"{cmd_str} SUCCESS")
    if state["timer"]:
        state["timer"].cancel()
        state["timer"] = None
    if state["sock"]:
        try:
            state["sock"].close()
        except Exception:
            pass
        state["sock"] = None
    sys.exit(0)


def command_loop():
    """Read commands from stdin and dispatch to handlers."""
    while True:
        try:
            line = input()
        except EOFError:
            break
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        cmd = tokens[0].lower()

        if cmd == "update":
            cmd_update(tokens)
        elif cmd == "step":
            cmd_step(tokens)
        elif cmd == "packets":
            cmd_packets(tokens)
        elif cmd == "display":
            cmd_display(tokens)
        elif cmd == "disable":
            cmd_disable(tokens)
        elif cmd == "crash":
            cmd_crash(tokens)
        else:
            # follow "<command-string> <error message>" format
            print(f"{tokens[0]} ERROR: unknown command")

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
        # *** MODIFIED FOR PART 4: run command interpreter instead of busy loop ***
        command_loop()
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
