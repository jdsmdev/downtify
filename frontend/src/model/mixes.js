// Mixes: playlists the server rebuilds every day from what the user
// plays - see downtify/mix_playlists.py.
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

function errorText(err) {
  return err?.response?.data?.detail || err?.message || 'failed'
}

// A library mix as the page shows it: the server's fields, tracks ready
// for the player.
function toMix(mix) {
  return { ...mix, tracks: (mix.tracks || []).map(normalizeTrack) }
}

async function load(refresh = false) {
  loading.value = true
  error.value = ''
  try {
    const res = await API.getMixes(refresh)
    mixes.value = (res.data?.mixes || []).map(toMix)
    loaded.value = true
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function loadDaily(refresh = false) {
  dailyLoading.value = true
  dailyError.value = ''
  try {
    const res = await API.getDailyMixes(refresh)
    daily.value = (res.data?.mixes || []).map(toMix)
    dailyLoaded.value = true
  } catch (err) {
    dailyError.value = errorText(err)
  } finally {
    dailyLoading.value = false
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
    load,
    loadDaily,
    findMix,
  }
}
