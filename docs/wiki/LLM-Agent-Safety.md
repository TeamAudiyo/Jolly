# LLM Agent Safety

Use the installable skill at `skills/jolly/SKILL.md` for the full control loop.

## Required loop

1. Run `jolly state --json` before a task.
2. Read the model DOF, joint limits, scene, and object positions.
3. Move above the object before descending.
4. Close the gripper only near a graspable object.
5. Lift before lateral motion.
6. Move above the target before descending.
7. Verify every response before the next command.
8. Stop on any nonzero exit, `ok: false`, or collision.

Jolly rolls back a motion when the robot or a held object contacts the
environment. Do not use `--allow-collision` in a normal task.

Reset after an unsafe or unknown state:

```bash
jolly reset --model jolly6 --scene empty --json
```
