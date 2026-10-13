<template>
  <div>
    <div
      v-if="!mixId"
      class="mx-auto flex max-w-[1680px] flex-col gap-8 px-4 pt-6 pb-10 sm:px-6 md:pt-8 lg:px-10"
    >
      <PageHeader :title="t('mixes.title')" :subtitle="t('mixes.subtitle')">
        <UiButton
          icon="refresh"
          :loading="store.loading.value"
          @click="refresh"
        >
          {{ t('common.refresh') }}
        </UiButton>
      </PageHeader>

      <UiEmpty
        v-if="store.error.value && !store.loaded.value"
        icon="alert"
        :title="t('mixes.failed')"
        :body="store.error.value"
      >
        <UiButton icon="refresh" @click="refresh">
          {{ t('common.retry') }}
        </UiButton>
      </UiEmpty>

      <div v-else :class="GRID" :aria-busy="store.loading.value || undefined">
        <MediaTile
          v-for="item in cards"
          :key="item.id"
          :to="{ name: 'Mixes', params: { id: item.id } }"
          :title="item.title"
          :subtitle="item.subtitle"
          :covers="item.covers"
          :name="item.title"
          :icon="item.icon"
          :playable="item.tracks.length > 0"
          :playing="isPlaying(item)"
          @play="playCard(item)"
        />
      </div>

      <p class="text-[13px] text-faint">{{ t('mixes.howItWorks') }}</p>
    </div>

    <template v-else-if="card">
      <CollectionHero
        :title="card.title"
        :kicker="t('mixes.kicker')"
        :covers="card.covers"
        :name="card.title"
        :icon="card.icon"
      >
        <template #subtitle>{{ card.body }}</template>
        <template #actions>
          <PlayButton
            :label="t('actions.playItem', { name: card.title })"
            :playing="isPlaying(card)"
            :disabled="!playableCount"
            @click="togglePlay"
          />
          <UiIconButton
            icon="shuffle"
            :label="t('actions.shuffle')"
            size="lg"
            round
            :disabled="!playableCount"
            @click="playCard(card, { shuffled: true })"
          />
          <UiButton
            v-if="card.library && card.tracks.length"
            variant="secondary"
            icon="plus"
            @click="playlistActions.openCreate(card.tracks)"
          >
            {{ t('mixes.saveAsPlaylist') }}
          </UiButton>
          <UiButton
            variant="ghost"
            icon="refresh"
            :loading="
              card.library ? store.loading.value : store.newLoading.value
            "
            @click="card.library ? refresh() : store.loadNew()"
          >
            {{ t('common.refresh') }}
          </UiButton>
        </template>
      </CollectionHero>

      <div
        class="mx-auto flex max-w-[1680px] flex-col gap-6 px-4 pb-10 sm:px-6 lg:px-10"
      >
        <template v-if="card.library">
          <TrackList
            v-if="card.tracks.length"
            :tracks="card.tracks"
            :context="contextFor(card)"
          />
          <UiEmpty
            v-else-if="store.loaded.value"
            :icon="card.icon"
            :title="t('mixes.emptyTitle')"
            :body="card.empty"
          />
        </template>

        <template v-else>
          <div v-if="store.newLoading.value" class="flex flex-col gap-2">
            <div
              v-for="n in 6"
              :key="n"
              class="flex h-16 items-center gap-3 px-3"
            >
              <UiSkeleton class="size-11 !rounded-[8px]" />
              <div class="flex flex-1 flex-col gap-2">
                <UiSkeleton class="h-3.5 w-1/3" />
                <UiSkeleton class="h-3 w-1/5" />
              </div>
            </div>
          </div>
          <UiEmpty
            v-else-if="store.newError.value"
            icon="alert"
            :title="t('mixes.failed')"
            :body="store.newError.value"
          >
            <UiButton icon="refresh" @click="store.loadNew()">
              {{ t('common.retry') }}
            </UiButton>
          </UiEmpty>
          <UiEmpty
            v-else-if="store.newLoaded.value && !store.newSongs.value.length"
            icon="wand"
            :title="t('mixes.emptyTitle')"
            :body="card.empty"
          />
          <template v-else-if="store.newSongs.value.length">
            <p v-if="seedNames" class="text-[13px] text-muted">
              {{ t('mixes.newBecause', { names: seedNames }) }}
            </p>
            <div class="-mx-3 flex flex-col">
              <TrackDownPlayHeader />
              <SimilarTrackRow
                v-for="(song, i) in store.newSongs.value"
                :key="`${song.artist}|${song.name}`"
                :song="song"
                :index="i"
                :songs="store.newSongs.value"
              />
            </div>
          </template>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup>
// "Made for you": playlists the server builds from what the user plays
// (see downtify/mixes.py). `/mixes` shows them all, `/mixes/<id>` one.
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import UiButton from '/src/components/ui/UiButton.vue'
import UiEmpty from '/src/components/ui/UiEmpty.vue'
import UiIconButton from '/src/components/ui/UiIconButton.vue'
import UiSkeleton from '/src/components/ui/UiSkeleton.vue'
import CollectionHero from '/src/components/library/CollectionHero.vue'
import MediaTile from '/src/components/library/MediaTile.vue'
import PageHeader from '/src/components/library/PageHeader.vue'
import PlayButton from '/src/components/library/PlayButton.vue'
import TrackDownPlayHeader from '/src/components/library/TrackDownPlayHeader.vue'
import TrackList from '/src/components/library/TrackList.vue'
import SimilarTrackRow from '/src/components/similar/SimilarTrackRow.vue'
import { useLibrary } from '/src/model/library'
import { useMixes } from '/src/model/mixes'
import { usePlayer } from '/src/model/player'
import { usePlaylistActions } from '/src/model/playlistActions'
import { songToPlayerTrack } from '/src/model/songPlay'
import { useTrackActions } from '/src/model/trackActions'
import { joinNames } from '/src/lib/discover'
import { useI18n } from '/src/i18n'

const GRID =
  'grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 2xl:grid-cols-6'

const { t, locale } = useI18n()
const route = useRoute()
const store = useMixes()
const library = useLibrary()
const player = usePlayer()
const actions = useTrackActions()
const playlistActions = usePlaylistActions()

const ICONS = {
  on_repeat: 'repeat',
  forgotten: 'clock',
  unplayed: 'sparkle',
  new: 'wand',
}

// Up to four different album covers, for the tile mosaic.
function libraryCovers(tracks) {
  const seen = new Set()
  const covers = []
  for (const track of tracks) {
    const key = `${track.albumArtist}|${track.album}`
    if (seen.has(key) || !track.hasCover) continue
    seen.add(key)
    covers.push(track.cover)
    if (covers.length === 4) break
  }
  return covers
}

const cards = computed(() => {
  const built = store.mixes.value.map((mix) => ({
    id: mix.id,
    library: true,
    tracks: mix.tracks,
    covers: libraryCovers(mix.tracks),
  }))
  const songs = store.newSongs.value
  const newCovers = songs.map((song) => song.cover_url).filter(Boolean)
  built.push({
    id: 'new',
    library: false,
    tracks: songs,
    covers: [...new Set(newCovers)].slice(0, 4),
  })
  return built.map((item) => ({
    ...item,
    icon: ICONS[item.id] || 'playlist',
    title: t(`mixes.${item.id}.title`),
    body: t(`mixes.${item.id}.body`),
    empty: t(`mixes.${item.id}.empty`),
    subtitle: item.tracks.length
      ? t('common.tracks', { count: item.tracks.length })
      : t(`mixes.${item.id}.short`),
  }))
})

const mixId = computed(() => String(route.params.id || ''))
const card = computed(() =>
  mixId.value
    ? cards.value.find((item) => item.id === mixId.value) || null
    : null
)

const playableCount = computed(() => card.value?.tracks.length || 0)

const seedNames = computed(() =>
  joinNames(store.newSeeds.value.map((seed) => seed.artist), locale.value)
)

function contextFor(item) {
  return {
    type: 'mix',
    title: item.title,
    cover: item.covers[0] || '',
    covers: item.covers,
    route: { name: 'Mixes', params: { id: item.id } },
  }
}

function isPlaying(item) {
  const ctx = player.context.value
  return (
    player.isPlaying.value && ctx?.type === 'mix' && ctx?.title === item.title
  )
}

function playCard(item, options = {}) {
  const tracks = item.library
    ? item.tracks
    : item.tracks.map((song) => songToPlayerTrack(song, library.findTrack))
  actions.play(tracks, 0, contextFor(item), options)
}

function togglePlay() {
  if (isPlaying(card.value)) player.pause()
  else playCard(card.value)
}

function refresh() {
  store.load()
}

onMounted(() => {
  if (!store.loaded.value) store.load()
  if (!store.newLoaded.value && !store.newLoading.value) store.loadNew()
})

// Opening a mix page shows the latest: listens keep coming in.
watch(mixId, (id) => {
  if (id && store.loaded.value) store.load()
})
</script>
