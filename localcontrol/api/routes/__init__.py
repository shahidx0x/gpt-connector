from __future__ import annotations

from fastapi import APIRouter

from . import approvals, artifacts, config, execution, filesystem, jobs, process, projects, search, shell, system, terminal, ui

routers: tuple[APIRouter, ...] = (
    ui.router,
    system.router,
    config.router,
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
