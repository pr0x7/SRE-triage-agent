"""
Local Docker sandbox backend for deepagents.
Drop-in swap for ModalSandbox / DaytonaSandbox — no cloud account, no billing.

Requires:
    pip install docker
    Docker daemon running locally (Docker Desktop / Docker Engine)
"""
from __future__ import annotations

import asyncio
import io
import shlex
import tarfile
import uuid

import docker
from docker.models.containers import Container

import atexit
import weakref
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

_global_sandbox_registry = weakref.WeakSet()

def _cleanup_all_sandboxes():
    for sandbox in list(_global_sandbox_registry):
        try:
            sandbox.stop()
        except Exception:
            pass

atexit.register(_cleanup_all_sandboxes)


class DockerSandbox(BaseSandbox):
    """Runs agent commands inside a local Docker container.

    BaseSandbox implements every filesystem tool (ls/read/write/edit/delete/
    glob/grep) by delegating to execute(), so this class only needs to handle
    container lifecycle + the abstract methods:
      - id (property)
      - execute()
      - upload_files()
      - download_files()
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        workdir: str = "/workspace",
        network_mode: str = "none",   # Default restricted egress network mode for security
        client: docker.DockerClient | None = None,
    ) -> None:
        self._client = client or docker.from_env()
        self._image = image
        self._workdir = workdir
        self._network_mode = network_mode
        self._id = f"deepagents-sandbox-{uuid.uuid4().hex[:8]}"
        self._container: Container | None = None
        _global_sandbox_registry.add(self)

    # ── abstract property ──────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._id

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Provision the container. Call once before use (or via context manager)."""
        self._container = self._client.containers.run(
            self._image,
            name=self._id,
            command="sleep infinity",      # keep alive between exec calls
            working_dir=self._workdir,
            detach=True,
            mem_limit="1g",
            nano_cpus=1_000_000_000,       # 1 CPU
            network_mode=self._network_mode,
        )
        self._container.exec_run(["mkdir", "-p", self._workdir])

    def stop(self) -> None:
        """Always call this in a finally/cleanup block — never leave containers running."""
        if self._container is not None:
            self._container.remove(force=True)
            self._container = None

    # ── abstract: execute ──────────────────────────────────────────────

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Execute a shell command inside the container and return structured output."""
        if self._container is None:
            raise RuntimeError("Sandbox not started — call .start() first")

        # docker-py doesn't support timeout on exec_run directly,
        # so we wrap with `timeout` command if specified
        if timeout is not None:
            command = f"timeout {timeout} /bin/sh -c {shlex.quote(command)}"
            shell_cmd = ["/bin/sh", "-c", command]
        else:
            shell_cmd = ["/bin/sh", "-c", command]

        result = self._container.exec_run(
            shell_cmd,
            workdir=self._workdir,
            demux=True,
        )
        stdout, stderr = result.output
        combined = (stdout or b"").decode(errors="replace")
        if stderr:
            combined += (stderr).decode(errors="replace")

        return ExecuteResponse(
            output=combined,
            exit_code=result.exit_code,
        )

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Async wrapper — docker-py has no native async, so we thread-delegate."""
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    # ── abstract: file transfer ────────────────────────────────────────

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Copy files into the container via docker put_archive."""
        if self._container is None:
            raise RuntimeError("Sandbox not started — call .start() first")

        results: list[FileUploadResponse] = []
        for path, content in files:
            try:
                # Build a tar archive in memory with the single file
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name=path.lstrip("/"))
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
                buf.seek(0)
                # Extract the tar archive into the working directory
                self._container.put_archive(self._workdir, buf)
                results.append(FileUploadResponse(path=path))
            except Exception as e:
                results.append(FileUploadResponse(path=path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Copy files out of the container via docker get_archive."""
        if self._container is None:
            raise RuntimeError("Sandbox not started — call .start() first")

        results: list[FileDownloadResponse] = []
        for path in paths:
            try:
                # Resolve relative paths relative to working directory
                abs_path = path if path.startswith("/") else f"{self._workdir}/{path}"
                stream, _stat = self._container.get_archive(abs_path)
                data = b"".join(stream)
                # Extract the file from the tar stream
                buf = io.BytesIO(data)
                with tarfile.open(fileobj=buf) as tar:
                    members = tar.getmembers()
                    if not members:
                        results.append(FileDownloadResponse(
                            path=path, error="file_not_found"
                        ))
                        continue
                    f = tar.extractfile(members[0])
                    content = f.read() if f else b""
                results.append(FileDownloadResponse(path=path, content=content))
            except Exception as e:
                error_str = str(e)
                if "No such" in error_str or "not found" in error_str.lower():
                    results.append(FileDownloadResponse(path=path, error="file_not_found"))
                else:
                    results.append(FileDownloadResponse(path=path, error=error_str))
        return results

    # ── context manager ────────────────────────────────────────────────

    def __enter__(self) -> "DockerSandbox":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()
