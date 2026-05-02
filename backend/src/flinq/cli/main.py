"""Typer CLI commands.

Usage examples:
    flinq serve
    flinq serve --host 0.0.0.0 --port 8000
    flinq worker
"""

from __future__ import annotations

import typer

from flinq.cli.identity import app as identity_app

app = typer.Typer(help="Flinq administration and dev CLI.", no_args_is_help=True)

app.add_typer(identity_app, name="identity")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev only)."),
) -> None:
    """Run the FastAPI application via uvicorn."""
    import uvicorn

    uvicorn.run(
        "flinq.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def worker() -> None:
    """Run the Taskiq worker.

    This command execs into `taskiq worker flinq.worker.broker:broker` so the
    Taskiq CLI owns the process (lifecycle, signal handling, graceful shutdown).
    """
    import os

    args = ["taskiq", "worker", "flinq.worker.broker:broker", "flinq.worker.tasks"]
    os.execvp(args[0], args)  # noqa: S606


if __name__ == "__main__":
    app()
