# Third-party licenses

## PyBullet / Bullet3

Jolly depends on PyBullet. Jolly does not redistribute PyBullet source or
binaries.

- Source: https://github.com/bulletphysics/bullet3
- License: zlib/libpng (`Zlib`)
- License text: https://github.com/bulletphysics/bullet3/blob/master/LICENSE.txt

## SO-ARM100 / SO-101 robot model

Jolly redistributes the official SO-101 new-calibration URDF and its referenced
STL meshes without modification. The files are under
`jolly/assets/robots/so101/`.

- Source: https://github.com/TheRobotStudio/SO-ARM100
- Pinned source commit: `5f6d2b876a53a4872e405b991dd925556c9e38a4`
- Upstream file: `Simulation/SO101/so101_new_calib.urdf`
- License: Apache License 2.0
- Modifications: None to the vendored URDF or STL files. Jolly selects the
  upstream `gripper_frame_link` as its inverse-kinematics end effector and maps
  the normalized CLI gripper value onto the upstream revolute joint limits.

The upstream work is titled "Standard Open SO-100 & SO-101 Arms." Its cited
authors are Rob Knight, Pepijn Kooijmans, Remi Cadene, Simon Alibert, Michel
Aractingi, Dana Aubakirova, Adil Zouitine, Russi Martino, Steven Palma,
Caroline Pascal, and Thomas Wolf.

Apache License 2.0 grants no trademark rights. Jolly does not claim endorsement
by The Robot Studio or Hugging Face.

The full Apache License 2.0 appears in `LICENSE-APACHE`.
