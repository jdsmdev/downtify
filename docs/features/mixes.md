---
icon: lucide/repeat
---

# Mixes

**Mixes** are playlists Downtify builds on its own from what you listen to. They follow your listening as it changes: open the page again and they reflect your latest plays. No setup, no account anywhere.

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

Kids songs are identified by explicit genre tags such as **Children's Music**, **Kids**, **Nursery Rhymes**, **Lullabies** and localized equivalents such as **Música infantil**. Tagged tracks are kept out of regular Daily Mixes, **On repeat**, **Forgotten favourites**, **Never played**, decade mixes and the seeds for **New for you**. The Kids Daily Mix puts played or liked songs first, then adds tagged songs you haven't played yet. Songs without a child-focused genre tag stay in the regular mixes; titles and artist names alone are not used to guess.

## Made from your listening

| Mix | What's in it |
|-----|--------------|
| **On repeat** | The songs you've played the most in the last 30 days. Recent plays count the most: a play counts half as much after a week. |
| **Forgotten favourites** | Songs you played at least three times (or liked and played) but haven't heard in two months, most played first. |
| **Never played** | Songs in your library you've never played, by the artists you play and like the most, at most three per artist. You get a different pick every day. |
| **New for you** | Songs that aren't in your library at all, like your current favourites. It uses YouTube Music's radio mix of your top three **On repeat** songs, one per artist. Suggestions must have a known non-kids iTunes genre. Every row plays in full and downloads, just like on [Similar](similar.md). |
| **New for your kids** | Children's songs not in your library, similar to kids' tracks you play or like. Suggestions must have an iTunes genre identified as children's music; unclassified songs are left out. |

On a library mix, **Save as playlist** turns what's in it right now into a regular [playlist](m3u-export.md#playlists-you-create) you can edit. The mix itself keeps changing, but the saved playlist doesn't.

## Decades

"Your 1990s", "Your 2000s" and so on, from the year tag of your songs. A decade needs at least 20 songs in your library; the four decades you play (and like) the most get a mix, with the songs you play the most first and the rest of the decade rotating daily, at most four songs per artist.

## What counts as a listen

The player counts a song once half of it (or four minutes) has played. Seeking past the middle doesn't count. This is the same listen [Discover](discover.md) counts, and the [mobile apps](mobile-apps.md) report theirs too, so a song played on your phone counts here as well. Only library songs count: a streamed song that isn't downloaded doesn't.

Each account has its own mixes, built only from its own listens and likes, over the songs it can see in the library.

::: info Nothing is written to disk
Mixes are worked out from the listening history each time you open them. They aren't M3U files, so they don't show up in Navidrome or other media servers, and deleting songs never leaves them stale. Use **Save as playlist** to keep a copy.
:::

To start over, use **Clear listening history** under **Hidden artists** on the [Discover](discover.md) page. It clears the history the mixes are built from too.

## API

See [`GET /api/mixes`](../api-reference.md#get-apimixes), [`GET /api/mixes/daily`](../api-reference.md#get-apimixesdaily), [`GET /api/mixes/new`](../api-reference.md#get-apimixesnew) and [`GET /api/mixes/new/kids`](../api-reference.md#get-apimixesnewkids) in the API Reference.
