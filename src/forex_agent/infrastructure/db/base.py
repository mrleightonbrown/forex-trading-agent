"""SQLAlchemy declarative base.

All ORM models live under `infrastructure` and import this base. Per
CLAUDE.md, SQLAlchemy objects must never escape infrastructure adapters —
`application` and `domain` code must not import from this module.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
