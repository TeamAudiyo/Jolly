---
name: jolly
description: Safely read, move, and benchmark local robot arms with JollyEngine and JollyDriver. Use for FK, IK, scene tasks, and pick-and-place.
---

# Jolly CLI skill

Control Jolly only through executable `jolly` subcommands. Do not use MCP.
Request JSON for every planning or verification command.

## Units and conventions

- Use meters for Cartesian positions.
- Use degrees for joint angles.
- Use `0.0` for an open gripper.
- Use `1.0` for a closed gripper.
- Treat `ok: false`, a nonzero exit status, or `collision: true` as a failure.

## Safe control loop

1. Run `jolly state --json` before each task.
2. Confirm the model DOF and current scene.
3. Read every object's position from the current state.
4. Move above an object before descending.
5. Keep at least 3 cm clearance from obstacles and the floor.
6. Close the gripper only when the tool is within 10 cm of a graspable object.
7. Lift vertically before moving laterally.
8. Move above the destination before descending.
9. Open the gripper to release the object.
10. Run `jolly state --json` after every motion.
11. Stop if Jolly reports a collision or joint-limit error.
12. Never add `--allow-collision` during a normal task.

## Discover the simulator

```bash
jolly models --json
jolly scene list --json
jolly challenge list --json
jolly state --json
```

Read `model.dof` before you construct a joint command. `jolly6` needs six arm
angles. `so101` needs five arm angles.

## Move by joint angles

```bash
jolly move --joints "0,-25,70,-45,0,0" --gripper 0.0 --json
```

Use only angles inside each joint's `limits_degrees` from `jolly state --json`.

## Move by Cartesian position

```bash
jolly reach --x 0.30 --y -0.10 --z 0.18 --gripper 0.0 --json
```

Verify `ik.within_tolerance` after the command. Do not continue when IK fails.

## Pick and place

Use this sequence. Replace coordinates with live object and target positions.

```bash
jolly reach --x 0.30 --y -0.16 --z 0.14 --gripper 0.0 --json
jolly reach --x 0.30 --y -0.16 --z 0.10 --gripper 0.0 --json
jolly reach --x 0.30 --y -0.16 --z 0.10 --gripper 1.0 --json
jolly state --json
jolly reach --x 0.30 --y -0.16 --z 0.18 --gripper 1.0 --json
jolly reach --x 0.16 --y -0.27 --z 0.18 --gripper 1.0 --json
jolly reach --x 0.16 --y -0.27 --z 0.10 --gripper 1.0 --json
jolly reach --x 0.16 --y -0.27 --z 0.10 --gripper 0.0 --json
jolly reach --x 0.16 --y -0.27 --z 0.18 --gripper 0.0 --json
```

After closing, require `held_object` to match the intended object. If it is
`null`, open the gripper, move above the object, and retry once.

## Challenges and benchmarks

```bash
jolly challenge start sort-red --model jolly6 --json
jolly challenge status --json
jolly benchmark start --json
# Read the generated instance and issue explicit reach or move controls.
jolly benchmark score --json
```

Read the generated `seed` and `instance` before planning. Never assume fixed
coordinates from an earlier run. Pass `--seed N` only to replay a case.

Jolly's PyBullet benchmark never moves the robot automatically. Read the
generated peg and hole coordinates, then issue every approach, descend, grasp,
lift, translate, lower, and release control. `benchmark score` measures the
result without moving the robot and returns PASS or FAIL with no numeric score.
Physical hardware uses the separate `jolly hardware benchmark` command.

## Recovery

Use this command after an unsafe pose or failed task:

```bash
jolly reset --model jolly6 --scene empty --json
```

Report the failed command, error JSON, model, scene, and last safe state.
