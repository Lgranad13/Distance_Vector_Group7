from routing_core import *
import time

init_core(1, [1,2,3,4], {2:7,3:4,4:5}, update_interval=2)

# 2 sends an update now (records heartbeat for 2)
apply_neighbor_vector(2, {1:7, 2:0, 3:9, 4:1})

# Record a heartbeat for 3 now
note_heartbeat(3)

# Wait 3.1s, refresh 2 (so 2 stays fresh)
time.sleep(3.1)
note_heartbeat(2)

# Wait another 3.1s (total since 3's heartbeat ≈ 6.2s, since 2's heartbeat ≈ 3.1s)
time.sleep(3.1)
expire_silent_neighbors()        # no 'now' arg, uses current time

print(snapshot())

snap = snapshot()
assert snap[0] == (1, 1, 0.0)
# 2 still direct at 7
assert any(t == (2, 2, 7.0) for t in snap)
# 3 is reachable via 2 with cost 16
assert any(t == (3, 2, 16.0) for t in snap)
# 4 still direct at 5
assert any(t == (4, 4, 5.0) for t in snap)
print("PASS: failure detection + DV recompute behave as expected.")