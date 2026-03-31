"""Shared FastAPI dependency callables for route modules."""

from __future__ import annotations

from fastapi import Depends

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.persistence.factory import get_repository
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def get_repo(settings: Settings = Depends(get_settings)) -> Repository:
    return get_repository(settings)


def get_invoker(settings: Settings = Depends(get_settings)) -> DefaultRoleInvoker:
    return DefaultRoleInvoker(settings=settings)
