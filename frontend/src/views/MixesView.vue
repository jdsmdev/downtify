<template>
  <div>
    <div
      v-if="!mixId"
      class="mx-auto flex max-w-[1680px] flex-col gap-8 px-4 pt-6 pb-10 sm:px-6 md:pt-8 lg:px-10"
    >
      <PageHeader :title="t('mixes.title')" :subtitle="t('mixes.subtitle')">
        <UiButton icon="refresh" :loading="anyLoading" @click="refreshAll">
          {{ t('common.refresh') }}
        </UiButton>
      </PageHeader>

      <UiEmpty
        v-if="store.error.value && !store.loaded.value"
        icon="alert"
        :title="t('mixes.failed')"
        :body="store.error.value"
      >
        <UiButton icon="refresh" @click="refreshAll">
          {{ t('common.retry') }}
        </UiButton>
      </UiEmpty>

      <template v-else>
        <section
          v-for="shelf in shelves"
          :key="shelf.id"
          class="flex flex-col gap-4"
        >
          <div>
            <h2 class="text-display text-xl font-semibold">
              {{ shelf.title }}
            </h2>
            <p v-if="shelf.body" class="mt-1 text-[13px] text-muted">
              {{ shelf.body }}
            </p>
          </div>
          <div v-if="shelf.loading" :class="GRID" aria-busy="true">
            <div v-for="n in 6" :key="n" class="flex flex-col gap-2.5">
              <UiSkeleton class="aspect-square w-full" />
              <UiSkeleton class="h-4 w-2/3" />
            </div>
          </div>
          <p v-else-if="!shelf.items.length" class="text-sm text-muted">
            {{ shelf.empty }}
          </p>
          <div v-else :class="GRID">
            <MediaTile
              v-for="item in shelf.items"
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
        </section>
      </template>

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
            v-if="card.tracks.length"
            variant="secondary"
            icon="plus"
            @click="playlistActions.openCreate(card.tracks)"
          >
            {{ t('mixes.saveAsPlaylist') }}
          </UiButton>
          <UiButton
            variant="ghost"
            icon="refresh"
            :loading="loadingFor(card)"
            @click="refreshFor(card)"
          >
            {{ t('common.refresh') }}
          </UiButton>
        </template>
      </CollectionHero>

      <div
        class="mx-auto flex max-w-[1680px] flex-col gap-6 px-4 pb-10 sm:px-6 lg:px-10"
      >
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
import TrackList from '/src/components/library/TrackList.vue'
import { useMixes } from '/src/model/mixes'
import { usePlayer } from '/src/model/player'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useTrackActions } from '/src/model/trackActions'
import { useI18n } from '/src/i18n'

const GRID =
  'grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 2xl:grid-cols-6'

const { t } = useI18n()
const route = useRoute()
const store = useMixes()
const player = usePlayer()
const actions = useTrackActions()
const playlistActions = usePlaylistActions()

const ICONS = {
  on_repeat: 'repeat',
  forgotten: 'clock',
  unplayed: 'sparkle',
  daily: 'music',
  kids: 'music',
  decade: 'disc',
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

// Title, texts and covers of one mix, by its kind.
function describe(mix) {
  const kind = mix.kind || mix.id
  const count = mix.tracks.length
  const tracks = count ? t('common.tracks', { count }) : ''
  const base = {
    ...mix,
    kind,
    icon: ICONS[kind] || 'playlist',
    covers: libraryCovers(mix.tracks),
    empty: '',
  }
  if (kind === 'daily') {
    const names = (mix.artists || []).join(', ')
    return {
      ...base,
      title: t('mixes.daily.title', { number: mix.number }),
      subtitle: names ? t('mixes.daily.artists', { names }) : tracks,
      body: t('mixes.daily.body', { names }),
    }
  }
  if (kind === 'kids') {
    return {
      ...base,
      title: t('mixes.kids.title'),
      subtitle: tracks,
      body: t('mixes.kids.body'),
    }
  }
  if (kind === 'decade') {
    // A string: numbers get thousands separators ("1,990").
    const decade = String(mix.decade)
    return {
      ...base,
      title: t('mixes.decade.title', { decade }),
      subtitle: tracks,
      body: t('mixes.decade.body', { decade }),
    }
  }
  return {
    ...base,
    title: t(`mixes.${kind}.title`),
    subtitle: tracks || t(`mixes.${kind}.short`),
    body: t(`mixes.${kind}.body`),
    empty: t(`mixes.${kind}.empty`),
  }
}

const dailyCards = computed(() => store.daily.value.map(describe))
const decadeCards = computed(() =>
  store.mixes.value.filter((mix) => mix.kind === 'decade').map(describe)
)
const ownCards = computed(() =>
  store.mixes.value.filter((mix) => mix.kind !== 'decade').map(describe)
)
const cards = computed(() => [
  ...dailyCards.value,
  ...ownCards.value,
  ...decadeCards.value,
])

const shelves = computed(() =>
  [
    {
      id: 'daily',
      title: t('mixes.dailyTitle'),
      body: t('mixes.dailyBody'),
      empty: store.dailyError.value
        ? t('mixes.dailyFailed')
        : t('mixes.dailyEmpty'),
      items: dailyCards.value,
      loading: store.dailyLoading.value && !store.dailyLoaded.value,
      show: true,
    },
    {
      id: 'own',
      title: t('mixes.ownTitle'),
      body: '',
      empty: '',
      items: ownCards.value,
      loading: !store.loaded.value,
      show: true,
    },
    {
      id: 'decades',
      title: t('mixes.decadesTitle'),
      body: t('mixes.decadesBody'),
      empty: '',
      items: decadeCards.value,
      loading: false,
      show: decadeCards.value.length > 0,
    },
  ].filter((shelf) => shelf.show)
)

const mixId = computed(() => String(route.params.id || ''))
const card = computed(() =>
  mixId.value
    ? cards.value.find((item) => item.id === mixId.value) || null
    : null
)

const playableCount = computed(() => card.value?.tracks.length || 0)

const anyLoading = computed(() => store.loading.value || store.dailyLoading.value)

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
  actions.play(item.tracks, 0, contextFor(item), options)
}

function togglePlay() {
  if (isPlaying(card.value)) player.pause()
  else playCard(card.value)
}

function loadingFor(item) {
  if (item.kind === 'daily') return store.dailyLoading.value
  return store.loading.value
}

function refreshFor(item) {
  if (item.kind === 'daily') store.loadDaily(true)
  else store.load(true)
}

// Rebuilding the playlists is one job, so the Daily Mixes wait for it.
function refreshAll() {
  store.load(true).then(() => store.loadDaily())
}

onMounted(() => {
  if (!store.loaded.value) store.load()
  if (!store.dailyLoaded.value && !store.dailyLoading.value) {
    store.loadDaily()
  }
})

// Opening a mix page shows the latest: listens keep coming in.
watch(mixId, (id) => {
  if (id && store.loaded.value) store.load()
})
</script>
