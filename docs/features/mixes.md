---
icon: lucide/repeat
---

# Mixes

**Mixes** are playlists Downtify builds on its own from what you listen to. They follow your listening as it changes: open the page again and they reflect your latest plays. No setup, no account anywhere.

## How to use it

Open **Mixes** from the sidebar (or the **More** sheet on phones). Each mix is a tile; play it straight from the tile, or open it to see its songs.

| Mix | What's in it |
|-----|--------------|
| **On repeat** | The songs you've played the most in the last 30 days. Recent plays count the most: a play counts half as much after a week. |
| **Forgotten favourites** | Songs you played at least three times (or liked and played) but haven't heard in two months, most played first. |
| **Never played** | Songs in your library you've never played, by the artists you play and like the most, at most three per artist. You get a different pick every day. |
| **New for you** | Songs that aren't in your library at all, like your current favourites. It uses YouTube Music's radio mix of your top three **On repeat** songs, one per artist. Every row plays in full and downloads, just like on [Similar](similar.md). |

On a library mix, **Save as playlist** turns what's in it right now into a regular [playlist](m3u-export.md#playlists-you-create) you can edit. The mix itself keeps changing, but the saved playlist doesn't.

## What counts as a listen

The player counts a song once half of it (or four minutes) has played. Seeking past the middle doesn't count. This is the same listen [Discover](discover.md) counts, and the [mobile apps](mobile-apps.md) report theirs too, so a song played on your phone counts here as well. Only library songs count: a streamed song that isn't downloaded doesn't.

Each account has its own mixes, built only from its own listens and likes, over the songs it can see in the library.

::: info Nothing is written to disk
Mixes are worked out from the listening history each time you open them. They aren't M3U files, so they don't show up in Navidrome or other media servers, and deleting songs never leaves them stale. Use **Save as playlist** to keep a copy.
:::

To start over, use **Clear listening history** under **Hidden artists** on the [Discover](discover.md) page. It clears the history the mixes are built from too.

## API

See [`GET /api/mixes`](../api-reference.md#get-apimixes) and [`GET /api/mixes/new`](../api-reference.md#get-apimixesnew) in the API Reference.
