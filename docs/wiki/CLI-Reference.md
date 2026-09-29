# CLI Reference

All positions use meters. All joint angles use degrees. Gripper `0.0` is open,
and gripper `1.0` is closed.

## Core commands

```bash
jolly models --json
jolly state --json
jolly reset --model jolly6 --scene empty --json
jolly move --joints "0,-25,70,-45,0,0" --gripper 0.0 --json
jolly reach --x 0.32 --y 0.00 --z 0.18 --gripper 0.0 --json
jolly fk --joints "0,-25,70,-45,0,0" --json
jolly render
```

## Scenes and challenges

```bash
jolly scene list --json
jolly scene load blocks --json
jolly challenge list --json
jolly challenge start sort-red --model jolly6 --json
jolly challenge status --json
jolly benchmark --json
```

## Viewers

```bash
jolly viewer --model jolly6 --scene blocks
jolly serve --host 127.0.0.1 --port 8765
```

Jolly rejects non-loopback web binds unless `--unsafe-public` is explicit.
Public mode has no authentication. Use public mode only in an isolated test
environment.

## Exit behavior

Successful commands exit with code 0. Invalid or unsafe requests exit nonzero.
With `--json`, Jolly emits an `ok: false` error object on stdout.
