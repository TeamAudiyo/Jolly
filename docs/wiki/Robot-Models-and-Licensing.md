# Robot Models and Licensing

## Jolly-6

`jolly6` is an original six-axis educational arm with a parallel gripper. Its
URDF uses primitive geometry and ships under `MIT OR Apache-2.0`.

## SO-101 profile

`so101` is a lightweight five-axis simulation profile with a gripper. It uses
original primitive geometry. Joint names, selected dimensions, and kinematic
limits derive from The Robot Studio's Apache-2.0 SO-101 metadata.

The profile does not include upstream CAD meshes. It does not claim visual
hardware fidelity or endorsement by The Robot Studio or Hugging Face.

## Physics engine

Jolly depends on PyBullet under the zlib/libpng license. The package does not
redistribute PyBullet source or binaries.

## Project license

Jolly code and original assets are dual-licensed. Users can choose the MIT
License or Apache License 2.0. See `LICENSE-MIT`, `LICENSE-APACHE`, and
`THIRD_PARTY_LICENSES.md` in the repository.
