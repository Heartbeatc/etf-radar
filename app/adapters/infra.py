from __future__ import annotations

from app.core.config import Settings

try:
    import asyncpg
except Exception:  # pragma: no cover
    asyncpg = None

try:
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover
    redis_async = None


class PostgresInfra:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.postgres_enabled
        self.last_error: str | None = None

    async def ensure_schema(self) -> None:
        if not self.enabled:
            return
        statements = [
            """
            create table if not exists schema_meta (
                key text primary key,
                value text not null,
                updated_at timestamptz not null default now()
            )
            """,
            """
            create table if not exists positions (
                code text primary key,
                entry_price numeric(18,6) not null,
                shares numeric(24,6),
                note text not null default '',
                updated_at timestamptz not null default now()
            )
            """,
            """
            create table if not exists system_locks (
                lock_key text primary key,
                owner text not null,
                expires_at timestamptz not null,
                updated_at timestamptz not null default now()
            )
            """,
            """
            create table if not exists job_runs (
                id bigserial primary key,
                job_name text not null,
                status text not null,
                started_at timestamptz not null default now(),
                finished_at timestamptz,
                detail jsonb not null default '{}'::jsonb
            )
            """,
            """
            insert into schema_meta(key, value) values('postgres_schema_version', '1')
            on conflict(key) do update set value = excluded.value, updated_at = now()
            """,
        ]
        conn = await self._connect()
        try:
            for statement in statements:
                await conn.execute(statement)
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)[:300]
            raise
        finally:
            await conn.close()

    async def health(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, "disabled"
        if asyncpg is None:
            self.last_error = "asyncpg is not installed"
            return False, self.last_error
        try:
            conn = await self._connect()
            try:
                value = await conn.fetchval("select 1")
            finally:
                await conn.close()
            self.last_error = None
            return value == 1, None
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False, self.last_error

    async def _connect(self):
        if asyncpg is None:
            raise RuntimeError("asyncpg is not installed")
        return await asyncpg.connect(
            host=self.settings.postgres_host,
            port=self.settings.postgres_port,
            database=self.settings.postgres_db,
            user=self.settings.postgres_user,
            password=self.settings.postgres_password,
            timeout=self.settings.postgres_timeout_seconds,
        )


class RedisInfra:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.redis_enabled
        self.last_error: str | None = None
        self._client = None
        if self.enabled and redis_async is not None:
            self._client = redis_async.from_url(
                settings.redis_url,
                socket_timeout=settings.redis_timeout_seconds,
                socket_connect_timeout=settings.redis_timeout_seconds,
                decode_responses=True,
            )
        elif self.enabled:
            self.last_error = "redis package is not installed"

    async def health(self) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, "disabled"
        if self._client is None:
            return False, self.last_error or "redis client not initialized"
        try:
            pong = await self._client.ping()
            if pong:
                await self._client.set(f"{self.settings.redis_key_prefix}:health", "ok", ex=60)
            self.last_error = None
            return bool(pong), None
        except Exception as exc:
            self.last_error = str(exc)[:300]
            return False, self.last_error

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
