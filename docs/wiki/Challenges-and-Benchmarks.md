# Challenges and Benchmarks

Jolly includes deterministic local scenes:

- `empty`: clear workspace for kinematics.
- `blocks`: three blocks and two target pads.
- `shelf`: floor-to-shelf manipulation.
- `obstacles`: collision-aware reaching.

Agent challenges include `reach-center`, `sort-red`, `shelf-load`, and
`obstacle-reach`. Each challenge has a command budget and explicit success
metrics.

```bash
jolly challenge start sort-red --model jolly6 --json
# Run move and reach commands.
jolly challenge status --json
```

The `jolly benchmark --json` command checks engine health. It loads each robot,
computes FK, and constructs each scene. The engine benchmark does not measure an
agent policy. Use challenge scores for task-performance evaluation.
