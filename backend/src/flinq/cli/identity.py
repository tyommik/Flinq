"""Identity CLI commands: create-admin, reset-password, promote.

Per ADR-0008: forgot-password is CLI-only in MVP (no email-based reset).
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable

import typer

from flinq.core.config import get_settings
from flinq.core.db import dispose_engine, init_engine, session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo

app = typer.Typer(help="Identity management commands.", no_args_is_help=True)


async def _with_engine[T](coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Initialize engine for a single CLI invocation, run, then dispose."""
    settings = get_settings()
    init_engine(settings)
    try:
        return await coro_factory()
    finally:
        await dispose_engine()


@app.command("create-admin")
def create_admin(
    email: str = typer.Argument(..., help="Email for the new admin."),
    name: str = typer.Option("Admin", help="Display name."),
) -> None:
    """Create a new admin user with a random password printed to stdout."""

    async def _do() -> None:
        async with session_scope() as s:
            repo = UserRepo(s)
            if await repo.get_by_email(email):
                typer.echo(f"User {email} already exists", err=True)
                raise typer.Exit(1)
            password = secrets.token_urlsafe(12)
            await repo.create(
                email=email,
                password_hash=hash_password(password),
                display_name=name,
                role="admin",
            )
            typer.echo(f"Created admin {email} with password: {password}")

    asyncio.run(_with_engine(_do))


@app.command("reset-password")
def reset_password(
    email: str = typer.Argument(..., help="Email of the user."),
) -> None:
    """Reset password to a random temporary value, printed to stdout."""

    async def _do() -> None:
        async with session_scope() as s:
            repo = UserRepo(s)
            user = await repo.get_by_email(email)
            if user is None:
                typer.echo(f"User {email} not found", err=True)
                raise typer.Exit(1)
            password = secrets.token_urlsafe(12)
            user.password_hash = hash_password(password)
            typer.echo(f"New password for {email}: {password}")

    asyncio.run(_with_engine(_do))


@app.command("promote")
def promote(
    email: str = typer.Argument(..., help="Email of the user to promote."),
) -> None:
    """Promote a user to admin role."""

    async def _do() -> None:
        async with session_scope() as s:
            user = await UserRepo(s).get_by_email(email)
            if user is None:
                typer.echo(f"User {email} not found", err=True)
                raise typer.Exit(1)
            user.role = "admin"
            typer.echo(f"Promoted {email} to admin")

    asyncio.run(_with_engine(_do))
