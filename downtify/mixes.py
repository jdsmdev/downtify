"""Mixes: playlists Downtify builds on its own from what the user plays.

Every counted listen of a library file is logged per user (see
:meth:`downtify.discover.DiscoverStore.record_listen`), and the mixes are
worked out from that log each time they are asked for - nothing is
written to disk, so they never go stale and never touch the library:

* **On repeat** - what the user has been playing the most lately: plays
  in the last :data:`RECENT_DAYS`, each worth less the older it is
  (half-life :data:`RECENT_HALF_LIFE_DAYS`).
* **Forgotten favourites** - songs played at least
  :data:`FORGOTTEN_MIN_PLAYS` times (or liked and played) but not in the
  last :data:`FORGOTTEN_AFTER_DAYS`, most played first.
* **Never played** - library songs the user has never played, by the
  artists they listen to (and like) the most; a few per artist, and a
  different pick each day.
* **New for you** - songs that aren't in the library at all, from
  YouTube Music's radio mix of the user's current favourites (see
  :func:`new_for_you`; the only one that needs the network).

The first three are lists of library rows (the ``GET /tracks`` shape),
so they play like any playlist; the last one is downloadable song rows,
like ``GET /api/similar/tracks``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Collection, Iterable
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from .library_catalog import album_artist_of, song_key

#: Songs per mix, at most.
MIX_SIZE = 50
#: Plays older than this don't count toward "On repeat".
RECENT_DAYS = 30
#: A play counts half as much toward "On repeat" after this many days.
RECENT_HALF_LIFE_DAYS = 7
#: A song not played for this long can be a forgotten favourite.
FORGOTTEN_AFTER_DAYS = 60
#: Plays a song needs (unless liked) to be a forgotten favourite.
FORGOTTEN_MIN_PLAYS = 3
#: Songs per artist in "Never played", at most.
UNPLAYED_PER_ARTIST = 3
#: Favourites "New for you" is seeded from.
NEW_SEEDS = 3
#: Similar songs asked for per seed.
NEW_PER_SEED = 25

MIX_IDS = ('on_repeat', 'forgotten', 'unplayed')

#: ``(artist, track) -> {tracks: [...]}``, like
#: :func:`downtify.providers.youtube_similar_tracks`.
SimilarFn = Callable[[str, str], dict[str, Any]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days(now: datetime, then: datetime) -> float:
    return max(0.0, (now - then).total_seconds() / 86400)


def _norm(path: Any) -> str:
    return str(path or '').strip().replace('\\', '/')


def track_stats(
    plays: Iterable[dict[str, Any]], now: Optional[datetime] = None
) -> dict[str, dict[str, Any]]:
    """``{file: {plays, last_played, recent}}`` from the play log.

    ``recent`` is the "On repeat" score: plays within
    :data:`RECENT_DAYS`, each faded by its age.
    """

    now = now or _now()
    stats: dict[str, dict[str, Any]] = {}
    for row in plays:
        file = _norm(row.get('file'))
        when = _parse_time(row.get('played_at'))
        if not file or when is None:
            continue
        entry = stats.setdefault(
            file, {'plays': 0, 'last_played': when, 'recent': 0.0}
        )
        entry['plays'] += 1
        entry['last_played'] = max(entry['last_played'], when)
        age = _days(now, when)
        if age <= RECENT_DAYS:
            entry['recent'] += 0.5 ** (age / RECENT_HALF_LIFE_DAYS)
    return stats


def on_repeat(
    stats: dict[str, dict[str, Any]], limit: int = MIX_SIZE
) -> list[str]:
    """Files played lately, the most (and most recently) played first."""

    ranked = sorted(
        (item for item in stats.items() if item[1]['recent'] > 0),
        key=lambda item: (-item[1]['recent'], -item[1]['plays'], item[0]),
    )
    return [file for file, _stats in ranked[:limit]]


def forgotten(
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
    limit: int = MIX_SIZE,
) -> list[str]:
    """Files the user loved but hasn't played in a while."""

    now = now or _now()
    picked = [
        (file, entry)
        for file, entry in stats.items()
        if _days(now, entry['last_played']) >= FORGOTTEN_AFTER_DAYS
        and (entry['plays'] >= FORGOTTEN_MIN_PLAYS or file in liked)
    ]
    picked.sort(
        key=lambda item: (
            -item[1]['plays'],
            item[1]['last_played'],
            item[0],
        )
    )
    return [file for file, _entry in picked[:limit]]


def _jitter(day: str, file: str) -> float:
    """A stable number in ``[0, 1)`` per day and file."""

    digest = hashlib.sha256(f'{day}|{file}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big') / 2**64


def unplayed(
    entries: Iterable[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
    limit: int = MIX_SIZE,
) -> list[str]:
    """Library files never played, by the user's favourite artists first.

    An artist's affinity grows with how often its other songs were played
    and liked; a per-day jitter decides between songs of equal standing,
    so the mix changes every day. With no history yet it is simply a
    daily random pick.
    """

    now = now or _now()
    day = now.date().isoformat()
    rows = [(entry, _norm(entry.get('file'))) for entry in entries]
    affinity: dict[str, float] = {}
    for entry, file in rows:
        artist = album_artist_of(entry).casefold()
        if not artist:
            continue
        points = float(stats.get(file, {}).get('plays', 0))
        if file in liked:
            points += 3.0
        affinity[artist] = affinity.get(artist, 0.0) + points

    scored: list[tuple[float, str, str]] = []
    for entry, file in rows:
        if not file or file in stats:
            continue
        artist = album_artist_of(entry).casefold()
        score = math.log1p(affinity.get(artist, 0.0)) + _jitter(day, file)
        scored.append((score, artist, file))
    scored.sort(key=lambda item: (-item[0], item[2]))

    per_artist: dict[str, int] = {}
    picked: list[str] = []
    for _score, artist, file in scored:
        if per_artist.get(artist, 0) >= UNPLAYED_PER_ARTIST:
            continue
        per_artist[artist] = per_artist.get(artist, 0) + 1
        picked.append(file)
        if len(picked) >= limit:
            break
    return picked


def build_mixes(
    entries: list[dict[str, Any]],
    plays: Iterable[dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """The library mixes as ``[{id, tracks}]`` (see :data:`MIX_IDS`).

    *entries* are the library rows the user may see; a logged file that
    isn't among them any more (deleted, moved, someone else's) is left
    out.
    """

    now = now or _now()
    liked_set = {_norm(path) for path in liked}
    stats = track_stats(plays, now)
    by_file = {_norm(entry.get('file')): entry for entry in entries}
    visible = {f: s for f, s in stats.items() if f in by_file}
    picks = {
        'on_repeat': on_repeat(visible),
        'forgotten': forgotten(visible, liked_set, now),
        'unplayed': unplayed(entries, stats, liked_set, now),
    }
    return [
        {'id': mix_id, 'tracks': [by_file[f] for f in picks[mix_id]]}
        for mix_id in MIX_IDS
    ]


def new_seeds(
    entries: list[dict[str, Any]],
    plays: Iterable[dict[str, Any]],
    now: Optional[datetime] = None,
    limit: int = NEW_SEEDS,
) -> list[dict[str, str]]:
    """``[{artist, title}]`` to seed "New for you": the top "On repeat"
    songs (all-time favourites when nothing was played lately), one per
    artist."""

    stats = track_stats(plays, now)
    by_file = {_norm(entry.get('file')): entry for entry in entries}
    visible = {f: s for f, s in stats.items() if f in by_file}
    ranked = on_repeat(visible, limit=MIX_SIZE)
    if not ranked:
        ranked = sorted(visible, key=lambda f: (-visible[f]['plays'], f))
    seeds: list[dict[str, str]] = []
    artists: set[str] = set()
    for file in ranked:
        entry = by_file[file]
        artist = str(entry.get('artist') or '').split(';')[0].strip()
        title = str(entry.get('title') or '').strip()
        if not artist or not title or artist.casefold() in artists:
            continue
        artists.add(artist.casefold())
        seeds.append({'artist': artist, 'title': title})
        if len(seeds) >= limit:
            break
    return seeds


def _song_key_of(song: dict[str, Any]) -> str:
    artists = song.get('artists')
    artist = (
        str(artists[0] or '')
        if isinstance(artists, list) and artists
        else str(song.get('artist') or '')
    )
    return song_key(artist, str(song.get('name') or song.get('title') or ''))


def new_for_you(
    seeds: list[dict[str, str]],
    entries: Iterable[dict[str, Any]],
    similar: SimilarFn,
    limit: int = MIX_SIZE,
) -> dict[str, Any]:
    """Songs like the *seeds* that aren't in the library.

    Each seed's similar songs are interleaved, so every favourite gets a
    say near the top; library songs and repeats are dropped. A seed
    YouTube can't answer for is skipped (``partial`` says so).
    """

    owned = {
        song_key(str(e.get('artist') or ''), str(e.get('title') or ''))
        for e in entries
    }
    lists: list[list[dict[str, Any]]] = []
    partial = False
    for seed in seeds:
        try:
            answer = similar(seed['artist'], seed['title'])
        except ValueError as exc:
            logger.debug('New for you: no mix for {}: {}', seed, exc)
            partial = True
            continue
        lists.append(list(answer.get('tracks') or []))

    tracks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position in range(max((len(songs) for songs in lists), default=0)):
        for songs in lists:
            if position >= len(songs):
                continue
            song = songs[position]
            key = _song_key_of(song)
            if key == '|' or key in owned or key in seen:
                continue
            seen.add(key)
            tracks.append(song)
            if len(tracks) >= limit:
                return {'seeds': seeds, 'tracks': tracks, 'partial': partial}
    return {'seeds': seeds, 'tracks': tracks, 'partial': partial}
