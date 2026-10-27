"""Keeps the `tenants` table in step with config/tenants/*.yaml (business tables point at it)."""

import logging

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import Tenant
from app.tenants import TenantRegistry

log = logging.getLogger("app")


def sync_tenants(engine: Engine, registry: TenantRegistry) -> None:
    with Session(engine) as session, session.begin():
        for tenant_id in registry.ids():
            config = registry.get(tenant_id)
            row = session.get(Tenant, tenant_id)
            if row is None:
                session.add(
                    Tenant(id=tenant_id, brand_name=config.brand_name, locale=config.locale)
                )
            else:
                row.brand_name, row.locale = config.brand_name, config.locale
