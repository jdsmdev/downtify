// Mixes: playlists the server builds from what the user plays - see
// downtify/mixes.py. "On repeat", "Forgotten favourites", "Never
// played", the decade mixes and the Daily Mixes are library tracks; "New
// for you" is songs not in the library yet, played (streamed) and
// downloaded like the Similar page's.
import { ref, shallowRef } from 'vue'

import API from '/src/model/api'
import { normalizeTrack } from '/src/lib/library'

const mixes = shallowRef([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')

const daily = shallowRef([])
const dailyLoading = ref(false)
const dailyLoaded = ref(false)
const dailyError = ref('')

const newSongs = shallowRef([])
const newSeeds = shallowRef([])
const newPartial = ref(false)
const newLoading = ref(false)
const newLoaded = ref(false)
const newError = ref('')

function errorText(err) {
  return err?.response?.data?.detail || err?.message || 'failed'
}

// The Similar page's row shape, so SimilarTrackRow can show them.
function toSong(item) {
  return {
    song_id: item.song_id || '',
    name: item.name || '',
    artists: Array.isArray(item.artists)
      ? item.artists
      : [item.artist].filter(Boolean),
    artist: item.artist || '',
    album_name: item.album_name || '',
    cover_url: item.cover_url || '',
    duration: item.duration || 0,
    url: item.url || '',
    match: item.match || 0,
  }
}

// A library mix as the page shows it: the server's fields, tracks ready
// for the player.
function toMix(mix) {
  return { ...mix, tracks: (mix.tracks || []).map(normalizeTrack) }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await API.getMixes()
    mixes.value = (res.data?.mixes || []).map(toMix)
    loaded.value = true
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function loadDaily() {
  dailyLoading.value = true
  dailyError.value = ''
  try {
    const res = await API.getDailyMixes()
    daily.value = (res.data?.mixes || []).map(toMix)
    dailyLoaded.value = true
  } catch (err) {
    dailyError.value = errorText(err)
  } finally {
    dailyLoading.value = false
  }
}

async function loadNew() {
  newLoading.value = true
  newError.value = ''
  try {
    const res = await API.getNewForYou()
    newSongs.value = (res.data?.tracks || []).map(toSong)
    newSeeds.value = res.data?.seeds || []
    newPartial.value = Boolean(res.data?.partial)
    newLoaded.value = true
  } catch (err) {
    newError.value = errorText(err)
  } finally {
    newLoading.value = false
  }
}

function findMix(id) {
  return (
    mixes.value.find((mix) => mix.id === id) ||
    daily.value.find((mix) => mix.id === id) ||
    null
  )
}

export function useMixes() {
  return {
    mixes,
    loading,
    loaded,
    error,
    daily,
    dailyLoading,
    dailyLoaded,
    dailyError,
    newSongs,
    newSeeds,
    newPartial,
    newLoading,
    newLoaded,
    newError,
    load,
    loadDaily,
    loadNew,
    findMix,
  }
}
