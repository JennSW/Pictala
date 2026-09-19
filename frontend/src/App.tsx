import { FormEvent, useEffect, useState } from "react";
import {
  fetchOutings,
  fetchOuting,
  markOutingReviewed,
  unmarkOutingReviewed,
  suggestSpecies,
  acceptSuggestion,
  rejectSuggestion,
  assignSpecies,
  unconfirmMatch,
  suggestFallback,
  suggestFallbackBatch,
  acceptFallback,
  searchBySpecies,
  fetchSyncStatus,
  adjustTimezone,
  fetchUnassignedClusters,
  fetchUnassignedCluster,
  suggestUnassignedFallback,
  suggestUnassignedFallbackBatch,
  identifyUnassignedPhoto,
  moveToCluster,
  OutingSummary,
  OutingDetail,
  SpeciesSuggestion,
  FallbackSuggestion,
  SearchResult,
  SyncStatus,
  ClusterSummary,
  ClusterDetail,
  MatchEntry,
  Observation,
} from "./api";
import DatePicker from "./DatePicker";
import PhotoLightbox, { LightboxEntry } from "./PhotoLightbox";
import SyncPanel from "./SyncPanel";
import ebirdMatchIcon from "./assets/icons/ebird-match.png";
import "./theme.css";

// Read-only status/species summary for the lightbox (issue #44) --
// mirrors the badge language each grid already shows, recomputed here
// since the lightbox needs it for every photo in the list, not just
// the one currently open.
function outingLightboxEntry(m: MatchEntry): LightboxEntry {
  const needsReview = Boolean(m.observation) && !m.reviewed_at;
  // Only status shown here is "Unconfirmed" (issue #47) -- the grid's
  // more specific language (Needs review/Off checklist/Note/Other/
  // Unmatched) is diagnostic detail that belongs in the review workflow,
  // not this read-only glance. Confirmed photos show no badge at all.
  // A fallback label (manual/AI-accepted/note) counts as confirmed too --
  // it already required a person to look and agree (see issue #32).
  const confirmed = m.observation ? !needsReview : Boolean(m.fallback_common_name);
  const statusLabel = confirmed ? null : "Unconfirmed";
  return {
    photo: m.photo,
    statusLabel,
    speciesLabel: m.observation?.common_name ?? m.fallback_common_name ?? null,
    scientificName: m.observation?.scientific_name ?? m.fallback_scientific_name ?? null,
  };
}

// Accessible name for the "view larger" button around each photo
// thumbnail. Previously the <img>'s alt text was just the raw Flickr
// title (e.g. "Aug 7-05658" -- meaningless to a screen reader, and often
// empty) even when the app already knows the identified species -- use
// that when there is one.
function photoAccessibleLabel(m: MatchEntry): string {
  const species = m.observation?.common_name ?? m.fallback_common_name;
  return species ? `View larger photo — ${species}` : `View larger photo — ${m.photo.title || "unidentified bird"}`;
}

function clusterLightboxEntry(m: MatchEntry): LightboxEntry {
  const identified = Boolean(m.fallback_common_name);
  return {
    photo: m.photo,
    statusLabel: identified ? (m.fallback_scientific_name ? "Identified" : "Not on eBird") : "Unidentified",
    speciesLabel: m.fallback_common_name ?? null,
    scientificName: m.fallback_scientific_name ?? null,
  };
}

// Per-photo state for the "Suggest species" flow (Strategy B). Keyed by
// photo id. Nothing here is persisted until the user clicks Accept --
// see DESIGN.md section 4.
// "rejected" -- the user rejected a positive suggestion (it named the
// wrong species). Shares its follow-up panel (manual dropdown, broader
// ID, a plain note) with the "no confident match" case, since both mean
// "this proposed answer isn't right."
// "editing" -- the user opened the fix action on an already-resolved
// match (see issue #32). Shares the same follow-up panel as "rejected"
// since both are "pick something else for this photo," just reached
// directly instead of via an AI suggestion first.
type SuggestionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: SpeciesSuggestion }
  | { status: "accepting" }
  | { status: "rejected" }
  | { status: "editing" };

// Fallback identification flow -- see docs/USER_STORIES.md, "Species ID
// fallback for eBird gaps". Separate from SuggestionState since it's a
// distinct action (broader, unconstrained guess) with its own result shape.
type FallbackState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: FallbackSuggestion }
  | { status: "accepting" };

export default function App() {
  const [outings, setOutings] = useState<OutingSummary[]>([]);
  const [selected, setSelected] = useState<OutingDetail | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The moment this page load happened, captured once from the *previous*
  // value stored -- so "confirmed this session" means reviewed_at falls
  // after whenever the app was last opened, not after right now. Storage
  // gets overwritten with the current time immediately after reading, so
  // next session's boundary is this one's start. null on the very first
  // ever load (nothing to compare against yet, so nothing shows as fresh).
  const [sessionBoundary] = useState<string | null>(() => {
    const stored = localStorage.getItem("birdtrip_last_load");
    localStorage.setItem("birdtrip_last_load", new Date().toISOString());
    return stored;
  });
  const [suggestions, setSuggestions] = useState<Record<number, SuggestionState>>({});
  const [fallbacks, setFallbacks] = useState<Record<number, FallbackState>>({});
  // Manual-assign dropdown selection, per photo (string since <select>
  // values are strings; "" means nothing picked yet).
  const [manualPick, setManualPick] = useState<Record<number, string>>({});
  // Editable text for a fallback guess, per photo -- pre-filled with the
  // AI's guess (including "Other" guesses like "Dragonfly"), editable
  // before accepting so the user can correct it or write their own note.
  const [fallbackText, setFallbackText] = useState<Record<number, string>>({});
  // Plain freeform note, per photo -- for the rejected/no-match follow-up
  // panel, saved directly with no AI guess involved at all.
  const [noteText, setNoteText] = useState<Record<number, string>>({});
  const [savingNote, setSavingNote] = useState<Record<number, boolean>>({});

  // Search by species (see docs/USER_STORIES.md, "Story: Search by
  // species"). searchResults === null means no search is active -- the
  // normal date-picker/outings-list/detail view shows instead.
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Sync status is still read here (the calendar/outings-list panel
  // needs it), but the button/confirm-last-sync/syncing state itself
  // lives in SyncPanel.tsx now -- it doesn't share anything with the
  // rest of this component beyond "here's the current status" and "a
  // sync just finished, here's the fresh data."
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);

  // Timezone-mismatch "Adjust" action (issue #6) -- per-photo loading
  // state since it's a per-card button.
  const [adjustingTimezone, setAdjustingTimezone] = useState<Record<number, boolean>>({});

  // Checklist-less photo clusters (issue #35) -- a separate browse mode
  // from the normal date-picker/outings view, entered via the "Not on
  // eBird" button. selectedCluster === null means showing the cluster
  // list; set means showing one cluster's photos.
  const [showUnassigned, setShowUnassigned] = useState(false);
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [selectedCluster, setSelectedCluster] = useState<ClusterDetail | null>(null);
  // Set when entering the cluster list from a specific calendar date
  // (viewClustersForDate) so the list shows just that date's clusters
  // instead of every checklist-less photo in the whole app. Null means
  // showing everything, e.g. from the general "Photos not on eBird"
  // button.
  const [clusterDateFilter, setClusterDateFilter] = useState<string | null>(null);
  const [clusterIdentifyText, setClusterIdentifyText] = useState<Record<number, string>>({});
  const [clusterSuggesting, setClusterSuggesting] = useState<Record<number, boolean>>({});
  // The AI's own guess, remembered separately from the editable
  // clusterIdentifyText above so a save can tell "accepted this AI
  // suggestion as-is" from "typed something from scratch" for AI
  // accuracy tracking (raised 2026-09-03) -- cleared once saved or once
  // the user starts over without ever asking Claude.
  const [clusterAiGuess, setClusterAiGuess] = useState<Record<number, string>>({});
  // Manually assign a checklist-less photo to a real checklist (issue
  // #67) -- reuses the existing assignSpecies endpoint, just reachable
  // from this cluster view. Picking a checklist fetches that checklist's
  // own reported species for the second dropdown; the cluster's own date
  // may be wrong (that's usually *why* the photo ended up here), so the
  // checklist list isn't filtered to it, only sorted with nearby dates
  // first as a convenience.
  const [assignToChecklistPick, setAssignToChecklistPick] = useState<Record<number, string>>({});
  const [assignToSpeciesOptions, setAssignToSpeciesOptions] = useState<Record<number, Observation[]>>({});
  const [assignToSpeciesPick, setAssignToSpeciesPick] = useState<Record<number, string>>({});
  const [assigningToChecklist, setAssigningToChecklist] = useState<Record<number, boolean>>({});
  const [clusterSaving, setClusterSaving] = useState<Record<number, boolean>>({});

  // Batch "Ask Pictala" (issue #5) -- a checkbox per unmatched/checklist-
  // less photo, keyed by photo id (globally unique, so one map covers
  // both the outing detail and cluster views). MAX_BATCH_PHOTOS mirrors
  // the backend's cap (species_classifier.MAX_BATCH_SIZE) so the button
  // disables before a request that would just get rejected.
  const [checkedPhotos, setCheckedPhotos] = useState<Record<number, boolean>>({});
  const [batchSuggesting, setBatchSuggesting] = useState(false);
  // Batch approve/confirm (issue #50) -- same checkedPhotos map, but for
  // "Needs review" matches (already have an observation, just never
  // confirmed) rather than Unmatched ones. A photo can only be in one of
  // those two states at once, so sharing the map is safe.
  const [batchConfirming, setBatchConfirming] = useState(false);
  // Batch assign to an already-reported species (issue #71) -- same
  // checkedPhotos map again, scoped to Unmatched/needs_claude photos like
  // batch Ask Pictala. One species picked for the whole batch at once,
  // rather than per-photo.
  const [batchAssignPick, setBatchAssignPick] = useState("");
  const [batchAssigning, setBatchAssigning] = useState(false);
  const MAX_BATCH_PHOTOS = 10;
  // One-click batch-confirm undo (issue #69) -- short-lived and scoped to
  // the checklist it ran against, so switching outings implicitly drops
  // any stale offer instead of undoing the wrong outing's batch.
  const [lastBatchConfirm, setLastBatchConfirm] = useState<{ checklistId: number; photoIds: number[] } | null>(
    null
  );
  const [undoingBatchConfirm, setUndoingBatchConfirm] = useState(false);
  const BATCH_UNDO_WINDOW_MS = 10000;

  // Inline photo lightbox (issue #44) -- a modal, not a new-tab
  // navigation, so looking at a photo closer never loses page state
  // (see #45). Read-only status/species context, deliberately no
  // actions and no prev/next -- see PhotoLightbox.tsx for why.
  const [lightboxEntry, setLightboxEntry] = useState<LightboxEntry | null>(null);

  function closeLightbox() {
    setLightboxEntry(null);
  }

  // Hero trip-card thumbnails (issue #4 follow-up) -- OutingSummary
  // doesn't carry a representative photo, so this fetches full detail
  // just for the 3 outings actually shown as hero cards, not every
  // outing. Keyed by outing id and cached indefinitely once resolved;
  // null (as opposed to not-yet-present) means "checked, this outing
  // really has no Flickr photo at all" (eBird-only), not "still loading."
  const [tripThumbnails, setTripThumbnails] = useState<Record<number, string | null>>({});

  useEffect(() => {
    const topIds = outings.slice(0, 3).map((o) => o.id);
    const missing = topIds.filter((id) => !(id in tripThumbnails));
    missing.forEach((id) => {
      fetchOuting(id)
        .then((detail) => {
          const photoUrl = detail.matches.find((m) => m.photo.url_medium)?.photo.url_medium ?? null;
          setTripThumbnails((prev) => ({ ...prev, [id]: photoUrl }));
        })
        .catch(() => {
          setTripThumbnails((prev) => ({ ...prev, [id]: null }));
        });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outings]);

  useEffect(() => {
    fetchOutings()
      .then((data) => {
        setOutings(data);
        // No date selected on load -- rather than an empty detail panel,
        // default to the most recent outing (see docs/USER_STORIES.md,
        // "Story: Date selection"). The list itself stays unfiltered;
        // this only affects the detail panel's initial state.
        if (data.length > 0) {
          openOuting(data[0].id);
        }
      })
      .catch((e) => setError(String(e)));
    fetchSyncStatus()
      .then(setSyncStatus)
      .catch((e) => setError(String(e)));
    // Fetched eagerly (not just when "Photos not on eBird" is opened) so
    // the calendar can mark checklist-less dates as available too --
    // otherwise a date like July 11 (real photos, no checklist) looks
    // identical to a date with nothing at all.
    fetchUnassignedClusters()
      .then(setClusters)
      .catch((e) => setError(String(e)));
  }, []);

  async function handleAdjustTimezone(checklistId: number, photoId: number) {
    setAdjustingTimezone((prev) => ({ ...prev, [photoId]: true }));
    try {
      await adjustTimezone(checklistId, photoId);
      // The correction can move the photo to a different checklist/outing
      // entirely -- refetch this outing rather than assume it's still here.
      setSelected(await fetchOuting(checklistId));
    } catch (e) {
      setError(String(e));
    } finally {
      setAdjustingTimezone((prev) => ({ ...prev, [photoId]: false }));
    }
  }

  async function loadUnassigned() {
    setShowUnassigned(true);
    setSelectedCluster(null);
    setClusterDateFilter(null);
    try {
      setClusters(await fetchUnassignedClusters());
    } catch (e) {
      setError(String(e));
    }
  }

  function viewClustersForDate() {
    setShowUnassigned(true);
    setClusterDateFilter(selectedDate);
    const matches = clusters.filter((c) => c.date === selectedDate);
    if (matches.length === 1) {
      openCluster(matches[0].id);
    } else {
      setSelectedCluster(null);
    }
  }

  async function openCluster(clusterId: string) {
    try {
      setSelectedCluster(await fetchUnassignedCluster(clusterId));
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleClusterSuggest(photoId: number) {
    if (!selectedCluster) return;
    setClusterSuggesting((prev) => ({ ...prev, [photoId]: true }));
    try {
      const result = await suggestUnassignedFallback(selectedCluster.id, photoId);
      setClusterIdentifyText((prev) => ({ ...prev, [photoId]: result.common_name ?? "" }));
      setClusterAiGuess((prev) => ({ ...prev, [photoId]: result.common_name ?? "" }));
    } catch (e) {
      setError(String(e));
    } finally {
      setClusterSuggesting((prev) => ({ ...prev, [photoId]: false }));
    }
  }

  function checkedPhotoIdsIn(photoIds: number[]): number[] {
    return photoIds.filter((id) => checkedPhotos[id]);
  }

  async function handleClusterSuggestBatch() {
    if (!selectedCluster) return;
    const photoIds = checkedPhotoIdsIn(selectedCluster.matches.map((m) => m.photo.id));
    if (photoIds.length === 0) return;
    setBatchSuggesting(true);
    try {
      const results = await suggestUnassignedFallbackBatch(selectedCluster.id, photoIds);
      setClusterIdentifyText((prev) => {
        const next = { ...prev };
        for (const r of results) next[r.photo_id] = r.common_name ?? "";
        return next;
      });
      setClusterAiGuess((prev) => {
        const next = { ...prev };
        for (const r of results) next[r.photo_id] = r.common_name ?? "";
        return next;
      });
      setCheckedPhotos((prev) => {
        const next = { ...prev };
        for (const id of photoIds) delete next[id];
        return next;
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchSuggesting(false);
    }
  }

  async function handleClusterIdentify(photoId: number) {
    if (!selectedCluster) return;
    const text = (clusterIdentifyText[photoId] ?? "").trim();
    if (!text) return;
    setClusterSaving((prev) => ({ ...prev, [photoId]: true }));
    try {
      await identifyUnassignedPhoto(selectedCluster.id, photoId, text, undefined, clusterAiGuess[photoId]);
      setSelectedCluster(await fetchUnassignedCluster(selectedCluster.id));
      setClusterAiGuess((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setClusterSaving((prev) => ({ ...prev, [photoId]: false }));
    }
  }

  async function handleMoveToCluster(photoId: number, toClusterId: string) {
    if (!selectedCluster || !toClusterId) return;
    try {
      await moveToCluster(selectedCluster.id, photoId, toClusterId);
      setClusters(await fetchUnassignedClusters());
      setSelectedCluster(await fetchUnassignedCluster(selectedCluster.id));
    } catch (e) {
      setError(String(e));
    }
  }

  // Picking a checklist for a checklist-less photo (issue #67) fetches
  // that checklist's own reported species for the second dropdown --
  // assignSpecies only accepts an observation actually on the target
  // checklist, so the species list has to come from wherever gets picked.
  async function handlePickAssignChecklist(photoId: number, checklistIdStr: string) {
    setAssignToChecklistPick((prev) => ({ ...prev, [photoId]: checklistIdStr }));
    setAssignToSpeciesPick((prev) => ({ ...prev, [photoId]: "" }));
    if (!checklistIdStr) {
      setAssignToSpeciesOptions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      return;
    }
    try {
      const outing = await fetchOuting(Number(checklistIdStr));
      setAssignToSpeciesOptions((prev) => ({ ...prev, [photoId]: outing.observations }));
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleAssignToChecklist(photoId: number) {
    const checklistIdStr = assignToChecklistPick[photoId];
    const observationIdStr = assignToSpeciesPick[photoId];
    if (!checklistIdStr || !observationIdStr || !selectedCluster) return;
    setAssigningToChecklist((prev) => ({ ...prev, [photoId]: true }));
    try {
      await assignSpecies(Number(checklistIdStr), photoId, Number(observationIdStr));
      const [freshCluster, freshClusters, freshOutings] = await Promise.all([
        fetchUnassignedCluster(selectedCluster.id),
        fetchUnassignedClusters(),
        fetchOutings(),
      ]);
      setSelectedCluster(freshCluster);
      setClusters(freshClusters);
      setOutings(freshOutings);
      setAssignToChecklistPick((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setAssignToSpeciesPick((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setAssignToSpeciesOptions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setAssigningToChecklist((prev) => ({ ...prev, [photoId]: false }));
    }
  }

  // Union of checklist-backed outing dates and checklist-less cluster
  // dates -- a date like July 11 (real photos, no eBird checklist)
  // needs to show as available too, not look identical to a date with
  // nothing at all.
  const availableDates = new Set([...outings.map((o) => o.date), ...clusters.map((c) => c.date)]);
  const visibleOutings = selectedDate ? outings.filter((o) => o.date === selectedDate) : outings;
  const clustersForSelectedDate = selectedDate ? clusters.filter((c) => c.date === selectedDate) : [];

  async function openOuting(id: number) {
    try {
      setSelected(await fetchOuting(id));
      setSuggestions({});
      setShowUnassigned(false);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleToggleReviewed(outingId: number, reviewed: boolean) {
    try {
      if (reviewed) await markOutingReviewed(outingId);
      else await unmarkOutingReviewed(outingId);
      setSelected(await fetchOuting(outingId));
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      setSearchResults(await searchBySpecies(searchQuery.trim()));
    } catch (e) {
      setError(String(e));
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setSearchQuery("");
    setSearchResults(null);
  }

  async function handleSuggest(checklistId: number, photoId: number) {
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "loading" } }));
    try {
      const data = await suggestSpecies(checklistId, photoId);
      setSuggestions((prev) => ({ ...prev, [photoId]: { status: "ready", data } }));
    } catch (e) {
      setSuggestions((prev) => ({
        ...prev,
        [photoId]: { status: "error", message: String(e) },
      }));
    }
  }

  async function handleAccept(
    checklistId: number,
    photoId: number,
    observationId: number,
    confidence: number,
    suggestedCommonName?: string | null
  ) {
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await acceptSuggestion(checklistId, photoId, observationId, confidence, suggestedCommonName);
      setSelected(await fetchOuting(checklistId));
      setSuggestions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setSuggestions((prev) => ({
        ...prev,
        [photoId]: { status: "error", message: String(e) },
      }));
    }
  }

  async function handleReject(checklistId: number, photoId: number) {
    // Still writes nothing to the match itself -- rejecting just means
    // not calling accept, same as always -- but now logs the rejection
    // for AI accuracy tracking (raised 2026-09-03) before handing off to
    // the same follow-up panel as "no confident match" (manual dropdown,
    // broader ID, a plain note), since a wrong suggestion and no
    // suggestion both mean "this proposed answer isn't right."
    const current = suggestions[photoId];
    const data = current?.status === "ready" ? current.data : null;
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "rejected" } }));
    try {
      await rejectSuggestion(checklistId, photoId, data?.suggested_common_name ?? null, data?.confidence ?? 0);
    } catch (e) {
      // Logging failure shouldn't block the user from moving on to the
      // follow-up panel they were already sent to above -- surface it as
      // a global banner instead of reverting their rejection.
      setError(String(e));
    }
  }

  function handleDismissRejected(photoId: number) {
    setSuggestions((prev) => {
      const next = { ...prev };
      delete next[photoId];
      return next;
    });
    setNoteText((prev) => {
      const next = { ...prev };
      delete next[photoId];
      return next;
    });
  }

  // Open the fix panel on an already-resolved match (issue #32) -- no
  // AI suggestion or rejection involved, the user just wants to correct
  // something. Reuses the "rejected" panel's markup/handlers. Also used
  // to open a direct manual-pick panel on an unmatched photo, without
  // going through an AI suggestion first -- same panel either way.
  function handleOpenFix(photoId: number) {
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "editing" } }));
  }

  // A "Needs review" match (rule-based, nobody's looked at it) is
  // already correct as-is -- confirm it directly instead of forcing a
  // trip through the fix panel to re-pick the same species.
  async function handleConfirmMatch(checklistId: number, photoId: number, observationId: number) {
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await assignSpecies(checklistId, photoId, observationId);
      setSelected(await fetchOuting(checklistId));
      setSuggestions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setSuggestions((prev) => ({ ...prev, [photoId]: { status: "error", message: String(e) } }));
    }
  }

  // Batch version of handleConfirmMatch (issue #50) -- confirms every
  // checked "Needs review" match in one action instead of one click each.
  // No dedicated batch endpoint on the backend; assignSpecies is a plain
  // DB write (no AI call behind it, unlike batch Ask Pictala), so firing
  // one request per photo in parallel is fine.
  async function handleConfirmBatch(checklistId: number) {
    if (!selected) return;
    const needsReviewIds = selected.matches
      .filter((m) => Boolean(m.observation) && !m.reviewed_at)
      .map((m) => m.photo.id);
    const photoIds = checkedPhotoIdsIn(needsReviewIds);
    if (photoIds.length === 0) return;
    setBatchConfirming(true);
    try {
      await Promise.all(
        photoIds.map((photoId) => {
          const match = selected.matches.find((m) => m.photo.id === photoId);
          const observationId = match?.observation?.id;
          return observationId ? assignSpecies(checklistId, photoId, observationId) : Promise.resolve();
        })
      );
      setSelected(await fetchOuting(checklistId));
      setCheckedPhotos((prev) => {
        const next = { ...prev };
        for (const id of photoIds) delete next[id];
        return next;
      });
      setLastBatchConfirm({ checklistId, photoIds });
      setTimeout(() => {
        setLastBatchConfirm((prev) =>
          prev && prev.checklistId === checklistId && prev.photoIds === photoIds ? null : prev
        );
      }, BATCH_UNDO_WINDOW_MS);
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchConfirming(false);
    }
  }

  // Undo the most recent batch confirm (issue #69) -- reverses only the
  // reviewed_at timestamp on each photo in that batch, so a wrong one
  // lands back in "Needs review" for the existing per-photo Edit flow
  // rather than needing its species re-picked here too.
  async function handleUndoBatchConfirm() {
    if (!lastBatchConfirm) return;
    const { checklistId, photoIds } = lastBatchConfirm;
    setUndoingBatchConfirm(true);
    try {
      await Promise.all(photoIds.map((photoId) => unconfirmMatch(checklistId, photoId)));
      setSelected(await fetchOuting(checklistId));
      setLastBatchConfirm(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setUndoingBatchConfirm(false);
    }
  }

  // Batch assign one already-reported species to every checked Unmatched
  // photo at once (issue #71) -- same assignSpecies call handleAssign
  // makes per-photo, just fired in parallel across the whole selection.
  async function handleAssignBatch(checklistId: number) {
    if (!selected) return;
    const observationId = Number(batchAssignPick);
    if (!observationId) return;
    const unmatchedIds = selected.matches
      .filter((m) => !m.observation && !m.fallback_common_name)
      .map((m) => m.photo.id);
    const photoIds = checkedPhotoIdsIn(unmatchedIds);
    if (photoIds.length === 0) return;
    setBatchAssigning(true);
    try {
      await Promise.all(photoIds.map((photoId) => assignSpecies(checklistId, photoId, observationId)));
      setSelected(await fetchOuting(checklistId));
      setCheckedPhotos((prev) => {
        const next = { ...prev };
        for (const id of photoIds) delete next[id];
        return next;
      });
      setBatchAssignPick("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchAssigning(false);
    }
  }

  // A name was entered for this photo -- typed by hand, reached either
  // from the Unmatched dropdown's "Other" text box or the rejected-
  // suggestion follow-up panel. The backend now resolves it (checklist's
  // own species -> eBird's full taxonomy -> plain note) rather than the
  // frontend trying to guess which of those three it is, so this is
  // just a name and nothing more -- one handler for both entry points.
  async function handleSaveNote(checklistId: number, photoId: number) {
    const text = (noteText[photoId] ?? "").trim();
    if (!text) return;
    setSavingNote((prev) => ({ ...prev, [photoId]: true }));
    try {
      await acceptFallback(checklistId, photoId, text);
      setSelected(await fetchOuting(checklistId));
      handleDismissRejected(photoId);
    } catch (e) {
      // A global banner rather than a per-photo error state -- setting
      // suggestion state to "error" here would replace the whole entry
      // panel (dropdown or rejected-panel) with just an error message,
      // losing the UI needed to retry. This way the panel stays put.
      setError(String(e));
    } finally {
      setSavingNote((prev) => ({ ...prev, [photoId]: false }));
    }
  }

  // Manual override: the user picks one of the outing's own reported
  // species themselves, no AI suggestion behind it -- for correcting a
  // false-negative "no confident match" result.
  async function handleAssign(checklistId: number, photoId: number) {
    const observationId = Number(manualPick[photoId]);
    if (!observationId) return;
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await assignSpecies(checklistId, photoId, observationId, noteText[photoId]);
      setSelected(await fetchOuting(checklistId));
      setSuggestions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setManualPick((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setNoteText((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setSuggestions((prev) => ({ ...prev, [photoId]: { status: "error", message: String(e) } }));
    }
  }

  // Fallback identification: broader, unconstrained guess for a photo
  // that doesn't match any of the outing's reported species.
  async function handleSuggestFallback(checklistId: number, photoId: number) {
    setFallbacks((prev) => ({ ...prev, [photoId]: { status: "loading" } }));
    try {
      const data = await suggestFallback(checklistId, photoId);
      setFallbacks((prev) => ({ ...prev, [photoId]: { status: "ready", data } }));
      // Pre-fill the editable text with the AI's guess (including "Other"
      // guesses like "Dragonfly"), so accepting as-is is just one click,
      // but it's editable before saving.
      setFallbackText((prev) => ({ ...prev, [photoId]: data.common_name ?? "" }));
    } catch (e) {
      setFallbacks((prev) => ({ ...prev, [photoId]: { status: "error", message: String(e) } }));
    }
  }

  async function handleSuggestFallbackBatch(checklistId: number) {
    if (!selected) return;
    // Scoped to actually-unmatched photos only -- checkedPhotos is a
    // shared map with the batch-confirm checkboxes (issue #50), so an
    // unscoped read here could sweep in checked "Needs review" photo ids
    // too if both were checked at once.
    const unmatchedIds = selected.matches
      .filter((m) => !m.observation && !m.fallback_common_name)
      .map((m) => m.photo.id);
    const photoIds = checkedPhotoIdsIn(unmatchedIds);
    if (photoIds.length === 0) return;
    setBatchSuggesting(true);
    try {
      const results = await suggestFallbackBatch(checklistId, photoIds);
      setFallbacks((prev) => {
        const next = { ...prev };
        for (const r of results) next[r.photo_id] = { status: "ready", data: r };
        return next;
      });
      setFallbackText((prev) => {
        const next = { ...prev };
        for (const r of results) next[r.photo_id] = r.common_name ?? "";
        return next;
      });
      setCheckedPhotos((prev) => {
        const next = { ...prev };
        for (const id of photoIds) delete next[id];
        return next;
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchSuggesting(false);
    }
  }

  async function handleAcceptFallback(checklistId: number, photoId: number, suggestion: FallbackSuggestion) {
    const text = (fallbackText[photoId] ?? "").trim();
    if (!text) return;
    setFallbacks((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await acceptFallback(checklistId, photoId, text, suggestion.confidence, suggestion.common_name);
      setSelected(await fetchOuting(checklistId));
      setFallbacks((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setSuggestions((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
      setFallbackText((prev) => {
        const next = { ...prev };
        delete next[photoId];
        return next;
      });
    } catch (e) {
      setFallbacks((prev) => ({ ...prev, [photoId]: { status: "error", message: String(e) } }));
    }
  }

  function handleDismissFallback(photoId: number) {
    setFallbacks((prev) => {
      const next = { ...prev };
      delete next[photoId];
      return next;
    });
    setFallbackText((prev) => {
      const next = { ...prev };
      delete next[photoId];
      return next;
    });
  }

  // Outing review grouping (issue #43, DESIGN.md §10.3) -- photo_groups
  // gives photo ids per bucket; look each one up in outing.matches, which
  // already carries everything a match card needs.
  function matchesForIds(outing: OutingDetail, ids: number[]): MatchEntry[] {
    const byId = new Map(outing.matches.map((m) => [m.photo.id, m]));
    return ids.map((id) => byId.get(id)).filter((m): m is MatchEntry => Boolean(m));
  }

  // One match card, reused across the To review/Confirmed column and the
  // Needs Match sidebar section -- same interactive suggest/reject/
  // fallback/batch/timezone/duplicate machinery as before, just relocated
  // out of the old single flat grid so it can render in either place.
  function renderMatchCard(outing: OutingDetail, m: MatchEntry) {
    const suggestion = suggestions[m.photo.id];
    const fallback = fallbacks[m.photo.id];
    const resolved = m.observation || m.fallback_common_name;
    // Temporary reference number, kept stable across the whole outing
    // (not just within whichever bucket this card landed in) -- not a
    // permanent design decision, just for talking through specific
    // photos together.
    const displayIndex = outing.matches.findIndex((mm) => mm.photo.id === m.photo.id) + 1;
    // Fallback methods (manual assignment, AI-suggestion accept, fallback
    // ID) all require a person to have looked at this specific photo and
    // agreed -- only a rule-based match has never actually been reviewed
    // by anyone (see issue #32).
    const needsReview = Boolean(m.observation) && !m.reviewed_at;
    // Only worth pointing out right after it happened -- once it's old
    // news (from a previous session), the checkmark is just noise; the
    // plain name is enough.
    const justConfirmed =
      Boolean(m.observation) &&
      !needsReview &&
      Boolean(m.reviewed_at) &&
      (!sessionBoundary || (m.reviewed_at as string) > sessionBoundary);
    // A Label typed by hand (a Note), not an AI guess -- confidence only
    // ever lands on exactly 1 when there was no suggestion behind it to
    // inherit a real value from.
    const isNote = Boolean(m.fallback_common_name) && !m.fallback_scientific_name && m.confidence === 1;
    // eBird-match badge (issue #48, DESIGN.md §10.8) -- a real reported
    // observation, same condition photo_groups.ebird_and_flickr uses.
    const onEbird = Boolean(m.observation);

    return (
      <figure key={m.photo.id} className="card match-card" style={{ margin: 0, overflow: "hidden" }}>
        <div className="match-card-header" style={{ padding: "var(--space-2) var(--space-3) 0" }}>
          <div className="thumb">
            {m.photo.url_medium ? (
              <button
                type="button"
                className="thumb-button"
                aria-label={photoAccessibleLabel(m)}
                onClick={() => setLightboxEntry(outingLightboxEntry(m))}
              >
                <img src={m.photo.url_medium} alt="" />
              </button>
            ) : (
              <div className="photo-placeholder" />
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)", fontWeight: 600 }}>
              #{displayIndex}
            </span>
            <div style={{ marginTop: 2 }}>
              {m.observation ? (
                needsReview ? (
                  <>
                    <span className="badge badge-warning">Needs review</span>
                    <div style={{ marginTop: "var(--space-1)" }}>
                      {m.observation.common_name}
                      {/* Icon shown regardless of whether a scientific
                          name exists -- it's independent data (eBird's
                          per-checklist CSV export has no scientific-name
                          column at all, see conversation with Jen,
                          2026-08-07), so tying the icon's visibility to it
                          would silently hide the icon whenever that gap
                          shows up. */}
                      <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
                        {m.observation.scientific_name && <span style={{ fontStyle: "italic" }}>{m.observation.scientific_name}</span>}
                        {onEbird && <img src={ebirdMatchIcon} alt="Logged on eBird" className="ebird-match-icon" />}
                      </div>
                      {m.note && (
                        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: 2 }}>
                          {m.note}
                        </div>
                      )}
                      <label style={{ marginTop: "var(--space-1)", display: "block", fontSize: "var(--text-xs)" }}>
                        <input
                          type="checkbox"
                          checked={Boolean(checkedPhotos[m.photo.id])}
                          disabled={
                            !checkedPhotos[m.photo.id] &&
                            checkedPhotoIdsIn(
                              outing.matches
                                .filter((mm) => Boolean(mm.observation) && !mm.reviewed_at)
                                .map((mm) => mm.photo.id)
                            ).length >= MAX_BATCH_PHOTOS
                          }
                          onChange={(e) => setCheckedPhotos((prev) => ({ ...prev, [m.photo.id]: e.target.checked }))}
                        />{" "}
                        Select for batch
                      </label>
                    </div>
                  </>
                ) : (
                  <div>
                    {m.observation.common_name}
                    {justConfirmed && (
                      <span
                        aria-label="Confirmed"
                        style={{ color: "var(--success)", marginLeft: "var(--space-1)" }}
                      >
                        ✓
                      </span>
                    )}
                    <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
                      {m.observation.scientific_name && <span style={{ fontStyle: "italic" }}>{m.observation.scientific_name}</span>}
                      {onEbird && <img src={ebirdMatchIcon} alt="Logged on eBird" className="ebird-match-icon" />}
                    </div>
                    {m.note && (
                      <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: 2 }}>{m.note}</div>
                    )}
                  </div>
                )
              ) : m.fallback_common_name ? (
                m.fallback_scientific_name ? (
                  // "Off checklist" badge removed per Jen (issue #41) --
                  // the "add to eBird" link already says everything the
                  // badge did, just without a second label repeating it.
                  <div>
                    {m.fallback_common_name}
                    {m.ebird_checklist_url && (
                      <>
                        {" — "}
                        <a href={m.ebird_checklist_url} target="_blank" rel="noreferrer">
                          add to eBird
                        </a>
                      </>
                    )}
                  </div>
                ) : isNote ? (
                  // A Note -- typed by hand, no AI guess behind it
                  // (confidence is only ever exactly 1 when there was no
                  // suggestion to inherit a real confidence value from).
                  // The Label speaks for itself; "Other" would just be
                  // noise here.
                  <div>{m.fallback_common_name}</div>
                ) : (
                  // An AI guess that didn't resolve to a real eBird
                  // species (e.g. "Dragonfly") -- eBird checklists only
                  // track birds, so there's nothing sensible to "add to
                  // eBird" here. Just confirmed in BirdTrip's own data.
                  <>
                    <span className="badge badge-neutral">Other</span>
                    <div style={{ marginTop: "var(--space-1)" }}>{m.fallback_common_name}</div>
                  </>
                )
              ) : (
                <>
                  <span className="badge badge-neutral">Unmatched</span>
                  <label style={{ marginLeft: "var(--space-2)", fontSize: "var(--text-xs)" }}>
                    <input
                      type="checkbox"
                      checked={Boolean(checkedPhotos[m.photo.id])}
                      disabled={
                        !checkedPhotos[m.photo.id] &&
                        checkedPhotoIdsIn(
                          outing.matches
                            .filter((mm) => !mm.observation && !mm.fallback_common_name)
                            .map((mm) => mm.photo.id)
                        ).length >= MAX_BATCH_PHOTOS
                      }
                      onChange={(e) => setCheckedPhotos((prev) => ({ ...prev, [m.photo.id]: e.target.checked }))}
                    />{" "}
                    Select for batch
                  </label>
                </>
              )}
            </div>
          </div>
        </div>
        <figcaption style={{ padding: "var(--space-2) var(--space-3) var(--space-3)" }}>
          {m.timezone_mismatch && (
            <div
              style={{
                marginTop: "var(--space-2)",
                padding: "var(--space-2)",
                fontSize: "var(--text-xs)",
                background: "var(--warning-bg, #fff3cd)",
                border: "1px solid var(--warning, #e0a800)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              Camera recorded {m.timezone_mismatch.photo_utc_offset}, but this location was on{" "}
              {m.timezone_mismatch.expected_utc_offset} at the time — possible clock/timezone mismatch.
              <div style={{ marginTop: "var(--space-1)" }}>
                <button
                  className="btn"
                  onClick={() => handleAdjustTimezone(m.checklist_id as number, m.photo.id)}
                  disabled={adjustingTimezone[m.photo.id]}
                >
                  {adjustingTimezone[m.photo.id] ? "Adjusting…" : "Adjust"}
                </button>
              </div>
            </div>
          )}
          {m.possible_duplicate && (
            <div
              style={{
                marginTop: "var(--space-2)",
                padding: "var(--space-2)",
                fontSize: "var(--text-xs)",
                background: "var(--warning-bg, #fff3cd)",
                border: "1px solid var(--warning, #e0a800)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              Possible duplicate —{" "}
              {m.possible_duplicate.other_flickr_urls
                .filter((url): url is string => Boolean(url))
                .map((url, i, arr) => (
                  <span key={url}>
                    <a href={url} target="_blank" rel="noreferrer">
                      Update Flickr ↗
                    </a>
                    {i < arr.length - 1 && ", "}
                  </span>
                ))}
            </div>
          )}
        </figcaption>

        {!resolved && !suggestion && (
          <div style={{ padding: "0 var(--space-3) var(--space-2)" }}>
            <select
              value={manualPick[m.photo.id] ?? ""}
              onChange={(e) => setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
              style={{ width: "100%", marginBottom: manualPick[m.photo.id] ? "var(--space-2)" : 0 }}
            >
              {/* Neutral hint until the user actually picks something --
                  nothing below the dropdown until then. "Other" pinned
                  first in the real options, since most unmatched photos
                  here are non-birds or off-checklist. */}
              <option value="" disabled hidden>
                It's actually…
              </option>
              <option value="other">Other</option>
              {outing.observations.map((obs) => (
                <option key={obs.id} value={obs.id}>
                  {obs.common_name}
                </option>
              ))}
            </select>

            {manualPick[m.photo.id] && (
              <>
                {/* Stays visible for a real species pick too, not just
                    Other -- general notes (e.g. "juvenile", "distant/
                    blurry shot") are useful either way. Persisted via
                    Match.note on assign (issue #79). */}
                <input
                  type="text"
                  value={noteText[m.photo.id] ?? ""}
                  onChange={(e) => setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
                  placeholder="Write a note"
                />
                {manualPick[m.photo.id] === "other" ? (
                  <div className="panel-actions" style={{ marginTop: "var(--space-2)" }}>
                    <button className="btn" onClick={() => handleSuggestFallback(outing.id, m.photo.id)}>
                      Ask Pictala
                    </button>
                    <button
                      className="btn btn-primary"
                      disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                      onClick={() => handleSaveNote(outing.id, m.photo.id)}
                    >
                      {savingNote[m.photo.id] ? "Saving…" : "Save note"}
                    </button>
                  </div>
                ) : (
                  <button
                    className="btn btn-primary btn-block"
                    style={{ marginTop: "var(--space-2)" }}
                    onClick={() => handleAssign(outing.id, m.photo.id)}
                  >
                    Assign
                  </button>
                )}
              </>
            )}
          </div>
        )}

        {resolved && needsReview && !suggestion && (
          <>
            <button
              className="btn btn-primary btn-block"
              onClick={() =>
                handleConfirmMatch(outing.id, m.photo.id, (m.observation as NonNullable<typeof m.observation>).id)
              }
            >
              Confirm — this is right
            </button>
            <button
              className="btn"
              onClick={() => handleOpenFix(m.photo.id)}
              style={{
                border: "none",
                background: "none",
                color: "var(--text-faint)",
                fontSize: "var(--text-xs)",
                padding: "var(--space-1) var(--space-3) var(--space-2)",
                width: "100%",
              }}
            >
              It's actually something else
            </button>
          </>
        )}

        {resolved && !needsReview && !suggestion && (
          <button
            className="btn"
            onClick={() => handleOpenFix(m.photo.id)}
            aria-label="Fix this match"
            style={{
              border: "none",
              background: "none",
              color: "var(--text-faint)",
              fontSize: "var(--text-xs)",
              padding: "0 var(--space-3) var(--space-2)",
              width: "100%",
              textAlign: "right",
            }}
          >
            Edit
          </button>
        )}

        {suggestion?.status === "loading" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", padding: "0 var(--space-3) var(--space-2)" }}>Thinking…</p>
        )}

        {suggestion?.status === "accepting" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", padding: "0 var(--space-3) var(--space-2)" }}>Saving…</p>
        )}

        {suggestion?.status === "error" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--danger)", padding: "0 var(--space-3) var(--space-2)" }}>{suggestion.message}</p>
        )}

        {suggestion?.status === "ready" && (
          <div className="panel">
            {suggestion.data.suggested_observation_id != null ? (
              <>
                <div>
                  AI suggests: <strong>{suggestion.data.suggested_common_name}</strong>
                </div>
                <div className="panel-reasoning">{suggestion.data.reasoning}</div>
                <div className="panel-actions">
                  <button
                    className="btn btn-primary"
                    onClick={() =>
                      handleAccept(
                        outing.id,
                        m.photo.id,
                        suggestion.data.suggested_observation_id as number,
                        suggestion.data.confidence,
                        suggestion.data.suggested_common_name
                      )
                    }
                  >
                    Accept
                  </button>
                  <button className="btn btn-danger" onClick={() => handleReject(outing.id, m.photo.id)}>
                    Reject
                  </button>
                </div>
              </>
            ) : (
              <>
                <div>No confident match among this outing's species.</div>
                <div className="panel-reasoning">{suggestion.data.reasoning}</div>

                <div style={{ marginTop: "var(--space-2)" }}>
                  <select
                    value={manualPick[m.photo.id] ?? ""}
                    onChange={(e) => setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
                    style={{ maxWidth: "100%" }}
                  >
                    <option value="">It's actually…</option>
                    {outing.observations.map((obs) => (
                      <option key={obs.id} value={obs.id}>
                        {obs.common_name}
                      </option>
                    ))}
                  </select>{" "}
                  <button
                    className="btn btn-primary"
                    disabled={!manualPick[m.photo.id]}
                    onClick={() => handleAssign(outing.id, m.photo.id)}
                  >
                    Assign
                  </button>
                </div>

                <div className="panel-actions">
                  <button className="btn" onClick={() => handleSuggestFallback(outing.id, m.photo.id)}>
                    Ask Pictala
                  </button>
                  <button className="btn" onClick={() => handleDismissRejected(m.photo.id)}>
                    Dismiss
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {suggestion?.status === "rejected" && (
          <div className="panel">
            <div>Rejected — what should this be instead?</div>

            <div style={{ marginTop: "var(--space-2)" }}>
              <select
                value={manualPick[m.photo.id] ?? ""}
                onChange={(e) => setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
                style={{ maxWidth: "100%" }}
              >
                <option value="">It's actually…</option>
                {outing.observations.map((obs) => (
                  <option key={obs.id} value={obs.id}>
                    {obs.common_name}
                  </option>
                ))}
              </select>{" "}
              <button
                className="btn btn-primary"
                disabled={!manualPick[m.photo.id]}
                onClick={() => handleAssign(outing.id, m.photo.id)}
              >
                Assign
              </button>
            </div>

            <div style={{ marginTop: "var(--space-2)" }}>
              <input
                type="text"
                value={noteText[m.photo.id] ?? ""}
                onChange={(e) => setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
                placeholder="Or write a note"
              />
              <button
                className="btn btn-primary"
                disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                onClick={() => handleSaveNote(outing.id, m.photo.id)}
              >
                {savingNote[m.photo.id] ? "Saving…" : "Save note"}
              </button>
            </div>

            <div className="panel-actions">
              <button className="btn" onClick={() => handleSuggestFallback(outing.id, m.photo.id)}>
                Ask Pictala
              </button>
              <button className="btn" onClick={() => handleDismissRejected(m.photo.id)}>
                Dismiss
              </button>
            </div>
          </div>
        )}

        {suggestion?.status === "editing" && (
          <div className="panel">
            <input
              type="text"
              value={noteText[m.photo.id] ?? ""}
              onChange={(e) => setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
              placeholder="What is it? (matches the checklist if it's on there)"
            />
            <div className="panel-actions" style={{ marginTop: 0 }}>
              <button
                className="btn btn-primary"
                disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                onClick={() => handleSaveNote(outing.id, m.photo.id)}
              >
                {savingNote[m.photo.id] ? "Saving…" : "Save"}
              </button>
              <button className="btn" onClick={() => handleSuggestFallback(outing.id, m.photo.id)}>
                Ask Pictala
              </button>
              <button className="btn" onClick={() => handleDismissRejected(m.photo.id)}>
                Dismiss
              </button>
            </div>
          </div>
        )}

        {fallback?.status === "loading" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", padding: "0 var(--space-3) var(--space-2)" }}>Thinking…</p>
        )}

        {fallback?.status === "accepting" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", padding: "0 var(--space-3) var(--space-2)" }}>Saving…</p>
        )}

        {fallback?.status === "error" && (
          <p style={{ fontSize: "var(--text-xs)", color: "var(--danger)", padding: "0 var(--space-3) var(--space-2)" }}>{fallback.message}</p>
        )}

        {fallback?.status === "ready" && (
          <div className="panel">
            {(() => {
              // Claude's guess isn't checked against this outing's own
              // species -- an unconstrained guess can land on something
              // that's actually on the checklist. Check here so the
              // messaging matches what accept-fallback will actually do
              // with it. Computed from the live, editable fallbackText
              // value (issue #78), not the original unedited guess --
              // otherwise editing the pre-filled text before saving could
              // leave this hint describing a name that's no longer what
              // will actually be submitted.
              const currentGuess = fallbackText[m.photo.id] ?? fallback.data.common_name;
              const onChecklist =
                fallback.data.species_code != null &&
                outing.observations.some(
                  (obs) => obs.common_name.toLowerCase() === currentGuess?.toLowerCase()
                );
              return (
                <>
                  <div>
                    {fallback.data.species_code ? (
                      <>
                        Broader guess: <strong>{fallback.data.common_name}</strong>
                      </>
                    ) : fallback.data.is_other && !fallback.data.is_bird ? (
                      <>
                        Not a bird — best guess: <strong>{fallback.data.common_name}</strong>
                      </>
                    ) : fallback.data.is_other && fallback.data.is_bird ? (
                      <>
                        Looks like a bird, but the name didn't match eBird's taxonomy:{" "}
                        <strong>{fallback.data.common_name}</strong>
                      </>
                    ) : fallback.data.is_bird ? (
                      "Couldn't confidently identify the species."
                    ) : (
                      "Doesn't look like a bird, and couldn't guess what it is."
                    )}
                  </div>
                  <div className="panel-reasoning">{fallback.data.reasoning}</div>
                  {fallback.data.species_code && (
                    <div className="panel-note">
                      {onChecklist
                        ? "Actually on this checklist -- saving will link it properly."
                        : "Not on this checklist — saving labels the photo only, and won't be written back to eBird."}
                    </div>
                  )}
                </>
              );
            })()}
            <input
              type="text"
              value={fallbackText[m.photo.id] ?? ""}
              onChange={(e) => setFallbackText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))}
              placeholder="Accept the guess above, or write your own note"
            />
            <div className="panel-actions" style={{ marginTop: 0 }}>
              <button
                className="btn btn-primary"
                disabled={!(fallbackText[m.photo.id] ?? "").trim()}
                onClick={() => handleAcceptFallback(outing.id, m.photo.id, fallback.data)}
              >
                Save
              </button>
              <button className="btn" onClick={() => handleDismissFallback(m.photo.id)}>
                Dismiss
              </button>
            </div>
          </div>
        )}
      </figure>
    );
  }

  return (
    <div>
      <header className="app-header">
        <span className="wordmark">Pictala</span>
        <p>Your eBird outings, matched with your Flickr photos.</p>
      </header>

      <div className="app-shell" style={{ padding: "0 var(--space-5)" }}>
      <h1 className="page-title">Browse Trips</h1>
      {error && (
        <p className="badge badge-danger" style={{ display: "block", padding: "var(--space-2) var(--space-3)", marginBottom: "var(--space-4)" }}>
          {error} — is the backend running at localhost:8000? (`uvicorn app.main:app --reload`)
        </p>
      )}

      <form onSubmit={handleSearch} role="search" style={{ marginBottom: "var(--space-5)" }}>
        <label htmlFor="species-search" style={{ display: "block", marginBottom: "var(--space-1)", fontSize: "var(--text-sm)" }}>
          Search by species
        </label>
        <input
          id="species-search"
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="e.g. Bald Eagle"
          disabled={outings.length === 0}
          style={{ padding: "var(--space-2)", width: 220, border: "1px solid var(--border-strong)", borderRadius: "var(--radius-sm)", fontSize: "var(--text-sm)" }}
        />
        <button type="submit" className="btn btn-primary" disabled={outings.length === 0 || !searchQuery.trim() || searching} style={{ marginLeft: "var(--space-2)" }}>
          {searching ? "Searching…" : "Search"}
        </button>
        {searchResults !== null && (
          <button type="button" className="btn" onClick={clearSearch} style={{ marginLeft: "var(--space-2)" }}>
            Clear search
          </button>
        )}
        {/* Nothing to search yet on a brand-new install (issue #58) --
            disabled rather than left active against an empty dataset. */}
        {outings.length === 0 && (
          <div style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)", marginTop: 2 }}>
            Sync your first outing to search by species.
          </div>
        )}
      </form>

      {searchResults !== null ? (
        <div>
          <h2>Search results for "{searchQuery}"</h2>
          {searchResults.length === 0 ? (
            <p>No matched photos found for that species.</p>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)" }}>
              {searchResults.map((r) => (
                <figure key={r.photo.id} className="card photo-card" style={{ width: 200, margin: 0, overflow: "hidden" }}>
                  {r.photo.url_medium ? (
                    <img src={r.photo.url_medium} alt={r.photo.title ?? r.common_name} width={200} style={{ width: 200, height: 140, objectFit: "cover", display: "block" }} />
                  ) : (
                    <div className="photo-placeholder" style={{ width: 200, height: 140 }} />
                  )}
                  <figcaption style={{ fontSize: "var(--text-sm)", padding: "var(--space-2) var(--space-3) var(--space-3)" }}>
                    <strong>{r.common_name}</strong>
                    <br />
                    <span style={{ color: "var(--text-muted)" }}>{r.location_name} · {r.date}</span>
                    <br />
                    {r.photo.flickr_url && (
                      <a href={r.photo.flickr_url} target="_blank" rel="noreferrer">
                        View on Flickr
                      </a>
                    )}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>
      ) : (
      <div className="browse-shell">
        {/* minWidth alone let this balloon to ~790px in the "Photos not
            on eBird" view: with flex-basis:auto and no competing pressure
            from that sibling's plain wrapping text (unlike the outing-
            detail view's fixed-width match cards, which happen to force
            enough shrinkage to mask the same underlying issue), the
            sidebar sized itself to its widest *unwrapped* line of text
            (a long paragraph in the sync panel) instead of wrapping
            within a sane width. maxWidth forces wrapping regardless of
            what's on the other side of the flex row. */}
        <div style={{ minWidth: 260, maxWidth: 360, flexShrink: 0 }}>
          {/* "Last 3 trips" -- promoted to the hero position per DESIGN.md
              §10.1 (resolved): the actual point of the app (what you saw
              + what you shot) leads, instead of the calendar being the
              first thing shown. Only shown unfiltered -- once a specific
              date is picked, the flow is about that date, not "browse
              recent trips" (per docs/mockups/entry-screen-mockup.html's
              intent; that mockup didn't model the date-filter interaction
              at all, so this is a judgment call, not a resolved decision
              itself). Thumbnail is the first Flickr photo found on that
              outing (any match status, not filtered to confirmed-only --
              see tripThumbnails effect above); an eBird-only outing with
              genuinely zero photos gets a larger eBird-match icon instead
              of a generic pin, same icon/meaning used elsewhere in the
              app (DESIGN.md §10.8) rather than a new symbol. */}
          {!selectedDate && outings.length > 0 && (
            <div className="trip-list">
              <h2 className="section-heading" style={{ fontSize: "var(--text-lg)", fontWeight: 700, margin: "0 0 var(--space-3)" }}>
                Last 3 trips
              </h2>
              {outings.slice(0, 3).map((o) => (
                <button key={o.id} className="trip-card" onClick={() => openOuting(o.id)}>
                  {tripThumbnails[o.id] ? (
                    <img className="trip-thumb" src={tripThumbnails[o.id] as string} alt="" />
                  ) : o.photo_count === 0 ? (
                    <span className="trip-thumb placeholder" aria-hidden="true">
                      <img src={ebirdMatchIcon} alt="" style={{ width: 30, height: 30, objectFit: "contain" }} />
                    </span>
                  ) : (
                    <span className="trip-thumb placeholder" aria-hidden="true">
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/>
                        <circle cx="12" cy="10" r="2.5"/>
                      </svg>
                    </span>
                  )}
                  <span className="trip-info">
                    <span className="name">{o.location_name}</span>
                    <br />
                    <span className="meta">{o.date} · {o.species_count} species · {o.photo_count} photos</span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Calendar -- demoted to a compact secondary widget (DESIGN.md
              §10.1, resolved). Same DatePicker component/functionality as
              before (date selection, disabled/unavailable dates) -- only
              the visual treatment (smaller cells via react-day-picker's
              own CSS vars, muted eyebrow label) changed. */}
          <div className="calendar-compact">
            <div className="cal-eyebrow">Trip activity</div>
            <DatePicker
              availableDates={availableDates}
              selected={selectedDate}
              onSelect={setSelectedDate}
            />
          </div>
          {selectedDate && (
            <button
              className="btn"
              onClick={() => setSelectedDate(null)}
              style={{ marginBottom: "var(--space-3)" }}
            >
              Clear date — show all outings
            </button>
          )}

          {/* Collapsed by default (issue: "layout is difficult to read") --
              the full outings list can get very long (dozens of entries)
              and was previously always fully expanded, dominating the
              page. Reuses the same collapsible pattern as the outing-
              detail sidebar sections below for visual consistency. Stays
              open once a date is picked -- that's a short, actively-
              relevant list, not the long unfiltered one. Placed right
              below the calendar (DESIGN.md follow-up, 2026-09-14) so
              picking a date shows its outings without scrolling past the
              sync panel first. */}
          <details className="outing-sidebar-section" open={Boolean(selectedDate)}>
            <summary className="outing-col-header">
              <span className="outing-count-badge" style={{ background: "var(--neutral-bg)", color: "var(--neutral)" }}>
                {visibleOutings.length}
              </span>
              <h3 className="outing-col-title">{selectedDate ? "Outings on this date" : "All Trips"}</h3>
            </summary>
            <ul style={{ listStyle: "none", padding: 0, marginTop: "var(--space-2)" }}>
              {visibleOutings.map((o) => (
                <li key={o.id} style={{ marginBottom: "var(--space-3)" }}>
                  <button
                    className="list-item-btn"
                    onClick={() => openOuting(o.id)}
                  >
                    <strong>{o.location_name}</strong>
                    <br />
                    <span style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
                      {o.date} · {o.species_count} species · {o.photo_count} photos
                    </span>
                  </button>
                </li>
              ))}
              {outings.length === 0 && !error && <li>No outings yet — sync eBird + Flickr data first.</li>}
              {outings.length > 0 && visibleOutings.length === 0 && (
                <li>No eBird outing found for this date.</li>
              )}
            </ul>

            {clustersForSelectedDate.length > 0 && (
              <button className="btn" onClick={viewClustersForDate} style={{ marginBottom: "var(--space-3)" }}>
                {clustersForSelectedDate.reduce((sum, c) => sum + c.photo_count, 0)} photos not on eBird for this date
              </button>
            )}
          </details>

          <SyncPanel
            syncStatus={syncStatus}
            onSynced={(status, freshOutings) => {
              setSyncStatus(status);
              setOutings(freshOutings);
            }}
            onError={(message) => setError(message)}
          />

          <button className="btn" onClick={loadUnassigned} style={{ marginTop: "var(--space-3)" }}>
            Show all photos not on eBird
          </button>
        </div>

        {showUnassigned && (
          <div style={{ flex: 1 }}>
            {selectedCluster ? (
              <>
                <button className="btn" onClick={() => setSelectedCluster(null)} style={{ marginBottom: "var(--space-3)" }}>
                  ← Back to clusters
                </button>
                <h2>{selectedCluster.date} — not on eBird</h2>
                {checkedPhotoIdsIn(selectedCluster.matches.map((m) => m.photo.id)).length > 0 && (
                  <button
                    className="btn btn-primary"
                    style={{ marginBottom: "var(--space-3)" }}
                    onClick={handleClusterSuggestBatch}
                    disabled={batchSuggesting}
                  >
                    {batchSuggesting
                      ? "Asking…"
                      : `Ask Pictala at ${checkedPhotoIdsIn(selectedCluster.matches.map((m) => m.photo.id)).length} selected`}
                  </button>
                )}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)" }}>
                  {selectedCluster.matches.map((m) => {
                    const identified = Boolean(m.fallback_common_name);
                    return (
                      <figure key={m.photo.id} className="card photo-card" style={{ margin: 0, overflow: "hidden" }}>
                        {m.photo.url_medium ? (
                          <button
                            type="button"
                            className="thumb-button"
                            aria-label={photoAccessibleLabel(m)}
                            onClick={() => setLightboxEntry(clusterLightboxEntry(m))}
                          >
                            <img src={m.photo.url_medium} alt="" width={180} />
                          </button>
                        ) : (
                          <div className="photo-placeholder" />
                        )}
                        <figcaption style={{ padding: "var(--space-2) var(--space-3) var(--space-3)" }}>
                          {identified ? (
                            <div style={{ marginBottom: "var(--space-1)" }}>
                              {!m.fallback_scientific_name && (
                                <span className="badge badge-neutral">Not on eBird</span>
                              )}
                              <div style={{ marginTop: "var(--space-1)" }}>
                                {m.fallback_common_name}
                                {m.fallback_scientific_name && (
                                  <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", fontStyle: "italic" }}>
                                    {m.fallback_scientific_name}
                                  </div>
                                )}
                              </div>
                            </div>
                          ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                              <label style={{ fontSize: "var(--text-xs)" }}>
                                <input
                                  type="checkbox"
                                  checked={Boolean(checkedPhotos[m.photo.id])}
                                  disabled={
                                    !checkedPhotos[m.photo.id] &&
                                    checkedPhotoIdsIn(selectedCluster.matches.map((mm) => mm.photo.id)).length >=
                                      MAX_BATCH_PHOTOS
                                  }
                                  onChange={(e) =>
                                    setCheckedPhotos((prev) => ({ ...prev, [m.photo.id]: e.target.checked }))
                                  }
                                />{" "}
                                Select for batch
                              </label>
                              <input
                                type="text"
                                placeholder="Species name or note"
                                value={clusterIdentifyText[m.photo.id] ?? ""}
                                onChange={(e) =>
                                  setClusterIdentifyText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                                }
                                style={{ width: "100%" }}
                              />
                              <div>
                                <button
                                  className="btn btn-primary"
                                  onClick={() => handleClusterIdentify(m.photo.id)}
                                  disabled={!(clusterIdentifyText[m.photo.id] ?? "").trim() || clusterSaving[m.photo.id]}
                                >
                                  {clusterSaving[m.photo.id] ? "Saving…" : "Save"}
                                </button>{" "}
                                <button
                                  className="btn"
                                  onClick={() => handleClusterSuggest(m.photo.id)}
                                  disabled={clusterSuggesting[m.photo.id]}
                                >
                                  {clusterSuggesting[m.photo.id] ? "Asking…" : "Ask Pictala"}
                                </button>
                              </div>
                              <div
                                style={{
                                  marginTop: "var(--space-2)",
                                  paddingTop: "var(--space-2)",
                                  borderTop: "1px solid var(--border)",
                                }}
                              >
                                <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginBottom: "var(--space-1)" }}>
                                  Or assign to a checklist directly:
                                </div>
                                <select
                                  value={assignToChecklistPick[m.photo.id] ?? ""}
                                  onChange={(e) => handlePickAssignChecklist(m.photo.id, e.target.value)}
                                  style={{ width: "100%", fontSize: "var(--text-xs)", marginBottom: "var(--space-1)" }}
                                >
                                  <option value="">Pick a checklist…</option>
                                  {outings
                                    .slice()
                                    .sort(
                                      (a, b) =>
                                        Math.abs(new Date(a.date).getTime() - new Date(selectedCluster.date).getTime()) -
                                        Math.abs(new Date(b.date).getTime() - new Date(selectedCluster.date).getTime())
                                    )
                                    .map((o) => (
                                      <option key={o.id} value={o.id}>
                                        {o.location_name} — {o.date}
                                      </option>
                                    ))}
                                </select>
                                {assignToSpeciesOptions[m.photo.id] && (
                                  <>
                                    <select
                                      value={assignToSpeciesPick[m.photo.id] ?? ""}
                                      onChange={(e) =>
                                        setAssignToSpeciesPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                                      }
                                      style={{ width: "100%", fontSize: "var(--text-xs)", marginBottom: "var(--space-1)" }}
                                    >
                                      <option value="">Pick a species…</option>
                                      {assignToSpeciesOptions[m.photo.id].map((obs) => (
                                        <option key={obs.id} value={obs.id}>
                                          {obs.common_name}
                                        </option>
                                      ))}
                                    </select>
                                    <button
                                      className="btn btn-primary"
                                      onClick={() => handleAssignToChecklist(m.photo.id)}
                                      disabled={!assignToSpeciesPick[m.photo.id] || assigningToChecklist[m.photo.id]}
                                    >
                                      {assigningToChecklist[m.photo.id] ? "Assigning…" : "Assign"}
                                    </button>
                                  </>
                                )}
                              </div>
                            </div>
                          )}
                          {clusters.filter((c) => c.date === selectedCluster.date && c.id !== selectedCluster.id).length > 0 && (
                            <select
                              value=""
                              onChange={(e) => handleMoveToCluster(m.photo.id, e.target.value)}
                              style={{ marginTop: "var(--space-2)", width: "100%", fontSize: "var(--text-xs)" }}
                            >
                              <option value="">Move to another group…</option>
                              {clusters
                                .filter((c) => c.date === selectedCluster.date && c.id !== selectedCluster.id)
                                .map((c) => (
                                  <option key={c.id} value={c.id}>
                                    Group of {c.photo_count} ({c.id})
                                  </option>
                                ))}
                            </select>
                          )}
                          {m.possible_duplicate && (
                            <div
                              style={{
                                marginTop: "var(--space-2)",
                                padding: "var(--space-2)",
                                fontSize: "var(--text-xs)",
                                background: "var(--warning-bg, #fff3cd)",
                                border: "1px solid var(--warning, #e0a800)",
                                borderRadius: "var(--radius-sm)",
                              }}
                            >
                              Possible duplicate —{" "}
                              {m.possible_duplicate.other_flickr_urls
                                .filter((url): url is string => Boolean(url))
                                .map((url, i, arr) => (
                                  <span key={url}>
                                    <a href={url} target="_blank" rel="noreferrer">
                                      Update Flickr ↗
                                    </a>
                                    {i < arr.length - 1 && ", "}
                                  </span>
                                ))}
                            </div>
                          )}
                        </figcaption>
                      </figure>
                    );
                  })}
                </div>
              </>
            ) : (
              <>
                <h2>{clusterDateFilter ? `Photos not on eBird — ${clusterDateFilter}` : "Photos not on eBird"}</h2>
                <p style={{ color: "var(--text-muted)" }}>
                  Grouped by date and capture-time proximity — no checklist to group by instead.
                </p>
                {clusterDateFilter && (
                  <button className="btn" onClick={() => setClusterDateFilter(null)} style={{ marginBottom: "var(--space-3)" }}>
                    Show all dates
                  </button>
                )}
                <ul style={{ listStyle: "none", padding: 0 }}>
                  {clusters
                    .filter((c) => !clusterDateFilter || c.date === clusterDateFilter)
                    .map((c) => (
                      <li key={c.id} style={{ marginBottom: "var(--space-3)" }}>
                        <button className="list-item-btn" onClick={() => openCluster(c.id)}>
                          <strong>{c.date}</strong>
                          <br />
                          <span style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
                            {c.photo_count} photos
                          </span>
                        </button>
                      </li>
                    ))}
                  {clusters.length === 0 && <li>No checklist-less photos — everything's on eBird.</li>}
                </ul>
              </>
            )}
          </div>
        )}

        {!showUnassigned && selected && (
          <div style={{ flex: 1 }}>
            <h2>
              {selected.location_name} — {selected.date}
            </h2>
            {/* Minimal surface for the stored reviewed state (issue #43)
                -- not the grouped review layout, just enough to actually
                use the flag while that design isn't settled yet. */}
            <p style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
              {selected.reviewed_at ? (
                <>
                  Reviewed{" "}
                  <button className="btn" onClick={() => handleToggleReviewed(selected.id, false)}>
                    Unmark
                  </button>
                </>
              ) : (
                (() => {
                  // Same "confirmed" test as the lightbox badge (issue #47):
                  // an eBird-backed match needs its own review, a
                  // fallback-labeled photo already required a person to
                  // agree, and an unmatched photo isn't confirmed at all.
                  const allConfirmed = selected.matches.every((m) =>
                    m.observation ? Boolean(m.reviewed_at) : Boolean(m.fallback_common_name)
                  );
                  return (
                    <button
                      className="btn"
                      onClick={() => handleToggleReviewed(selected.id, true)}
                      disabled={!allConfirmed}
                      title={allConfirmed ? undefined : "Every photo needs to be confirmed before this outing can be marked reviewed"}
                    >
                      Mark outing reviewed
                    </button>
                  );
                })()
              )}
            </p>
            {(() => {
              const groups = selected.photo_groups;
              const toReviewOrConfirmed = matchesForIds(selected, [
                ...groups.ebird_and_flickr,
                ...groups.flickr_best_guess,
              ]);
              const needsClaudeMatches = matchesForIds(selected, groups.needs_claude);
              const noPhotoObservations = selected.observations.filter((o) =>
                groups.ebird_no_photo.includes(o.id)
              );
              const reviewed = Boolean(selected.reviewed_at);
              const primaryTitle = reviewed ? "Confirmed" : "To review";
              // Split by type -- a checkbox in this column now covers two
              // different eligible states (issue #50: needs-review matches
              // for batch confirm, alongside the existing unmatched photos
              // for batch Ask Pictala), so "checked" alone is ambiguous.
              const needsReviewInPrimary = checkedPhotoIdsIn(
                toReviewOrConfirmed.filter((m) => Boolean(m.observation) && !m.reviewed_at).map((m) => m.photo.id)
              );
              // Unmatched (needs_claude) photos can never appear in
              // ebird_and_flickr/flickr_best_guess -- outing_review.py's
              // compute_photo_groups puts a photo in exactly one bucket,
              // and needs_claude is specifically "no observation, no
              // fallback." Their checkboxes render in needsClaudeMatches
              // (the sidebar), so the checked count has to come from
              // there too, not from toReviewOrConfirmed.
              const checkedNeedsClaude = checkedPhotoIdsIn(needsClaudeMatches.map((m) => m.photo.id));

              return (
                <div className="outing-grid">
                  <div>
                    <div className="outing-col-header">
                      <span className="outing-count-badge">{toReviewOrConfirmed.length}</span>
                      <h3 className="outing-col-title">{primaryTitle}</h3>
                    </div>
                    {needsReviewInPrimary.length > 0 && (
                      <button
                        className="btn btn-primary"
                        style={{ marginBottom: "var(--space-2)", marginRight: "var(--space-2)" }}
                        onClick={() => handleConfirmBatch(selected.id)}
                        disabled={batchConfirming}
                      >
                        {batchConfirming ? "Confirming…" : `Confirm ${needsReviewInPrimary.length} selected`}
                      </button>
                    )}
                    {lastBatchConfirm && lastBatchConfirm.checklistId === selected.id && (
                      <div
                        className="card"
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "var(--space-3)",
                          padding: "var(--space-2) var(--space-3)",
                          marginBottom: "var(--space-2)",
                        }}
                      >
                        <span style={{ fontSize: "var(--text-sm)" }}>
                          Confirmed {lastBatchConfirm.photoIds.length} photo
                          {lastBatchConfirm.photoIds.length === 1 ? "" : "s"}.
                        </span>
                        <button className="btn" onClick={handleUndoBatchConfirm} disabled={undoingBatchConfirm}>
                          {undoingBatchConfirm ? "Undoing…" : "Undo"}
                        </button>
                      </div>
                    )}
                    <div className="outing-match-grid">
                      {toReviewOrConfirmed.map((m) => renderMatchCard(selected, m))}
                      {toReviewOrConfirmed.length === 0 && <p>No photos matched this outing yet.</p>}
                    </div>
                  </div>

                  <div className="outing-sidebar">
                    {needsClaudeMatches.length > 0 && (
                      <div>
                        <div className="outing-col-header">
                          <span className="outing-count-badge" style={{ background: "var(--neutral-bg)", color: "var(--neutral)" }}>
                            {needsClaudeMatches.length}
                          </span>
                          <h3 className="outing-col-title">Needs Match</h3>
                        </div>
                        {checkedNeedsClaude.length > 0 && (
                          <div style={{ marginBottom: "var(--space-3)" }}>
                            <button
                              className="btn btn-primary"
                              style={{ marginBottom: "var(--space-2)" }}
                              onClick={() => handleSuggestFallbackBatch(selected.id)}
                              disabled={batchSuggesting}
                            >
                              {batchSuggesting ? "Asking…" : `Ask Pictala at ${checkedNeedsClaude.length} selected`}
                            </button>
                            <div style={{ display: "flex", gap: "var(--space-2)" }}>
                              <select
                                value={batchAssignPick}
                                onChange={(e) => setBatchAssignPick(e.target.value)}
                                style={{ flex: 1, minWidth: 0 }}
                              >
                                <option value="">It's actually…</option>
                                {selected.observations.map((obs) => (
                                  <option key={obs.id} value={obs.id}>
                                    {obs.common_name}
                                  </option>
                                ))}
                              </select>
                              <button
                                className="btn btn-primary"
                                disabled={!batchAssignPick || batchAssigning}
                                onClick={() => handleAssignBatch(selected.id)}
                              >
                                {batchAssigning ? "Assigning…" : `Assign ${checkedNeedsClaude.length} selected`}
                              </button>
                            </div>
                          </div>
                        )}
                        <div className="outing-match-grid">
                          {needsClaudeMatches.map((m) => renderMatchCard(selected, m))}
                        </div>
                      </div>
                    )}

                    {/* "No photos on Flickr" -- a species entry, not a
                        photo card, in its own collapsed-by-default list.
                        Originally gated behind full-outing review
                        (DESIGN.md §10.3's "after review" bucket), moved
                        to always-visible-when-non-empty per Jen: a
                        species having no photo doesn't actually depend on
                        anything else in the outing being resolved first,
                        unlike Confirmed/Not-a-bird which do -- gating it
                        just hid real data behind unrelated unresolved
                        photos (School Pond, 2026-08-11 review: 4 no-photo
                        species invisible behind 14 unrelated Needs-Claude
                        photos). Note: the mockup's fourth post-review
                        bucket, "Not a bird," has no backend representation
                        yet (see app/services/outing_review.py) -- there's
                        currently no way to distinguish "still needs
                        Claude" from "Claude looked and it's not a bird,"
                        so it's omitted here rather than faked. */}
                    {noPhotoObservations.length > 0 && (
                      <details className="outing-sidebar-section" open>
                        <summary className="outing-col-header">
                          <span className="outing-count-badge" style={{ background: "var(--neutral-bg)", color: "var(--neutral)" }}>
                            {noPhotoObservations.length}
                          </span>
                          <h3 className="outing-col-title">No photos on Flickr</h3>
                        </summary>
                        <ul className="no-photo-list">
                          {noPhotoObservations.map((obs) => (
                            <li key={obs.id} className="no-photo-item">
                              <div style={{ fontSize: "var(--text-sm)", fontWeight: 700 }}>{obs.common_name}</div>
                              {obs.scientific_name && (
                                <div style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)", fontStyle: "italic" }}>
                                  {obs.scientific_name}
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        )}
      </div>
      )}
      </div>

      {lightboxEntry && <PhotoLightbox entry={lightboxEntry} onClose={closeLightbox} />}
    </div>
  );
}
