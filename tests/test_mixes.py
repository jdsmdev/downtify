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
from downtify.discover import DiscoverStore, artist_key

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


def test_new_for_you_filters_children_by_genre():
    seeds = [{'artist': 'Kids Artist', 'title': 'Kids Song'}]
    songs = [
        {'name': 'New Kids Song', 'artists': ['Kids Band']},
        {'name': 'New Pop Song', 'artists': ['Pop Band']},
        {'name': 'Unclassified Song', 'artists': ['Unknown Band']},
    ]
    genres = {
        'New Kids Song': "Children's Music",
        'New Pop Song': 'Pop',
        'Unclassified Song': '',
    }

    def similar(_artist: str, _title: str) -> dict[str, Any]:
        return {'tracks': songs}

    def genre_for(song: dict[str, Any]) -> str:
        return genres[song['name']]

    regular = mixes.new_for_you(seeds, [], similar, genre_for=genre_for)
    kids = mixes.new_for_you(
        seeds, [], similar, genre_for=genre_for, kids_only=True
    )

    assert [song['name'] for song in regular['tracks']] == ['New Pop Song']
    assert [song['name'] for song in kids['tracks']] == ['New Kids Song']
    assert regular['partial'] is True
    assert kids['partial'] is True


def test_new_kids_seeds_use_only_played_or_liked_kids_tracks():
    entries = [
        _tagged('kids-a.mp3', 'Kids A', genre="Children's Music", title='A'),
        _tagged('kids-b.mp3', 'Kids B', genre='Nursery Rhymes', title='B'),
        _tagged('pop.mp3', 'Pop', genre='Pop', title='Pop'),
        _tagged('unheard.mp3', 'Kids C', genre='Kids', title='Unheard'),
    ]
    plays = _plays('kids-a.mp3', 1, 2) + _plays('pop.mp3', 1, 2, 3)

    seeds = mixes.new_kids_seeds(entries, plays, {'kids-b.mp3'}, NOW)

    assert seeds == [
        {'artist': 'Kids B', 'title': 'B'},
        {'artist': 'Kids A', 'title': 'A'},
    ]


def _tagged(file: str, artist: str, **tags: str) -> dict[str, Any]:
    return {**_entry(file, artist), **tags}


def test_cluster_artists_groups_related_and_genre_alike():
    rock_a, rock_b = artist_key('Rock A'), artist_key('Rock B')
    jazz, jazz_extra = artist_key('Jazz C'), artist_key('Jazz Extra')
    seeds = [(rock_a, 'Rock A', 9.0), (jazz, 'Jazz C', 6.0)]
    seeds.append((rock_b, 'Rock B', 2.0))

    clusters = mixes.cluster_artists(
        seeds,
        {rock_a: [{'name': 'Rock B'}]},
        {rock_a, rock_b, jazz, jazz_extra, artist_key('Loner')},
        {jazz: {'jazz'}, jazz_extra: {'jazz'}},
    )

    assert clusters == [
        {'seeds': [rock_a, rock_b], 'extra': []},
        {'seeds': [jazz], 'extra': [jazz_extra]},
    ]


def test_daily_mixes_cluster_favourites_and_mix_in_unplayed_songs():
    entries = [_tagged(f'ra{i}.mp3', 'Rock A', genre='Rock') for i in range(8)]
    entries += [
        _tagged(f'rb{i}.mp3', 'Rock B', genre='Rock') for i in range(8)
    ]
    entries += [
        _tagged(f'jc{i}.mp3', 'Jazz C', genre='Jazz') for i in range(12)
    ]
    plays = []
    for file in ('ra0.mp3', 'ra1.mp3', 'ra2.mp3'):
        plays += _plays(file, 1, 2, 3)
    for file in ('jc0.mp3', 'jc1.mp3', 'jc2.mp3'):
        plays += _plays(file, 1, 2)
    plays += _plays('rb0.mp3', 1) + _plays('rb1.mp3', 1)
    asked: list[list[str]] = []

    def related_for(names: list[str]) -> tuple[dict[str, Any], bool]:
        asked.append(names)
        return {}, False

    result = mixes.daily_mixes(entries, plays, [], related_for, NOW)

    assert asked == [['Rock A', 'Jazz C', 'Rock B']]
    assert [m['id'] for m in result['mixes']] == ['daily_1', 'daily_2']
    rock, jazz = (
        [t['file'] for t in mix['tracks']] for mix in result['mixes']
    )
    assert result['mixes'][0]['artists'] == ['Rock A', 'Rock B']
    assert {f[:2] for f in rock} == {'ra', 'rb'}
    assert len(rock) == 16
    played = {'ra0.mp3', 'ra1.mp3', 'ra2.mp3', 'rb0.mp3', 'rb1.mp3'}
    assert rock[0] in played
    assert played <= set(rock)
    assert {f[:2] for f in jazz} == {'jc'}
    assert len(jazz) == 12
    assert not set(rock) & set(jazz)
    # The same day gives the same mixes.
    assert result == mixes.daily_mixes(entries, plays, [], related_for, NOW)


def test_daily_mixes_need_listening_history():
    def related_for(names: list[str]) -> tuple[dict[str, Any], bool]:
        raise AssertionError('not asked without favourites')

    entries = [_entry('a.mp3', 'A')]
    assert mixes.daily_mixes(entries, [], [], related_for, NOW) == {
        'mixes': [],
        'partial': False,
    }


def test_decade_mixes_follow_the_most_played_decades():
    entries = [_tagged(f'n{i}.mp3', f'N{i}', year='1995') for i in range(25)]
    entries += [
        _tagged(f'z{i}.mp3', f'Z{i}', year='2004-05-01') for i in range(25)
    ]
    entries += [_tagged(f'e{i}.mp3', f'E{i}', year='1980') for i in range(5)]
    stats = mixes.track_stats(_plays('z3.mp3', 1, 2), NOW)

    picked = mixes.decade_mixes(entries, stats, set(), NOW)

    assert [decade for decade, _files in picked] == [2000, 1990]
    assert picked[0][1][0] == 'z3.mp3'
    assert len(picked[0][1]) == 25


def test_kids_genres_are_classified_without_matching_song_titles():
    assert mixes.is_kids_track(
        _tagged('a.mp3', 'Artist', genre="Children's Music")
    )
    assert mixes.is_kids_track(
        _tagged('b.mp3', 'Artist', genre='Música infantil')
    )
    assert mixes.is_kids_track(
        _tagged('c.mp3', 'Artist', genre='Pop; Nursery Rhymes')
    )
    assert not mixes.is_kids_track(
        _tagged(
            'children.mp3', 'Artist', genre='Pop', title='Children of the Sun'
        )
    )


def test_general_mixes_and_new_seeds_leave_out_kids_tracks():
    kids = [
        _tagged(
            f'kid{i}.mp3',
            'Children Artist',
            genre="Children's Music",
            year='1995',
        )
        for i in range(22)
    ]
    adults = [
        _tagged(f'adult{i}.mp3', f'Adult {i}', genre='Pop', year='1995')
        for i in range(22)
    ]
    entries = kids + adults
    plays = _plays('kid0.mp3', 1, 2, 100, 101, 102)
    plays += _plays('adult0.mp3', 1, 2, 100, 101, 102)

    built = mixes.build_mixes(entries, plays, [], NOW)
    seeds = mixes.new_seeds(entries, plays, NOW)

    assert all(
        not mixes.is_kids_track(track)
        for mix in built
        for track in mix['tracks']
    )
    assert seeds == [{'artist': 'Adult 0', 'title': 'adult0.mp3'}]


def test_daily_mixes_make_a_separate_kids_mix_without_regular_seeds():
    kids = [
        _tagged(f'kid{i}.mp3', 'Children Artist', genre="Children's Music")
        for i in range(8)
    ]

    def related_for(_names: list[str]) -> tuple[dict[str, Any], bool]:
        raise AssertionError('no regular artists need a related lookup')

    result = mixes.daily_mixes(kids, [], [], related_for, NOW)

    assert [mix['id'] for mix in result['mixes']] == ['daily_kids']
    assert len(result['mixes'][0]['tracks']) == len(kids)
    assert all(
        mixes.is_kids_track(track) for track in result['mixes'][0]['tracks']
    )


def test_daily_mix_keeps_kids_out_of_regular_mix_and_adds_their_mix():
    kids = [
        _tagged(f'kid{i}.mp3', 'Children Artist', genre="Children's Music")
        for i in range(8)
    ]
    adults = [
        _tagged(f'pop{i}.mp3', 'Adult Artist', genre='Pop') for i in range(12)
    ]
    plays = _plays('kid0.mp3', 1, 2) + _plays('pop0.mp3', 1, 2)

    result = mixes.daily_mixes(
        kids + adults, plays, [], lambda _names: ({}, False), NOW
    )
    by_id = {mix['id']: mix['tracks'] for mix in result['mixes']}

    assert set(by_id) == {'daily_1', 'daily_kids'}
    assert all(not mixes.is_kids_track(track) for track in by_id['daily_1'])
    assert all(mixes.is_kids_track(track) for track in by_id['daily_kids'])


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


def test_new_for_kids_endpoint_returns_only_verified_kids_genres(
    mix_state, monkeypatch
):
    child_entry = _tagged(
        'kids.mp3', 'Kids Artist', genre="Children's Music", title='Kids Song'
    )
    monkeypatch.setattr(
        api,
        'listing_for_request',
        lambda _ctx, allowed_keys=None: [child_entry],
    )
    monkeypatch.setattr(
        api,
        'resolve_library_file',
        lambda file, _ctx: Path(file) if file == 'kids.mp3' else None,
    )
    monkeypatch.setattr(
        api.providers,
        'youtube_similar_tracks',
        lambda *_args, **_kwargs: {
            'tracks': [
                {'name': 'New Kids', 'artists': ['Kids Band']},
                {'name': 'New Pop', 'artists': ['Pop Band']},
            ]
        },
    )
    monkeypatch.setattr(
        api.itunes,
        'fetch_genre',
        lambda song: (
            "Children's Music" if song['name'] == 'New Kids' else 'Pop'
        ),
    )
    mix_state.record_listen(
        'Kids Artist', when=NOW, user_id=1, file='kids.mp3'
    )

    result = asyncio.run(api.new_for_kids_endpoint(_request()))

    assert [song['name'] for song in result['tracks']] == ['New Kids']


def test_new_for_kids_endpoint_is_empty_without_played_or_liked_kids_tracks(
    mix_state, monkeypatch
):
    monkeypatch.setattr(
        api,
        'listing_for_request',
        lambda _ctx, allowed_keys=None: [
            _tagged('pop.mp3', 'Pop', genre='Pop', title='Pop Song')
        ],
    )

    result = asyncio.run(api.new_for_kids_endpoint(_request()))

    assert result == {'seeds': [], 'tracks': [], 'partial': False}


def test_daily_mixes_endpoint_asks_for_the_favourites_related_artists(
    mix_state, monkeypatch
):
    asked: list[list[str]] = []

    def related(_store, names):
        asked.append(names)
        return {}, True

    monkeypatch.setattr(api, 'related_for_artists', related)
    asyncio.run(
        api.record_listen_endpoint(_request({'artist': 'A', 'file': 'a.mp3'}))
    )

    result = asyncio.run(api.daily_mixes_endpoint(_request()))

    assert asked == [['A']]
    assert result == {'mixes': [], 'partial': True}
