"""Mixes: playlists Downtify builds on its own from what the user plays.

Every counted listen of a library file is logged per user (see
:meth:`downtify.discover.DiscoverStore.record_listen`), and the mixes are
worked out from that log (:mod:`downtify.mix_playlists` writes them out
as playlists once a day):

* **On repeat** - what the user has been playing the most lately: plays
  in the last :data:`RECENT_DAYS`, each worth less the older it is
  (half-life :data:`RECENT_HALF_LIFE_DAYS`).
* **Forgotten favourites** - songs played at least
  :data:`FORGOTTEN_MIN_PLAYS` times (or liked and played) but not in the
  last :data:`FORGOTTEN_AFTER_DAYS`, most played first.
* **Never played** - library songs the user has never played, by the
  artists they listen to (and like) the most; a few per artist, and a
  different pick each day.
* **Daily Mix 1-6** - like Spotify's: the user's favourite artists
  grouped into clusters of similar music (Deezer's related artists, and
  shared genre tags), each mix their most played songs with a share of
  library songs from that cluster the user hasn't played yet, a new pick
  every day (see :func:`daily_mixes`; Deezer's answers are cached).
* **Kids Daily Mix** - explicitly child-focused genre-tagged tracks,
  excluded from the other library mixes, played/liked songs first.
* **Decades** - "Your 1990s" and so on: the songs of the decades the
  user listens to the most, by the year tag.

All of them are lists of library rows (the ``GET /tracks`` shape), so
they play like any playlist.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable
from datetime import datetime, timezone
from typing import Any, Optional

from .discover import artist_key
from .library_catalog import album_artist_of

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
#: Daily Mixes, at most.
DAILY_MIXES = 6
#: Favourite artists the Daily Mixes are built around.
DAILY_SEEDS = 18
#: Favourite artists per Daily Mix, at most (the rest start a new one).
DAILY_SEEDS_PER_MIX = 4
#: A Daily Mix with fewer songs than this is left out.
DAILY_MIN_TRACKS = 10
#: Share of a Daily Mix that is songs the user already plays.
DAILY_FAMILIAR_SHARE = 0.6
#: Songs per artist in each half of a Daily Mix, at most (more when the
#: mix has few artists).
DAILY_PER_ARTIST = 5
#: An artist's plays count half as much after this many days.
ARTIST_HALF_LIFE_DAYS = 30
#: Decade mixes, at most.
DECADE_MIXES = 4
#: A decade needs this many library songs for a mix.
DECADE_MIN_TRACKS = 20
#: Songs per artist in a decade mix, at most.
DECADE_PER_ARTIST = 4
#: Familiar/fresh balance for the kids' mix.
KIDS_FAMILIAR_SHARE = 0.6

MIX_IDS = ('on_repeat', 'forgotten', 'unplayed')

_GENRE_SPLIT = re.compile(r'[;,/]')
_YEAR = re.compile(r'\s*(\d{4})')
_KIDS_GENRES = frozenset({
    'child',
    'children',
    'children s',
    'children s music',
    'children s songs',
    'children music',
    'kids',
    'kids music',
    'kids songs',
    'nursery rhyme',
    'nursery rhymes',
    'lullaby',
    'lullabies',
    'preschool music',
    'music for children',
    'music for kids',
    'musica infantil',
    'canciones infantiles',
    'musique pour enfants',
    'musique enfantine',
    'musica per bambini',
    'kinderlieder',
    'kindermusik',
})

#: ``names -> ({artist key: related artists}, partial)``, like
#: :func:`downtify.discover.related_for_artists`.
RelatedFn = Callable[[list[str]], tuple[dict[str, list[dict[str, Any]]], bool]]


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


def _genre_key(value: Any) -> str:
    folded = unicodedata.normalize('NFKD', str(value or '').casefold())
    folded = ''.join(c for c in folded if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', folded).split())


def is_kids_genre(value: Any) -> bool:
    """Whether a genre label explicitly describes children's music."""

    return _genre_key(value) in _KIDS_GENRES


def is_kids_track(entry: dict[str, Any]) -> bool:
    """Whether a library track has an explicitly child-focused genre tag.

    Classification intentionally uses genre tags only: artist and title
    keywords would misclassify ordinary songs with child-related names.
    """

    return any(
        is_kids_genre(tag)
        for tag in _GENRE_SPLIT.split(str(entry.get('genre') or ''))
        if tag.strip()
    )


def _regular_entries(
    entries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [entry for entry in entries if not is_kids_track(entry)]


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
    return _capped(scored, UNPLAYED_PER_ARTIST, limit)


def _capped(
    scored: list[tuple[float, str, str]], per_artist: int, limit: int
) -> list[str]:
    """The best ``(score, artist, file)`` files, *per_artist* at most
    from one artist."""

    counts: dict[str, int] = {}
    picked: list[str] = []
    if limit <= 0:
        return picked
    for _score, artist, file in sorted(
        scored, key=lambda item: (-item[0], item[2])
    ):
        if counts.get(artist, 0) >= per_artist:
            continue
        counts[artist] = counts.get(artist, 0) + 1
        picked.append(file)
        if len(picked) >= limit:
            break
    return picked


def _decade(year: Any) -> Optional[int]:
    match = _YEAR.match(str(year or ''))
    if not match:
        return None
    value = int(match.group(1))
    return value // 10 * 10 if 1900 <= value <= 2100 else None


def decade_mixes(
    entries: Iterable[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
    limit: int = MIX_SIZE,
) -> list[tuple[int, list[str]]]:
    """``[(decade, files)]`` for the decades the user plays the most.

    A decade needs :data:`DECADE_MIN_TRACKS` library songs (by the year
    tag); the ones played (and liked) the most come first. In each mix
    the most played songs lead, and a per-day jitter rotates the rest.
    """

    now = now or _now()
    day = now.date().isoformat()
    songs: dict[int, list[tuple[float, str, str]]] = {}
    weight: dict[int, float] = {}
    for entry in entries:
        decade = _decade(entry.get('year'))
        file = _norm(entry.get('file'))
        if decade is None or not file:
            continue
        plays = int(stats.get(file, {}).get('plays', 0))
        loved = 1.0 if file in liked else 0.0
        score = math.log1p(plays) + loved + _jitter(day, file)
        artist = album_artist_of(entry).casefold()
        songs.setdefault(decade, []).append((score, artist, file))
        weight[decade] = weight.get(decade, 0.0) + plays + 2 * loved
    picked = sorted(
        (d for d, rows in songs.items() if len(rows) >= DECADE_MIN_TRACKS),
        key=lambda d: (-weight[d], -len(songs[d]), d),
    )[:DECADE_MIXES]
    return [(d, _capped(songs[d], DECADE_PER_ARTIST, limit)) for d in picked]


def build_mixes(
    entries: list[dict[str, Any]],
    plays: Iterable[dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """The library mixes as ``[{id, kind, tracks}]``: those in
    :data:`MIX_IDS` (``kind`` is the id), then the decade mixes
    (``kind`` ``decade``, plus ``decade``: ``1990``).

    *entries* are the library rows the user may see; a logged file that
    isn't among them any more (deleted, moved, someone else's) is left
    out.
    """

    now = now or _now()
    entries = _regular_entries(entries)
    liked_set = {_norm(path) for path in liked}
    stats = track_stats(plays, now)
    by_file = {_norm(entry.get('file')): entry for entry in entries}
    visible = {f: s for f, s in stats.items() if f in by_file}
    picks = {
        'on_repeat': on_repeat(visible),
        'forgotten': forgotten(visible, liked_set, now),
        'unplayed': unplayed(entries, stats, liked_set, now),
    }
    built = [
        {
            'id': mix_id,
            'kind': mix_id,
            'tracks': [by_file[f] for f in picks[mix_id]],
        }
        for mix_id in MIX_IDS
    ]
    for decade, files in decade_mixes(entries, stats, liked_set, now):
        built.append({
            'id': f'decade_{decade}',
            'kind': 'decade',
            'decade': decade,
            'tracks': [by_file[f] for f in files],
        })
    return built


def artist_weights(
    entries: Iterable[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
) -> dict[str, dict[str, Any]]:
    """``{artist key: {name, weight}}`` - how much the user listens to
    each library artist: its songs' plays, each faded by how long ago the
    song was last played (:data:`ARTIST_HALF_LIFE_DAYS`), plus its liked
    songs. Artists with no weight are left out."""

    now = now or _now()
    weights: dict[str, dict[str, Any]] = {}
    for entry in entries:
        file = _norm(entry.get('file'))
        name = album_artist_of(entry)
        key = artist_key(name)
        if not key:
            continue
        points = 2.0 if file in liked else 0.0
        entry_stats = stats.get(file)
        if entry_stats:
            age = _days(now, entry_stats['last_played'])
            fade = 0.5 ** (age / ARTIST_HALF_LIFE_DAYS)
            points += entry_stats['plays'] * fade
        if points <= 0:
            continue
        bucket = weights.setdefault(key, {'name': name, 'weight': 0.0})
        bucket['weight'] += points
    return weights


def artist_genres(entries: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    """``{artist key: genres}`` from the songs' genre tags."""

    genres: dict[str, set[str]] = {}
    for entry in entries:
        key = artist_key(album_artist_of(entry))
        tags = {
            tag.strip().casefold()
            for tag in _GENRE_SPLIT.split(str(entry.get('genre') or ''))
            if tag.strip()
        }
        if key and tags:
            genres.setdefault(key, set()).update(tags)
    return genres


def _link(
    a: str,
    b: str,
    related: dict[str, set[str]],
    genres: dict[str, set[str]],
) -> int:
    """How alike two artists are: 2 when either is the other's related
    artist, plus 1 per genre they share."""

    score = 2 if b in related.get(a, ()) or a in related.get(b, ()) else 0
    return score + len(genres.get(a, set()) & genres.get(b, set()))


def _best_cluster(
    key: str,
    clusters: list[dict[str, list[str]]],
    related: dict[str, set[str]],
    genres: dict[str, set[str]],
    *,
    open_only: bool,
) -> Optional[dict[str, list[str]]]:
    best, best_score = None, 0
    for cluster in clusters:
        if open_only and len(cluster['seeds']) >= DAILY_SEEDS_PER_MIX:
            continue
        score = sum(
            _link(key, seed, related, genres) for seed in cluster['seeds']
        )
        if score > best_score:
            best, best_score = cluster, score
    return best


def cluster_artists(
    seeds: list[tuple[str, str, float]],
    related: dict[str, list[dict[str, Any]]],
    library: Collection[str],
    genres: dict[str, set[str]],
    limit: int = DAILY_MIXES,
) -> list[dict[str, list[str]]]:
    """Group the favourite artists into at most *limit* clusters of
    similar music, as ``[{seeds, extra}]`` (artist keys).

    *seeds* are ``(key, name, weight)``, heaviest first; *related* each
    seed's related artists (Deezer's). A seed joins the cluster it's most
    alike (:func:`_link`) while that has room
    (:data:`DAILY_SEEDS_PER_MIX`), else starts a new one. Then every
    other *library* artist alike a cluster's seeds joins the closest one
    as ``extra`` - the similar artists a Daily Mix mixes in.
    """

    related_keys = {
        key: {artist_key(row.get('name')) for row in rows}
        for key, rows in related.items()
    }
    clusters: list[dict[str, list[str]]] = []
    for key, _name, _weight in seeds:
        best = _best_cluster(
            key, clusters, related_keys, genres, open_only=True
        )
        if best is not None:
            best['seeds'].append(key)
        elif len(clusters) < limit:
            clusters.append({'seeds': [key], 'extra': []})
    taken = {key for cluster in clusters for key in cluster['seeds']}
    for key in sorted(library):
        if key in taken:
            continue
        best = _best_cluster(
            key, clusters, related_keys, genres, open_only=False
        )
        if best is not None:
            best['extra'].append(key)
    return clusters


def _interleave(familiar: list[str], fresh: list[str]) -> list[str]:
    """Familiar songs with a fresh one every few, the way a Daily Mix
    plays: two of every five are fresh while both last."""

    out: list[str] = []
    fam, new = list(familiar), list(fresh)
    position = 0
    while fam or new:
        want_new = position % 5 in {1, 3}
        source = new if (want_new and new) or not fam else fam
        out.append(source.pop(0))
        position += 1
    return out


def _daily_files(
    keys: list[str],
    by_artist: dict[str, list[str]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    weights: dict[str, dict[str, Any]],
    day: str,
    used: set[str],
    limit: int = MIX_SIZE,
) -> list[str]:
    familiar: list[tuple[float, str, str]] = []
    fresh: list[tuple[float, str, str]] = []
    for key in keys:
        affinity = math.log1p(weights.get(key, {}).get('weight', 0.0))
        for file in by_artist.get(key, []):
            if file in used:
                continue
            jitter = _jitter(day, file)
            plays = int(stats.get(file, {}).get('plays', 0))
            if plays or file in liked:
                loved = 1.0 if file in liked else 0.0
                score = math.log1p(plays) + loved + jitter
                familiar.append((score, key, file))
            else:
                fresh.append((affinity + jitter, key, file))
    # Few artists in a cluster may fill more of it each.
    per_artist = max(DAILY_PER_ARTIST, math.ceil(limit / max(1, len(keys))))
    want = round(limit * DAILY_FAMILIAR_SHARE)
    known = _capped(familiar, per_artist, want)
    new = _capped(fresh, per_artist, limit - len(known))
    if len(known) + len(new) < limit:
        known = _capped(familiar, per_artist, limit - len(new))
    return _interleave(known, new)


def _favourite_artists(
    weights: dict[str, dict[str, Any]], limit: int = DAILY_SEEDS
) -> list[tuple[str, str, float]]:
    ranked = sorted(
        weights.items(),
        key=lambda item: (-item[1]['weight'], item[1]['name'].casefold()),
    )[:limit]
    return [(key, value['name'], value['weight']) for key, value in ranked]


def _index_by_artist(
    entries: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    """``(row by file, files by artist key, name by artist key)``."""

    by_file: dict[str, dict[str, Any]] = {}
    by_artist: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for entry in entries:
        file = _norm(entry.get('file'))
        name = album_artist_of(entry)
        key = artist_key(name)
        if not file or not key:
            continue
        by_file[file] = entry
        by_artist.setdefault(key, []).append(file)
        names.setdefault(key, name)
    return by_file, by_artist, names


def daily_mixes(
    entries: list[dict[str, Any]],
    plays: Iterable[dict[str, Any]],
    liked: Collection[str],
    related_for: RelatedFn,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Spotify-style Daily Mixes: ``{mixes, partial}``.

    The user's :data:`DAILY_SEEDS` heaviest non-kids artists
    (:func:`artist_weights`) are grouped into clusters of similar music
    (:func:`cluster_artists`); each cluster's mix is about
    :data:`DAILY_FAMILIAR_SHARE` songs the user already plays or likes,
    the rest library songs of the same artists (and the similar ones in
    the library) never played, interleaved, with a per-day jitter so it
    changes daily. A song is only in one Daily Mix; a cluster with fewer
    than :data:`DAILY_MIN_TRACKS` songs makes none.

    Each mix is ``{id, kind: 'daily', number, artists, tracks}`` -
    ``artists`` up to three names to show for it. ``partial`` when the
    related artists couldn't all be fetched (genre tags still group
    them).
    """

    now = now or _now()
    kids_entries = [entry for entry in entries if is_kids_track(entry)]
    regular_entries = _regular_entries(entries)
    liked_set = {_norm(path) for path in liked}
    stats = track_stats(plays, now)
    mixes, partial = _regular_daily_mixes(
        regular_entries, stats, liked_set, related_for, now
    )
    kids_files = kids_daily_mix(kids_entries, stats, liked_set, now)
    if kids_files:
        kids_by_file = {
            _norm(entry.get('file')): entry for entry in kids_entries
        }
        mixes.append({
            'id': 'daily_kids',
            'kind': 'kids',
            'artists': [],
            'tracks': [kids_by_file[file] for file in kids_files],
        })
    return {'mixes': mixes, 'partial': partial}


def _regular_daily_mixes(
    entries: list[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    related_for: RelatedFn,
    now: datetime,
) -> tuple[list[dict[str, Any]], bool]:
    weights = artist_weights(entries, stats, liked, now)
    seeds = _favourite_artists(weights)
    if not seeds:
        return [], False
    related, partial = related_for([name for _key, name, _weight in seeds])
    by_file, by_artist, names = _index_by_artist(entries)
    picked = _cluster_files(
        cluster_artists(
            seeds, related, set(by_artist), artist_genres(entries)
        ),
        by_artist,
        stats,
        liked,
        weights,
        now.date().isoformat(),
    )
    mixes = [
        {
            'id': f'daily_{number}',
            'kind': 'daily',
            'number': number,
            'artists': [names[key] for key in keys[:3] if key in names],
            'tracks': [by_file[f] for f in files],
        }
        for number, (keys, files) in enumerate(picked, start=1)
    ]
    return mixes, partial


def kids_daily_mix(
    entries: Iterable[dict[str, Any]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    now: Optional[datetime] = None,
    limit: int = MIX_SIZE,
) -> list[str]:
    """Daily pick of explicitly child-focused library tracks.

    Played or liked tracks lead, then never-played kids' tracks fill the
    rest; a daily deterministic shuffle rotates tracks within each group.
    All eligible songs are included when the library has fewer than the
    usual mix size, with no minimum-count threshold.
    """

    now = now or _now()
    day = now.date().isoformat()
    eligible = [
        (_norm(entry.get('file')), album_artist_of(entry).casefold())
        for entry in entries
        if is_kids_track(entry) and _norm(entry.get('file'))
    ]
    if not eligible or limit <= 0:
        return []
    limit = min(limit, len(eligible))
    artists = {artist for _file, artist in eligible}
    per_artist = max(DAILY_PER_ARTIST, math.ceil(limit / len(artists)))
    familiar: list[tuple[float, str, str]] = []
    fresh: list[tuple[float, str, str]] = []
    affinity: dict[str, float] = {}
    for file, artist in eligible:
        affinity[artist] = affinity.get(artist, 0.0) + int(
            stats.get(file, {}).get('plays', 0)
        )
    for file, artist in eligible:
        plays = int(stats.get(file, {}).get('plays', 0))
        if plays or file in liked:
            score = math.log1p(plays) + (1.0 if file in liked else 0.0)
            familiar.append((score + _jitter(day, file), artist, file))
        else:
            fresh.append((
                math.log1p(affinity[artist]) + _jitter(day, file),
                artist,
                file,
            ))
    target_familiar = round(limit * KIDS_FAMILIAR_SHARE)
    known = _capped(familiar, per_artist, target_familiar)
    new = _capped(fresh, per_artist, limit - len(known))
    if len(known) + len(new) < limit:
        known = _capped(familiar, per_artist, limit - len(new))
    return _interleave(known, new)


def _cluster_files(
    clusters: list[dict[str, list[str]]],
    by_artist: dict[str, list[str]],
    stats: dict[str, dict[str, Any]],
    liked: Collection[str],
    weights: dict[str, dict[str, Any]],
    day: str,
) -> list[tuple[list[str], list[str]]]:
    """``[(artist keys, files)]`` per cluster big enough for a mix; a
    song goes to the first mix that picks it."""

    used: set[str] = set()
    picked: list[tuple[list[str], list[str]]] = []
    for cluster in clusters:
        keys = cluster['seeds'] + cluster['extra']
        files = _daily_files(keys, by_artist, stats, liked, weights, day, used)
        if len(files) < DAILY_MIN_TRACKS:
            continue
        used.update(files)
        picked.append((keys, files))
    return picked
