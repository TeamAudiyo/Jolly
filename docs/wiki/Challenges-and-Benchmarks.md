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

`jolly benchmark --json` checks engine health with randomized joint states and
scene layouts. Use `--cases` to select cases per model and scene. Use `--seed`
to replay the exact generated inputs.

Jolly uses its own `JollyEngine` and `JollyDriver`. It does not use Inspect,
Inspect AI, or an external robot benchmark harness. PyBullet remains the local
open-source rigid-body physics backend.
