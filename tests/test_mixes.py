"""Mixes: playlists built from the per-user play log (no network - the
YouTube Music radio is stubbed)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request

from downtify import api, mixes
from downtify.auth import Principal
from downtify.discover import DiscoverStore

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

_ADMIN = Principal('device', 'client', '', 1, 'admin', 'admin')


def _request(payload: Any = None) -> Request:
    body = json.dumps(payload if payload is not None else {}).encode()

    async def receive() -> dict[str, Any]:
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(
        {
            'type': 'http',
            'method': 'POST',
            'headers': [],
            'state': {'principal': _ADMIN},
        },
        receive,
    )


def _entry(file: str, artist: str, title: str = '') -> dict[str, Any]:
    return {
        'file': file,
        'artist': artist,
        'album_artist': artist,
        'title': title or file,
    }


def _plays(file: str, *days_ago: float) -> list[dict[str, Any]]:
    return [
        {'file': file, 'played_at': (NOW - timedelta(days=d)).isoformat()}
        for d in days_ago
    ]


# ── the store ─────────────────────────────────────────────────────────


def test_store_logs_track_plays_once_per_play_id(tmp_path: Path):
    store = DiscoverStore(tmp_path / 'lib.db')

    store.record_listen('Air', play_id='p1', user_id=2, file='a\\b.mp3')
    store.record_listen('Air', play_id='p1', user_id=2, file='a\\b.mp3')
    store.record_listen('Air', user_id=2)
    store.record_listen('Air', user_id=3, file='c.mp3')

    assert [row['file'] for row in store.track_plays(2)] == ['a/b.mp3']
    assert [row['file'] for row in store.track_plays(3)] == ['c.mp3']


def test_clearing_and_removing_forget_track_plays(tmp_path: Path):
    store = DiscoverStore(tmp_path / 'lib.db')
    store.record_listen('Air', user_id=2, file='a.mp3')
    store.record_listen('Air', user_id=3, file='b.mp3')

    store.clear_listens(2)
    store.remove_user(3)

    assert store.track_plays(2) == []
    assert store.track_plays(3) == []


# ── the mixes ─────────────────────────────────────────────────────────


def test_on_repeat_favours_recent_and_frequent_plays():
    plays = (
        _plays('old.mp3', 25, 26, 27, 28)
        + _plays('hot.mp3', 0, 1, 2)
        + _plays('stale.mp3', 90, 91, 92, 93, 94)
    )
    stats = mixes.track_stats(plays, NOW)

    assert mixes.on_repeat(stats) == ['hot.mp3', 'old.mp3']


def test_forgotten_needs_old_plays_and_enough_of_them_or_a_like():
    plays = (
        _plays('loved.mp3', 100, 101, 102, 103)
        + _plays('once.mp3', 100)
        + _plays('liked.mp3', 80)
        + _plays('current.mp3', 1, 100, 101)
    )
    stats = mixes.track_stats(plays, NOW)

    assert mixes.forgotten(stats, {'liked.mp3'}, NOW) == [
        'loved.mp3',
        'liked.mp3',
    ]


def test_unplayed_skips_played_files_and_leans_on_favourite_artists():
    entries = [_entry('fav-1.mp3', 'Fav'), _entry('other-1.mp3', 'Other')]
    entries += [_entry(f'fav-new-{i}.mp3', 'Fav') for i in range(5)]
    entries += [_entry(f'other-new-{i}.mp3', 'Other') for i in range(5)]
    stats = mixes.track_stats(_plays('fav-1.mp3', 1, 2, 3, 4, 5), NOW)

    picked = mixes.unplayed(entries, stats, set(), NOW)

    assert 'fav-1.mp3' not in picked
    assert all(file.startswith('fav-new') for file in picked[:3])
    assert sum(file.startswith('fav-new') for file in picked) == 3
    # The same day gives the same pick.
    assert picked == mixes.unplayed(entries, stats, set(), NOW)


def test_build_mixes_drops_files_missing_from_the_library():
    entries = [_entry('here.mp3', 'A')]
    plays = _plays('here.mp3', 1) + _plays('gone.mp3', 1, 2)

    built = {
        mix['id']: [t['file'] for t in mix['tracks']]
        for mix in mixes.build_mixes(entries, plays, [], NOW)
    }

    assert built == {
        'on_repeat': ['here.mp3'],
        'forgotten': [],
        'unplayed': [],
    }


def test_new_for_you_interleaves_seeds_and_skips_the_library():
    entries = [_entry('a.mp3', 'A', 'Song A'), _entry('b.mp3', 'B', 'Song B')]
    seeds = mixes.new_seeds(
        entries, _plays('a.mp3', 1, 2) + _plays('b.mp3', 1), NOW
    )
    assert seeds == [
        {'artist': 'A', 'title': 'Song A'},
        {'artist': 'B', 'title': 'Song B'},
    ]

    def similar(artist: str, title: str) -> dict[str, Any]:
        if artist == 'B':
            raise ValueError('no match')
        return {
            'tracks': [
                {'name': 'Song B', 'artists': ['B']},
                {'name': 'New 1', 'artists': ['X']},
                {'name': 'New 1', 'artists': ['X']},
                {'name': 'New 2', 'artists': ['Y']},
            ]
        }

    result = mixes.new_for_you(seeds, entries, similar)

    assert [song['name'] for song in result['tracks']] == ['New 1', 'New 2']
    assert result['partial'] is True


# ── endpoints ─────────────────────────────────────────────────────────


@pytest.fixture
def mix_state(monkeypatch, tmp_path):
    store = DiscoverStore(tmp_path / 'lib.db')
    library = [_entry('a.mp3', 'A', 'Song A'), _entry('b.mp3', 'B', 'Song B')]
    monkeypatch.setattr(api.state, 'discover', store)
    monkeypatch.setattr(api.state, 'likes', None)
    monkeypatch.setattr(api.state, 'library_sync', None)
    monkeypatch.setattr(api, 'library_context', lambda: None)
    monkeypatch.setattr(
        api,
        'resolve_library_file',
        lambda file, _ctx: Path(file) if file in {'a.mp3', 'b.mp3'} else None,
    )
    monkeypatch.setattr(
        api, 'listing_for_request', lambda _ctx, allowed_keys=None: library
    )
    return store


def test_listen_endpoint_logs_only_library_files(mix_state):
    asyncio.run(
        api.record_listen_endpoint(_request({'artist': 'A', 'file': 'a.mp3'}))
    )
    asyncio.run(
        api.record_listen_endpoint(
            _request({'artist': 'A', 'file': '../etc/passwd'})
        )
    )

    plays = mix_state.track_plays(api.request_user_id(_request()))
    assert [row['file'] for row in plays] == ['a.mp3']


def test_mixes_endpoint_builds_from_logged_listens(mix_state):
    asyncio.run(
        api.record_listen_endpoint(_request({'artist': 'A', 'file': 'a.mp3'}))
    )

    result = asyncio.run(api.mixes_endpoint(_request()))

    by_id = {mix['id']: mix['tracks'] for mix in result['mixes']}
    assert [t['file'] for t in by_id['on_repeat']] == ['a.mp3']
    assert [t['file'] for t in by_id['unplayed']] == ['b.mp3']


def test_new_for_you_endpoint_is_empty_without_listens(mix_state):
    assert asyncio.run(api.new_for_you_endpoint(_request())) == {
        'seeds': [],
        'tracks': [],
        'partial': False,
    }
