# Jolly

Jolly is a local robot-arm physics simulator for terminal users and LLM agents.
It combines PyBullet rigid-body physics, forward and inverse kinematics,
collision rollback, deterministic scenes, manipulation challenges, and an
optional local web viewer.

## Start here

```bash
npm install -g jolly-cli
jolly reset --model jolly6 --scene blocks --json
jolly state --json
```

Jolly uses no MCP server and needs no cloud account at runtime. Every control
operation is an executable CLI command. Add `--json` for machine-readable
responses.

## Wiki pages

- [Installation](Installation)
- [CLI Reference](CLI-Reference)
- [Robot Models and Licensing](Robot-Models-and-Licensing)
- [Challenges and Benchmarks](Challenges-and-Benchmarks)
- [LLM Agent Safety](LLM-Agent-Safety)
- [Web Viewer](Web-Viewer)
