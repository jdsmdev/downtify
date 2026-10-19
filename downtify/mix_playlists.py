"""Mixes kept as real playlists, rebuilt once a day for every user.

:mod:`downtify.mixes` works out the lists; this module writes each one as
a manual (M3U) playlist owned by the user it was made for, so mixes show
up wherever playlists do. A background loop (:func:`mix_playlist_loop`)
rebuilds them when the UTC day changes; ``GET /api/mixes`` and
``GET /api/mixes/daily`` read the playlists back instead of computing
anything. Only the mixes made of library songs are playlists - "New for
you" suggests songs that aren't in the library, so it stays live.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Collection, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from . import m3u, mixes
from .library_catalog import LibraryContext
from .manual_playlists import (
    ManualPlaylistError,
    drop_manual_playlist,
    read_playlist_files,
    write_generated_playlist,
)
from .playlist_catalog import ManualPlaylistOwners
from .sqlite_utils import connect_sqlite

#: How often the loop checks whether a new day has started.
LOOP_INTERVAL = 3600
#: Wait after startup so the library listing is warm first.
START_DELAY = 120

_LABELS = {
    'on_repeat': 'On repeat',
    'forgotten': 'Forgotten favourites',
    'unplayed': 'Never played',
    'kids': 'Kids Daily Mix',
}
_META_KEYS = ('kind', 'number', 'artists', 'decade')
_DAILY_KINDS = ('daily', 'kids')


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def mix_label(mix: dict[str, Any]) -> str:
    kind = mix.get('kind')
    if kind == 'decade':
        return f'Your {mix.get("decade")}s'
    if kind == 'daily':
        return f'Daily Mix {mix.get("number")}'
    return _LABELS.get(str(mix.get('id')), str(mix.get('id')))


def playlist_name(label: str, username: str) -> str:
    """Playlist names are global, so each user's mix carries their name."""

    return f'{label} - {username}' if username else label


class MixPlaylistStore:
    """Which playlists are a user's mixes, and when they were last made."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mix_playlists (
                    user_id INTEGER NOT NULL,
                    mix_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    meta TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (user_id, mix_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mix_playlist_runs (
                    user_id INTEGER PRIMARY KEY,
                    generated_on TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._path, row_factory=True)

    def generated_on(self, user_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                'SELECT generated_on FROM mix_playlist_runs WHERE user_id = ?',
                (int(user_id),),
            ).fetchone()
        return str(row['generated_on']) if row else None

    def entries(self, user_id: int) -> list[dict[str, Any]]:
        """``[{mix_id, name, meta}]`` in the order they were made."""

        with self._connect() as conn:
            rows = conn.execute(
                'SELECT mix_id, name, meta FROM mix_playlists '
                'WHERE user_id = ? ORDER BY position',
                (int(user_id),),
            ).fetchall()
        return [
            {
                'mix_id': str(row['mix_id']),
                'name': str(row['name']),
                'meta': json.loads(row['meta']),
            }
            for row in rows
        ]

    def replace(
        self, user_id: int, rows: Iterable[dict[str, Any]], day: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                'DELETE FROM mix_playlists WHERE user_id = ?', (int(user_id),)
            )
            conn.executemany(
                'INSERT INTO mix_playlists '
                '(user_id, mix_id, name, meta, position) '
                'VALUES (?, ?, ?, ?, ?)',
                [
                    (
                        int(user_id),
                        row['mix_id'],
                        row['name'],
                        json.dumps(row['meta']),
                        position,
                    )
                    for position, row in enumerate(rows)
                ],
            )
            conn.execute(
                'INSERT INTO mix_playlist_runs (user_id, generated_on) '
                'VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET '
                'generated_on = excluded.generated_on',
                (int(user_id), day),
            )

    def forget_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                'DELETE FROM mix_playlists WHERE user_id = ?', (int(user_id),)
            )
            conn.execute(
                'DELETE FROM mix_playlist_runs WHERE user_id = ?',
                (int(user_id),),
            )


def _drop(
    ctx: LibraryContext, owners: Optional[ManualPlaylistOwners], name: str
) -> None:
    try:
        drop_manual_playlist(ctx, name)
    except ManualPlaylistError as exc:
        logger.debug('Mix playlist {!r} not removed: {}', name, exc)
    if owners is not None:
        owners.forget_owner(name)


def generate_user_mixes(
    ctx: LibraryContext,
    store: MixPlaylistStore,
    owners: Optional[ManualPlaylistOwners],
    *,
    user_id: int,
    username: str,
    entries: list[dict[str, Any]],
    plays: list[dict[str, Any]],
    liked: Collection[str],
    related_for: mixes.RelatedFn,
    now: Optional[datetime] = None,
) -> list[str]:
    """Write *user_id*'s library mixes as playlists and drop the ones that
    no longer apply. Returns the playlist names."""

    now = now or datetime.now(timezone.utc)
    built = mixes.build_mixes(entries, plays, liked, now)
    built += mixes.daily_mixes(entries, plays, liked, related_for, now)[
        'mixes'
    ]
    previous = {row['name'].casefold() for row in store.entries(user_id)}
    kept: list[dict[str, Any]] = []
    for mix in built:
        files = [
            str(track.get('file') or '').replace('\\', '/')
            for track in mix['tracks']
        ]
        if not files:
            continue
        name = playlist_name(mix_label(mix), username)
        taken = m3u.find_m3u_for_name(ctx.download_dir, name) is not None
        if taken and name.casefold() not in previous:
            logger.warning('Mix playlist {!r}: name already in use', name)
            continue
        written = write_generated_playlist(ctx, name, files)
        if owners is not None:
            owners.set_owner(written, user_id)
        kept.append({
            'mix_id': mix['id'],
            'name': written,
            'meta': {k: mix[k] for k in _META_KEYS if k in mix},
        })
    current = {row['name'].casefold() for row in kept}
    for row in store.entries(user_id):
        if row['name'].casefold() not in current:
            _drop(ctx, owners, row['name'])
    store.replace(user_id, kept, now.date().isoformat())
    return [row['name'] for row in kept]


def remove_user_mixes(
    ctx: LibraryContext,
    store: MixPlaylistStore,
    owners: Optional[ManualPlaylistOwners],
    user_id: int,
) -> None:
    """Delete a removed account's mix playlists."""

    for row in store.entries(user_id):
        _drop(ctx, owners, row['name'])
    store.forget_user(user_id)


def stored_mixes(
    ctx: LibraryContext,
    store: MixPlaylistStore,
    user_id: int,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The user's mixes as ``{id, playlist, tracks, ...}``, read from
    their playlists; files no longer in *entries* are left out."""

    by_file = {
        str(entry.get('file') or '').replace('\\', '/'): entry
        for entry in entries
    }
    found: list[dict[str, Any]] = []
    for row in store.entries(user_id):
        files = read_playlist_files(ctx, row['name'])
        if files is None:
            continue
        found.append({
            'id': row['mix_id'],
            **row['meta'],
            'playlist': row['name'],
            'tracks': [by_file[f] for f in files if f in by_file],
        })
    return found


def library_shelf(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``GET /api/mixes`` list: the fixed mixes (empty when there is
    nothing for them) and then the decades."""

    by_id = {mix['id']: mix for mix in stored}
    shelf = [
        by_id.get(mix_id)
        or {'id': mix_id, 'kind': mix_id, 'playlist': '', 'tracks': []}
        for mix_id in mixes.MIX_IDS
    ]
    return shelf + [mix for mix in stored if mix.get('kind') == 'decade']


def daily_shelf(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``GET /api/mixes/daily`` list: Daily Mixes and the kids' one."""

    return [mix for mix in stored if mix.get('kind') in _DAILY_KINDS]


async def mix_playlist_loop(
    run_due: Callable[[], Any],
    interval: float = LOOP_INTERVAL,
    start_delay: float = START_DELAY,
) -> None:
    """Background task: call *run_due* (which rebuilds the mixes of every
    user not yet done today) every *interval* seconds."""

    await asyncio.sleep(start_delay)
    while True:
        try:
            await asyncio.to_thread(run_due)
        except Exception:
            logger.exception('Unexpected error in mix playlist loop')
        await asyncio.sleep(interval)
