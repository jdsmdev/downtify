"""Mixes kept as playlists, rebuilt daily per user (offline)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from downtify import mix_playlists
from downtify.library_catalog import LibraryContext
from downtify.m3u import is_manual_m3u
from downtify.playlist_catalog import ManualPlaylistOwners

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _entry(file: str) -> dict[str, Any]:
    return {
        'file': file,
        'artist': 'A',
        'album_artist': 'A',
        'title': file,
    }


def _plays(file: str, *days_ago: float) -> list[dict[str, Any]]:
    return [
        {'file': file, 'played_at': (NOW - timedelta(days=d)).isoformat()}
        for d in days_ago
    ]


def _related(_names: list[str]) -> tuple[dict[str, Any], bool]:
    return {}, False


def _setup(tmp_path: Path):
    download = tmp_path / 'downloads'
    for name in ('hot.mp3', 'new.mp3'):
        (download / name).parent.mkdir(parents=True, exist_ok=True)
        (download / name).write_bytes(b'')
    ctx = LibraryContext(download_dir=download)
    db = tmp_path / 'lib.db'
    return (
        ctx,
        mix_playlists.MixPlaylistStore(db),
        ManualPlaylistOwners(db),
    )


def _generate(setup, plays, user_id=2, username='ann'):
    ctx, store, owners = setup
    return mix_playlists.generate_user_mixes(
        ctx,
        store,
        owners,
        user_id=user_id,
        username=username,
        entries=[_entry('hot.mp3'), _entry('new.mp3')],
        plays=plays,
        liked=[],
        related_for=_related,
        now=NOW,
    )


def test_mixes_become_owned_manual_playlists(tmp_path):
    setup = _setup(tmp_path)
    ctx = setup[0]

    names = _generate(setup, _plays('hot.mp3', 1, 2))

    assert 'On repeat - ann' in names
    path = ctx.download_dir / 'Playlists' / 'On repeat - ann.m3u'
    assert is_manual_m3u(path)
    assert setup[2].owner('On repeat - ann') == 2
    assert setup[1].generated_on(2) == '2026-10-01'


def test_stored_mixes_read_the_playlists_back(tmp_path):
    setup = _setup(tmp_path)
    ctx, store, _owners = setup
    entries = [_entry('hot.mp3'), _entry('new.mp3')]
    _generate(setup, _plays('hot.mp3', 1, 2))

    shelf = mix_playlists.library_shelf(
        mix_playlists.stored_mixes(ctx, store, 2, entries)
    )

    by_id = {mix['id']: mix for mix in shelf}
    assert [t['file'] for t in by_id['on_repeat']['tracks']] == ['hot.mp3']
    assert by_id['on_repeat']['playlist'] == 'On repeat - ann'
    assert by_id['forgotten'] == {
        'id': 'forgotten',
        'kind': 'forgotten',
        'playlist': '',
        'tracks': [],
    }


def test_rebuilding_drops_mixes_that_no_longer_apply(tmp_path):
    setup = _setup(tmp_path)
    ctx, _store, owners = setup
    _generate(setup, _plays('hot.mp3', 1, 2))
    path = ctx.download_dir / 'Playlists' / 'On repeat - ann.m3u'
    assert path.is_file()

    _generate(setup, [])

    assert not path.exists()
    assert owners.owner('On repeat - ann') is None


def test_users_get_their_own_playlists_and_removal_cleans_up(tmp_path):
    setup = _setup(tmp_path)
    ctx, store, owners = setup
    plays = _plays('hot.mp3', 1)
    _generate(setup, plays, user_id=2, username='ann')
    _generate(setup, plays, user_id=3, username='bob')

    assert owners.owner('On repeat - ann') == 2
    assert owners.owner('On repeat - bob') == 3

    mix_playlists.remove_user_mixes(ctx, store, owners, 2)

    assert not (
        ctx.download_dir / 'Playlists' / 'On repeat - ann.m3u'
    ).exists()
    assert (ctx.download_dir / 'Playlists' / 'On repeat - bob.m3u').is_file()
    assert store.generated_on(2) is None


def test_loop_runs_the_job_after_the_delay():
    calls: list[int] = []

    async def run() -> None:
        task = asyncio.create_task(
            mix_playlists.mix_playlist_loop(
                lambda: calls.append(1), interval=60, start_delay=0
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(run())

    assert calls == [1]
