import { FormEvent, useEffect, useState } from "react";
import {
  fetchOutings,
  fetchOuting,
  suggestSpecies,
  acceptSuggestion,
  assignSpecies,
  suggestFallback,
  suggestFallbackBatch,
  acceptFallback,
  searchBySpecies,
  fetchSyncStatus,
  runSync,
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
} from "./api";
import DatePicker from "./DatePicker";
import "./theme.css";

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

  // Manual "Sync now" button (docs/USER_STORIES.md, "Story: Manual
  // sync") -- capped server-side at 4/day. confirmLastSync gates the
  // last available sync of the day behind an explicit "sync anyway"
  // step, so a click doesn't silently burn the last one.
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [confirmLastSync, setConfirmLastSync] = useState(false);

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
  const [clusterSaving, setClusterSaving] = useState<Record<number, boolean>>({});

  // Batch "Ask Claude" (issue #5) -- a checkbox per unmatched/checklist-
  // less photo, keyed by photo id (globally unique, so one map covers
  // both the outing detail and cluster views). MAX_BATCH_PHOTOS mirrors
  // the backend's cap (species_classifier.MAX_BATCH_SIZE) so the button
  // disables before a request that would just get rejected.
  const [checkedPhotos, setCheckedPhotos] = useState<Record<number, boolean>>({});
  const [batchSuggesting, setBatchSuggesting] = useState(false);
  const MAX_BATCH_PHOTOS = 10;

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

  async function performSync() {
    setSyncing(true);
    setConfirmLastSync(false);
    try {
      await runSync();
      const [status, freshOutings] = await Promise.all([fetchSyncStatus(), fetchOutings()]);
      setSyncStatus(status);
      setOutings(freshOutings);
    } catch (e) {
      setError(String(e));
    } finally {
      setSyncing(false);
    }
  }

  function handleSyncClick() {
    // Warn before the last available sync of the day rather than just
    // burning it, so the user can choose to wait for more Flickr
    // uploads first.
    if (syncStatus && syncStatus.remaining === 1 && !confirmLastSync) {
      setConfirmLastSync(true);
      return;
    }
    performSync();
  }

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
      await identifyUnassignedPhoto(selectedCluster.id, photoId, text);
      setSelectedCluster(await fetchUnassignedCluster(selectedCluster.id));
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

  async function handleAccept(checklistId: number, photoId: number, observationId: number, confidence: number) {
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await acceptSuggestion(checklistId, photoId, observationId, confidence);
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

  function handleReject(photoId: number) {
    // Nothing was ever saved. Previously this just cleared the guess
    // entirely; now it hands off to the same follow-up panel as "no
    // confident match" (manual dropdown, broader ID, a plain note),
    // since a wrong suggestion and no suggestion both mean "this
    // proposed answer isn't right."
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "rejected" } }));
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
      await assignSpecies(checklistId, photoId, observationId);
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
    const photoIds = checkedPhotoIdsIn(selected.matches.map((m) => m.photo.id));
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
      await acceptFallback(checklistId, photoId, text, suggestion.confidence);
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

  return (
    <div>
      <header className="app-header">
        <h1>BirdTrip</h1>
        <p>Your eBird outings, matched with your Flickr photos.</p>
      </header>

      <div className="app-shell" style={{ padding: "0 var(--space-5)" }}>
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
          style={{ padding: "var(--space-2)", width: 220, border: "1px solid var(--border-strong)", borderRadius: "var(--radius-sm)", fontSize: "var(--text-sm)" }}
        />
        <button type="submit" className="btn btn-primary" disabled={!searchQuery.trim() || searching} style={{ marginLeft: "var(--space-2)" }}>
          {searching ? "Searching…" : "Search"}
        </button>
        {searchResults !== null && (
          <button type="button" className="btn" onClick={clearSearch} style={{ marginLeft: "var(--space-2)" }}>
            Clear search
          </button>
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
      <div style={{ display: "flex", gap: "var(--space-6)" }}>
        <div style={{ minWidth: 260 }}>
          <DatePicker
            availableDates={availableDates}
            selected={selectedDate}
            onSelect={setSelectedDate}
          />
          {selectedDate && (
            <button
              className="btn"
              onClick={() => setSelectedDate(null)}
              style={{ marginBottom: "var(--space-3)" }}
            >
              Clear date — show all outings
            </button>
          )}

          <div className="card" style={{ marginBottom: "var(--space-4)", padding: "var(--space-3)" }}>
            {syncStatus && (
              <div style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)", marginBottom: "var(--space-2)" }}>
                {syncStatus.remaining > 0
                  ? `${syncStatus.remaining} of ${syncStatus.limit} syncs left today`
                  : "No syncs left today — resets at midnight"}
                {syncStatus.last_synced_at && (
                  <>
                    <br />
                    Last synced {new Date(syncStatus.last_synced_at).toLocaleTimeString()}
                  </>
                )}
              </div>
            )}
            {confirmLastSync ? (
              <div>
                <p style={{ fontSize: "var(--text-sm)", marginBottom: "var(--space-2)" }}>
                  This is your last sync available today. Wait for more Flickr uploads first?
                </p>
                <button className="btn btn-primary" onClick={performSync} disabled={syncing}>
                  {syncing ? "Syncing…" : "Sync anyway"}
                </button>{" "}
                <button className="btn" onClick={() => setConfirmLastSync(false)}>
                  Wait
                </button>
              </div>
            ) : (
              <button
                className="btn"
                onClick={handleSyncClick}
                disabled={syncing || syncStatus?.remaining === 0}
              >
                {syncing ? "Syncing…" : "Sync now"}
              </button>
            )}
          </div>

          <ul style={{ listStyle: "none", padding: 0 }}>
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

          <button className="btn" onClick={loadUnassigned} style={{ marginTop: "var(--space-3)" }}>
            Photos not on eBird
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
                      : `Ask Claude for ${checkedPhotoIdsIn(selectedCluster.matches.map((m) => m.photo.id)).length} selected`}
                  </button>
                )}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)" }}>
                  {selectedCluster.matches.map((m) => {
                    const identified = Boolean(m.fallback_common_name);
                    return (
                      <figure key={m.photo.id} className="card photo-card" style={{ margin: 0, overflow: "hidden" }}>
                        {m.photo.url_medium ? (
                          m.photo.flickr_url ? (
                            <a href={m.photo.flickr_url} target="_blank" rel="noreferrer">
                              <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                            </a>
                          ) : (
                            <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                          )
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
                                  {clusterSuggesting[m.photo.id] ? "Asking…" : "Ask Claude"}
                                </button>
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
            <h3>Matched photos</h3>
            {checkedPhotoIdsIn(selected.matches.map((m) => m.photo.id)).length > 0 && (
              <button
                className="btn btn-primary"
                style={{ marginBottom: "var(--space-3)" }}
                onClick={() => handleSuggestFallbackBatch(selected.id)}
                disabled={batchSuggesting}
              >
                {batchSuggesting
                  ? "Asking…"
                  : `Ask Claude for ${checkedPhotoIdsIn(selected.matches.map((m) => m.photo.id)).length} selected`}
              </button>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)" }}>
              {selected.matches.map((m, index) => {
                const suggestion = suggestions[m.photo.id];
                const fallback = fallbacks[m.photo.id];
                const resolved = m.observation || m.fallback_common_name;
                // Fallback methods (manual assignment, AI-suggestion
                // accept, fallback ID) all require a person to have
                // looked at this specific photo and agreed -- only a
                // rule-based match has never actually been reviewed by
                // anyone (see issue #32).
                const needsReview = Boolean(m.observation) && !m.reviewed_at;
                // Only worth pointing out right after it happened -- once
                // it's old news (from a previous session), the checkmark
                // is just noise; the plain name is enough.
                const justConfirmed =
                  Boolean(m.observation) &&
                  !needsReview &&
                  Boolean(m.reviewed_at) &&
                  (!sessionBoundary || (m.reviewed_at as string) > sessionBoundary);
                // A Label typed by hand (a Note), not an AI guess --
                // confidence only ever lands on exactly 1 when there was
                // no suggestion behind it to inherit a real value from.
                const isNote =
                  Boolean(m.fallback_common_name) &&
                  !m.fallback_scientific_name &&
                  m.confidence === 1;
                return (
                  <figure key={m.photo.id} className="card photo-card" style={{ margin: 0, overflow: "hidden", position: "relative" }}>
                    {/* Temporary reference numbers, for talking through
                        specific photos together -- not a permanent design
                        decision. */}
                    <span
                      style={{
                        position: "absolute",
                        top: "var(--space-1)",
                        left: "var(--space-1)",
                        background: "rgba(0, 0, 0, 0.65)",
                        color: "white",
                        fontSize: "var(--text-xs)",
                        fontWeight: 600,
                        padding: "1px 6px",
                        borderRadius: "var(--radius-sm)",
                        zIndex: 1,
                      }}
                    >
                      {index + 1}
                    </span>
                    {m.photo.url_medium ? (
                      m.photo.flickr_url ? (
                        <a href={m.photo.flickr_url} target="_blank" rel="noreferrer">
                          <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                        </a>
                      ) : (
                        <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                      )
                    ) : (
                      <div className="photo-placeholder" />
                    )}
                    <figcaption style={{ padding: "var(--space-2) var(--space-3) var(--space-3)" }}>
                      <div style={{ marginBottom: "var(--space-1)" }}>
                        {m.observation ? (
                          needsReview ? (
                            <>
                              <span className="badge badge-warning">Needs review</span>
                              <div style={{ marginTop: "var(--space-1)" }}>
                                {m.observation.common_name}
                                {m.observation.scientific_name && (
                                  <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", fontStyle: "italic" }}>
                                    {m.observation.scientific_name}
                                  </div>
                                )}
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
                              {m.observation.scientific_name && (
                                <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", fontStyle: "italic" }}>
                                  {m.observation.scientific_name}
                                </div>
                              )}
                            </div>
                          )
                        ) : m.fallback_common_name ? (
                          m.fallback_scientific_name ? (
                            <>
                              <span className="badge badge-warning">Off checklist</span>
                              <div style={{ marginTop: "var(--space-1)" }}>
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
                            </>
                          ) : isNote ? (
                            // A Note -- typed by hand, no AI guess behind
                            // it (confidence is only ever exactly 1 when
                            // there was no suggestion to inherit a real
                            // confidence value from). The Label speaks for
                            // itself; "Other" would just be noise here.
                            <div>{m.fallback_common_name}</div>
                          ) : (
                            // An AI guess that didn't resolve to a real
                            // eBird species (e.g. "Dragonfly") -- eBird
                            // checklists only track birds, so there's
                            // nothing sensible to "add to eBird" here. Just
                            // confirmed in BirdTrip's own data.
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
                                  checkedPhotoIdsIn(selected.matches.map((mm) => mm.photo.id)).length >= MAX_BATCH_PHOTOS
                                }
                                onChange={(e) =>
                                  setCheckedPhotos((prev) => ({ ...prev, [m.photo.id]: e.target.checked }))
                                }
                              />{" "}
                              Select for batch
                            </label>
                          </>
                        )}
                      </div>
                      {/* Method/confidence is diagnostic detail. Hidden once
                          plainly confirmed or a hand-typed Note (both
                          assumed correct, just noise) and for unmatched
                          (nothing to have confidence about yet --
                          rule_based_same_day/50% means nothing to a user).
                          Still shown for needs-review/off-checklist/other,
                          where it's the whole point. */}
                      {resolved && !(m.observation && !needsReview) && !isNote && (
                        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)" }}>
                          {m.method}
                          {m.method !== "rule_based" && ` · ${Math.round(m.confidence * 100)}%`}
                        </div>
                      )}
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
                          Camera recorded {m.timezone_mismatch.photo_utc_offset}, but this
                          location was on {m.timezone_mismatch.expected_utc_offset} at the time
                          — possible clock/timezone mismatch.
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
                    </figcaption>

                    {!resolved && !suggestion && (
                      <div style={{ padding: "0 var(--space-3) var(--space-2)" }}>
                        <select
                          value={manualPick[m.photo.id] ?? ""}
                          onChange={(e) =>
                            setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                          }
                          style={{ width: "100%", marginBottom: manualPick[m.photo.id] ? "var(--space-2)" : 0 }}
                        >
                          {/* Neutral hint until the user actually picks
                              something -- nothing below the dropdown until
                              then. "Other" pinned first in the real
                              options, since most unmatched photos here are
                              non-birds or off-checklist. */}
                          <option value="" disabled hidden>
                            It's actually…
                          </option>
                          <option value="other">Other</option>
                          {selected.observations.map((obs) => (
                            <option key={obs.id} value={obs.id}>
                              {obs.common_name}
                            </option>
                          ))}
                        </select>

                        {manualPick[m.photo.id] && (
                          <>
                            {/* Stays visible for a real species pick too,
                                not just Other -- general notes (e.g.
                                "juvenile", "distant/blurry shot") are
                                useful either way. Not yet wired to persist
                                anything when a real species is selected --
                                see conversation with Jen, 2026-08-04. */}
                            <input
                              type="text"
                              value={noteText[m.photo.id] ?? ""}
                              onChange={(e) =>
                                setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                              }
                              placeholder="Write a note"
                            />
                            {manualPick[m.photo.id] === "other" ? (
                              <div className="panel-actions" style={{ marginTop: "var(--space-2)" }}>
                                <button className="btn" onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                                  Ask Claude
                                </button>
                                <button
                                  className="btn btn-primary"
                                  disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                                  onClick={() => handleSaveNote(selected.id, m.photo.id)}
                                >
                                  {savingNote[m.photo.id] ? "Saving…" : "Save note"}
                                </button>
                              </div>
                            ) : (
                              <button
                                className="btn btn-primary btn-block"
                                style={{ marginTop: "var(--space-2)" }}
                                onClick={() => handleAssign(selected.id, m.photo.id)}
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
                            handleConfirmMatch(selected.id, m.photo.id, (m.observation as NonNullable<typeof m.observation>).id)
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
                              AI suggests: <strong>{suggestion.data.suggested_common_name}</strong>{" "}
                              ({Math.round(suggestion.data.confidence * 100)}%)
                            </div>
                            <div className="panel-reasoning">{suggestion.data.reasoning}</div>
                            <div className="panel-actions">
                              <button
                                className="btn btn-primary"
                                onClick={() =>
                                  handleAccept(
                                    selected.id,
                                    m.photo.id,
                                    suggestion.data.suggested_observation_id as number,
                                    suggestion.data.confidence
                                  )
                                }
                              >
                                Accept
                              </button>
                              <button className="btn btn-danger" onClick={() => handleReject(m.photo.id)}>
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
                                onChange={(e) =>
                                  setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                                }
                                style={{ maxWidth: "100%" }}
                              >
                                <option value="">It's actually…</option>
                                {selected.observations.map((obs) => (
                                  <option key={obs.id} value={obs.id}>
                                    {obs.common_name}
                                  </option>
                                ))}
                              </select>{" "}
                              <button
                                className="btn btn-primary"
                                disabled={!manualPick[m.photo.id]}
                                onClick={() => handleAssign(selected.id, m.photo.id)}
                              >
                                Assign
                              </button>
                            </div>

                            <div className="panel-actions">
                              <button className="btn" onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                                Ask Claude
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
                            onChange={(e) =>
                              setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                            }
                            style={{ maxWidth: "100%" }}
                          >
                            <option value="">It's actually…</option>
                            {selected.observations.map((obs) => (
                              <option key={obs.id} value={obs.id}>
                                {obs.common_name}
                              </option>
                            ))}
                          </select>{" "}
                          <button
                            className="btn btn-primary"
                            disabled={!manualPick[m.photo.id]}
                            onClick={() => handleAssign(selected.id, m.photo.id)}
                          >
                            Assign
                          </button>
                        </div>

                        <div style={{ marginTop: "var(--space-2)" }}>
                          <input
                            type="text"
                            value={noteText[m.photo.id] ?? ""}
                            onChange={(e) =>
                              setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                            }
                            placeholder="Or write a note"
                          />
                          <button
                            className="btn btn-primary"
                            disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                            onClick={() => handleSaveNote(selected.id, m.photo.id)}
                          >
                            {savingNote[m.photo.id] ? "Saving…" : "Save note"}
                          </button>
                        </div>

                        <div className="panel-actions">
                          <button className="btn" onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                            Ask Claude
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
                          onChange={(e) =>
                            setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                          }
                          placeholder="What is it? (matches the checklist if it's on there)"
                        />
                        <div className="panel-actions" style={{ marginTop: 0 }}>
                          <button
                            className="btn btn-primary"
                            disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                            onClick={() => handleSaveNote(selected.id, m.photo.id)}
                          >
                            {savingNote[m.photo.id] ? "Saving…" : "Save"}
                          </button>
                          <button className="btn" onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                            Ask Claude
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
                          // Claude's guess isn't checked against this
                          // outing's own species -- an unconstrained guess
                          // can land on something that's actually on the
                          // checklist. Check here so the messaging matches
                          // what accept-fallback will actually do with it.
                          const onChecklist =
                            fallback.data.species_code != null &&
                            selected.observations.some(
                              (obs) => obs.common_name.toLowerCase() === fallback.data.common_name?.toLowerCase()
                            );
                          return (
                            <>
                              <div>
                                {fallback.data.species_code ? (
                                  <>
                                    Broader guess: <strong>{fallback.data.common_name}</strong>{" "}
                                    ({Math.round(fallback.data.confidence * 100)}%)
                                  </>
                                ) : fallback.data.is_other ? (
                                  <>
                                    Not a bird — best guess: <strong>{fallback.data.common_name}</strong>
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
                          onChange={(e) =>
                            setFallbackText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                          }
                          placeholder="Accept the guess above, or write your own note"
                        />
                        <div className="panel-actions" style={{ marginTop: 0 }}>
                          <button
                            className="btn btn-primary"
                            disabled={!(fallbackText[m.photo.id] ?? "").trim()}
                            onClick={() => handleAcceptFallback(selected.id, m.photo.id, fallback.data)}
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
              })}
              {selected.matches.length === 0 && <p>No photos matched this outing yet.</p>}
            </div>

            <h3>Species seen</h3>
            <ul>
              {selected.observations.map((obs) => (
                <li key={obs.id}>
                  {obs.common_name}
                  {obs.count ? ` (${obs.count})` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      )}
      </div>
    </div>
  );
}
