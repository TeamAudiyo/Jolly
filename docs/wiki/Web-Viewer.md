# Web Viewer

![Jolly web viewer executing a Cartesian reach in the insertion scene](../assets/jolly-web-demo.gif)

[Watch the full WebM recording](../assets/jolly-web-demo.webm) or
[open the full-resolution still](../assets/jolly-so101-viewer.png).

Start the local viewer:

```bash
jolly serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. API documentation is available at
`http://127.0.0.1:8765/api/docs`.

The viewer provides:

- An interactive PyBullet render of the official SO-101 CAD meshes.
- Robot and scene selectors.
- Joint positions and limits.
- End-effector pose.
- Collision and grasp status.
- Scene objects.
- A safe local command console for state, reset, move, and reach.

The recording executes a Cartesian reach in the insertion scene through the
local command console.

The API writes the same persistent state as the CLI. The default bind is
loopback-only. Do not use `--unsafe-public` on an untrusted network.
