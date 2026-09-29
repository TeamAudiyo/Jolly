# Challenges and Benchmarks

Jolly includes local scene templates:

- `empty`: clear workspace for kinematics.
- `blocks`: three blocks and two target pads.
- `shelf`: floor-to-shelf manipulation.
- `obstacles`: collision-aware reaching.

Agent challenges include `reach-center`, `sort-red`, `shelf-load`, and
`obstacle-reach`. `JollyDriver` generates a new target and scene layout for each
start. Each challenge has a command budget and explicit success metrics.

```bash
jolly challenge start sort-red --model jolly6 --json
# Run move and reach commands.
jolly challenge status --json
```

The start result contains a generated seed and instance. Use `--seed` to replay
the exact case.

`jolly benchmark --json` executes randomized reaching, obstacle avoidance, and
drop-in-hole tasks. The score uses measured reach error, collision state, grasp
state, release state, and the peg's final physical pose. Scene construction and
forward-kinematics health checks contribute no points.

Jolly uses its own `JollyEngine`, `JollyDriver`, and direct
`SO101HardwareDriver`. It does not use Inspect, Inspect AI, or an external robot
benchmark harness. PyBullet remains the local open-source rigid-body backend
for physics tasks. Physical SO-101 results come only from STS3215 motor feedback
and remain separate from physics scores.
