---
icon: lucide/repeat
---

# Mixes

**Mixes** are playlists Downtify builds on its own from what you listen to. Every day a background job rebuilds them as real [playlists](m3u-export.md#playlists-you-create), one set per account, so they show up in the Library, in Navidrome and in the apps like any other playlist. No setup, no account anywhere.

## How to use it

Open **Mixes** from the sidebar (or the **More** sheet on phones). Each mix is a tile; play it straight from the tile, or open it to see its songs. The page has up to three shelves: **Your Daily Mixes**, the mixes made from your listening, and **Decades**.

## Daily Mixes

Like Spotify's Daily Mixes: up to six mixes, each built around a group of your favourite artists that sound alike. A separate **Kids Daily Mix** gathers child-focused music from your library, even before you've listened to it.

1. Your favourite artists are the ones you play the most (recent plays count more: a play counts half as much after a month) and like the most. The top 18 are used.
2. They are grouped by how alike they are: Deezer's "related artists" for each one (the same lookup [Discover](discover.md) uses, cached for a week), and the genre tags their songs share. A group holds up to four favourites; the rest start a new one.
3. Other artists in your library that are alike a group's favourites join it too, so a mix also brings in similar music you have but rarely play.
4. Each mix is about 60% songs you already play or like, and 40% library songs from the same artists you've never played, interleaved. A song is only ever in one Daily Mix, and a group with fewer than 10 songs makes none.

The tile shows the first artists in the mix ("Portishead, Massive Attack and more"). Daily Mixes change every day, and follow your listening as it changes.

::: tip Genre tags help
When Deezer can't be reached, artists are still grouped by the genre tags in your files. Tagging genres (or letting [Upgrade library](library-upgrade.md) fill tags in) makes the groups better either way.
:::

Kids songs are identified by explicit genre tags such as **Children's Music**, **Kids**, **Nursery Rhymes**, **Lullabies** and localized equivalents such as **Música infantil**. Tagged tracks are kept out of regular Daily Mixes, **On repeat**, **Forgotten favourites**, **Never played**, decade mixes. The Kids Daily Mix puts played or liked songs first, then adds tagged songs you haven't played yet. Songs without a child-focused genre tag stay in the regular mixes; titles and artist names alone are not used to guess.

## Made from your listening

| Mix | What's in it |
|-----|--------------|
| **On repeat** | The songs you've played the most in the last 30 days. Recent plays count the most: a play counts half as much after a week. |
| **Forgotten favourites** | Songs you played at least three times (or liked and played) but haven't heard in two months, most played first. |
| **Never played** | Songs in your library you've never played, by the artists you play and like the most, at most three per artist. You get a different pick every day. |

On a library mix, **Save as playlist** copies what's in it right now into a regular playlist that tomorrow's rebuild won't touch.

## Decades

"Your 1990s", "Your 2000s" and so on, from the year tag of your songs. A decade needs at least 20 songs in your library; the four decades you play (and like) the most get a mix, with the songs you play the most first and the rest of the decade rotating daily, at most four songs per artist.

## What counts as a listen

The player counts a song once half of it (or four minutes) has played. Seeking past the middle doesn't count. This is the same listen [Discover](discover.md) counts, and the [mobile apps](mobile-apps.md) report theirs too, so a song played on your phone counts here as well. Only library songs count: a streamed song that isn't downloaded doesn't.

Each account has its own mixes, built only from its own listens and likes, over the songs it can see in the library.

::: info Mixes are playlists, rebuilt daily
The mixes are written as M3U playlists named like **Daily Mix 1 - alice** (the account's name is added because playlist names are shared). The server rebuilds them once a day (UTC), starting shortly after it boots, and **Refresh** on the Mixes page rebuilds yours right away. Each rebuild overwrites the playlist, so edits to a mix don't last; a mix that no longer applies is removed, and deleting an account removes its mixes. Playlists never delete songs, so removing a mix never touches your library.
:::

To start over, use **Clear listening history** under **Hidden artists** on the [Discover](discover.md) page. It clears the history the mixes are built from too.

## API

See [`GET /api/mixes`](../api-reference.md#get-apimixes) and [`GET /api/mixes/daily`](../api-reference.md#get-apimixesdaily) in the API Reference.
