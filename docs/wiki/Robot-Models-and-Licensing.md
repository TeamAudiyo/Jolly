# Robot Models and Licensing

## Jolly-6

`jolly6` is an original six-axis educational arm with a parallel gripper. Its
URDF uses primitive geometry and ships under `MIT OR Apache-2.0`.

## SO-101 profile

`so101` uses the official five-axis new-calibration URDF and its 13 referenced
STL meshes. Jolly vendors the unmodified files from pinned commit
`5f6d2b876a53a4872e405b991dd925556c9e38a4` of The Robot Studio's SO-ARM100
repository.

The upstream model is Apache-2.0. Jolly includes the upstream license,
`CITATION.cff`, README, and a source record. Jolly does not claim endorsement by
The Robot Studio or Hugging Face.

## Physics engine

Jolly depends on PyBullet under the zlib/libpng license. The package does not
redistribute PyBullet source or binaries.

## Project license

Jolly code and original assets are dual-licensed. Users can choose the MIT
License or Apache License 2.0. See `LICENSE-MIT`, `LICENSE-APACHE`, and
`THIRD_PARTY_LICENSES.md` in the repository.
