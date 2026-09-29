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

The `pickplace` scene contains a part and randomized pickup/placement pads.
`jolly benchmark start --trials 3 --json` plans trials without task motion.
Issue approach, descent, grasp, lift, sideways motion, lowering, and release
controls. `score` settles physics and measures object coordinates once.
`next` activates the next layout. `report` calculates numeric success percentage
and placement-error statistics from immutable scored trials.

Simulation measurements come directly from PyBullet world transforms. Hardware
requires fresh independent sensor measurements. Commands and IK cannot score
object placement. See [Multi-Arm Benchmark](Multi-Arm-Benchmark).

The direct `hardware benchmark` remains a separate motor-feedback benchmark.
No simulator result is presented as physical-hardware verification.
