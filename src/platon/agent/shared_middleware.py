from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.middleware import FilesystemMiddleware

from platon.agent.models.agent_config import AgentConfig


def shared_filesystem_middleware(
    backend_root: Path | None = None,
) -> FilesystemMiddleware:
    if backend_root is None:
        backend_root = AgentConfig().backend_root

    shared_root = backend_root / "shared"
    shared_root.mkdir(parents=True, exist_ok=True)

    return FilesystemMiddleware(
        backend=FilesystemBackend(
            root_dir=shared_root,
            virtual_mode=True,
        ),
        tools=["ls", "read_file", "glob", "grep"],
    )
