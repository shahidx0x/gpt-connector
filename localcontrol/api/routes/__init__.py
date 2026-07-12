from __future__ import annotations

from fastapi import APIRouter

from . import approvals, artifacts, execution, filesystem, jobs, process, projects, search, shell, system, terminal

routers: tuple[APIRouter, ...] = (
    system.router,
    filesystem.router,
    artifacts.router,
    search.router,
    shell.router,
    terminal.router,
    jobs.router,
    execution.router,
    projects.router,
    process.router,
    approvals.router,
)

