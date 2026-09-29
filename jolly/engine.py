from __future__ import annotations

from jolly.core.physics import PhysicsEngine


class JollyEngine(PhysicsEngine):
    """Jolly's simulator engine, with PyBullet used only as its physics backend."""

    name = "JollyEngine"
    physics_backend = "PyBullet"
