"""Storage abstraction for engine data delivery.

Why this exists (observed live 2026-07-15, malloy bring-up): the runner
sandboxes DATA_DIR into a temp workspace per experiment, but engines backed by
a long-lived server container read from a FIXED bind mount. An engine that
derives its data directory from DATA_DIR writes into the sandbox, the server
never sees the files, and ingestion "succeeds" invisibly. The failure was
structural: the assumption that every engine shares the runner's local
filesystem is false for client-server engines.

The contract: engines never join paths to decide where data lives. They hold a
DataStore and call `put_file` / `put_text`; the store owns the location and —
for mounted stores — VERIFIES that what was written is actually visible from
inside the container before returning. Delivery is checked, not assumed.
"""
import os
import shutil
import subprocess
from typing import Protocol, runtime_checkable


@runtime_checkable
class DataStore(Protocol):
    """Where an engine's data lives, and how files get there."""

    root: str  # host-side directory the store manages

    def put_file(self, local_path: str, dest_name: str) -> str:
        """Copy a local file into the store. Returns the host-side path."""
        ...

    def put_text(self, content: str, dest_name: str) -> str:
        """Write text content into the store. Returns the host-side path."""
        ...

    def describe(self) -> str:
        """One line for logs/errors: where this store delivers to."""
        ...


class LocalDirStore:
    """For in-process engines: a plain host directory (may live inside the
    per-experiment sandbox — that's fine, the engine runs in this process)."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def put_file(self, local_path: str, dest_name: str) -> str:
        dest = os.path.join(self.root, dest_name)
        shutil.copy(local_path, dest)
        return dest

    def put_text(self, content: str, dest_name: str) -> str:
        dest = os.path.join(self.root, dest_name)
        with open(dest, "w") as f:
            f.write(content)
        return dest

    def describe(self) -> str:
        return f"LocalDirStore({self.root})"


class MountedVolumeStore:
    """For client-server Docker engines: a host directory that is bind-mounted
    into a running container. Writes go to `host_dir`; the container reads
    them at `container_dir`.

    Delivery is verified, not assumed: on first write, a probe file is written
    host-side and checked for visibility INSIDE the container via
    `docker exec`. If the mount is missing, stale, or pointing elsewhere, the
    experiment fails at ingestion with an error naming both sides of the
    mount — never a downstream 404.
    """

    def __init__(self, host_dir: str, container_dir: str, container: str):
        self.root = host_dir
        self.container_dir = container_dir
        self.container = container
        self._verified = False
        os.makedirs(host_dir, exist_ok=True)

    def _verify_mount(self) -> None:
        if self._verified:
            return
        probe = ".sbd_mount_probe"
        host_probe = os.path.join(self.root, probe)
        with open(host_probe, "w") as f:
            f.write("probe")
        try:
            res = subprocess.run(
                ["docker", "exec", self.container, "test", "-f",
                 os.path.join(self.container_dir, probe)],
                capture_output=True, timeout=30,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"{self.describe()}: 'docker' not found on PATH — cannot "
                f"verify the mount for container '{self.container}'."
            )
        finally:
            os.remove(host_probe)
        if res.returncode != 0:
            raise RuntimeError(
                f"{self.describe()}: file written to host dir '{self.root}' "
                f"is NOT visible at '{self.container_dir}' inside container "
                f"'{self.container}'. The bind mount is missing or points "
                f"elsewhere — check the container's compose file and that the "
                f"engine's store is anchored to the mounted host path (not a "
                f"sandboxed DATA_DIR)."
            )
        self._verified = True

    def put_file(self, local_path: str, dest_name: str) -> str:
        self._verify_mount()
        dest = os.path.join(self.root, dest_name)
        shutil.copy(local_path, dest)
        return dest

    def put_text(self, content: str, dest_name: str) -> str:
        self._verify_mount()
        dest = os.path.join(self.root, dest_name)
        with open(dest, "w") as f:
            f.write(content)
        return dest

    def describe(self) -> str:
        return (f"MountedVolumeStore(host={self.root} -> "
                f"container={self.container}:{self.container_dir})")
