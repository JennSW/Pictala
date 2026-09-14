// Thin fetch wrapper around the FastAPI backend. Kept dependency-free
// (no axios/react-query) since the scaffold's job is to demonstrate the
// data flow clearly, not to showcase a data-fetching library.
const API_BASE = "http://localhost:8000";

export interface OutingSummary {
  id: number;
  location_name: string;
  date: string;
  species_count: number;
  photo_count: number;
  reviewed_at: string | null;
}

// Grouping data for the outing review UI (issue #43) -- see
// app/services/outing_review.py for the bucket definitions. Exposed
// unconditionally; which buckets a given UI shows, and how they're
// labeled, is a presentation decision, not decided here.
export interface PhotoGroups {
  ebird_and_flickr: number[];
  flickr_best_guess: number[];
  needs_claude: number[];
  ebird_no_photo: number[];
}

export interface Observation {
  id: number;
  common_name: string;
  scientific_name: string | null;
  count: string | null;
}

export interface Photo {
  id: number;
  flickr_id: string;
  title: string | null;
  date_taken: string;
  url_medium: string | null;
  latitude: number | null;
  longitude: number | null;
  // Computed by photo_out() on every photo the backend serializes, not
  // just search results -- see issue #44.
  flickr_url: string | null;
}

export interface TimezoneMismatch {
  photo_utc_offset: string;
  expected_utc_offset: string;
  hours_diff: number;
}

export interface PossibleDuplicate {
  other_photo_ids: number[];
  other_flickr_urls: (string | null)[];
}

export interface MatchEntry {
  checklist_id: number | null;
  photo: Photo;
  observation: Observation | null;
  method: string;
  confidence: number;
  fallback_common_name: string | null;
  fallback_scientific_name: string | null;
  ebird_checklist_url: string | null;
  reviewed_at: string | null;
  timezone_mismatch: TimezoneMismatch | null;
  possible_duplicate: PossibleDuplicate | null;
}

export interface SearchResult {
  checklist_id: number;
  location_name: string;
  date: string;
  common_name: string;
  photo: Photo;
}

export interface OutingDetail {
  id: number;
  location_name: string;
  date: string;
  latitude: number | null;
  longitude: number | null;
  observations: Observation[];
  matches: MatchEntry[];
  reviewed_at: string | null;
  photo_groups: PhotoGroups;
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // response wasn't JSON -- fall through to the generic message
  }
  return `Request failed: ${res.status}`;
}

// Shared by every function below -- every endpoint had its own copy of
// "fetch, check res.ok, parse JSON", which meant 20 near-identical
// blocks and an inconsistency where only some of them surfaced the
// backend's actual error detail instead of just a bare status code.
// `path` is relative (e.g. "/outings"), not a full URL.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchOutings(): Promise<OutingSummary[]> {
  return request("/outings");
}

export function markOutingReviewed(outingId: number): Promise<{ reviewed_at: string }> {
  return request(`/outings/${outingId}/mark-reviewed`, { method: "POST" });
}

export function unmarkOutingReviewed(outingId: number): Promise<{ reviewed_at: null }> {
  return request(`/outings/${outingId}/unmark-reviewed`, { method: "POST" });
}

export function fetchOuting(id: number): Promise<OutingDetail> {
  return request(`/outings/${id}`);
}

// Search by species (see docs/USER_STORIES.md, "Story: Search by
// species"). Only confirmed matches are searchable -- see search.py.
export function searchBySpecies(query: string): Promise<SearchResult[]> {
  return request(`/search?species=${encodeURIComponent(query)}`);
}

export interface SpeciesSuggestion {
  photo_id: number;
  checklist_id: number;
  candidate_common_names: string[];
  suggested_observation_id: number | null;
  suggested_common_name: string | null;
  confidence: number;
  reasoning: string;
}

// Strategy B (see DESIGN.md section 4): ask the model for a suggestion.
// Nothing is saved on the backend yet -- this is just the guess.
export function suggestSpecies(checklistId: number, photoId: number): Promise<SpeciesSuggestion> {
  return request(`/match/${checklistId}/suggest/${photoId}`, { method: "POST" });
}

// The user looked at a SpeciesSuggestion and chose to keep it.
// suggestedCommonName is passed through unchanged for AI accuracy
// logging (issue raised 2026-09-03) -- accept always keeps Claude's own
// suggested species, so this always logs as an "accepted" outcome.
export function acceptSuggestion(
  checklistId: number,
  photoId: number,
  observationId: number,
  confidence: number,
  suggestedCommonName?: string | null
): Promise<MatchEntry> {
  return postJson(`/match/${checklistId}/accept/${photoId}`, {
    observation_id: observationId,
    confidence,
    suggested_common_name: suggestedCommonName ?? null,
  });
}

// The user looked at a SpeciesSuggestion and said no. Writes nothing to
// the match itself (nothing to undo), but logs the rejection for AI
// accuracy tracking.
export function rejectSuggestion(
  checklistId: number,
  photoId: number,
  suggestedCommonName: string | null,
  confidence: number
): Promise<void> {
  return postJson(`/match/${checklistId}/reject/${photoId}`, {
    suggested_common_name: suggestedCommonName,
    confidence,
  });
}

// Manual override -- the user picks one of the outing's own reported
// species themselves, no AI suggestion behind it. For correcting a
// false-negative "no confident match" result.
export function assignSpecies(
  checklistId: number,
  photoId: number,
  observationId: number
): Promise<MatchEntry> {
  return postJson(`/match/${checklistId}/assign/${photoId}`, { observation_id: observationId });
}

// Undo a batch confirm (issue #69) -- clears reviewed_at so the match
// goes back to "Needs review" without touching which species it's
// assigned to.
export function unconfirmMatch(checklistId: number, photoId: number): Promise<{ reviewed_at: null }> {
  return request(`/match/${checklistId}/unconfirm/${photoId}`, { method: "POST" });
}

export interface FallbackSuggestion {
  photo_id: number;
  checklist_id: number | null;
  is_bird: boolean;
  common_name: string | null;
  scientific_name: string | null;
  species_code: string | null;
  confidence: number;
  reasoning: string;
  ebird_checklist_url: string | null;
  is_other: boolean;
}

// Broader, unconstrained guess for a photo that doesn't match any of the
// outing's reported species (see docs/USER_STORIES.md, "Species ID
// fallback for eBird gaps"). Nothing saved yet.
export function suggestFallback(checklistId: number, photoId: number): Promise<FallbackSuggestion> {
  return request(`/match/${checklistId}/suggest-fallback/${photoId}`, { method: "POST" });
}

// Batch version (issue #5) -- one Claude call for every checked photo
// instead of one round trip each. Same "nothing persisted yet" contract;
// caller still accepts each result individually.
export function suggestFallbackBatch(
  checklistId: number,
  photoIds: number[]
): Promise<FallbackSuggestion[]> {
  return postJson(`/match/${checklistId}/suggest-fallback-batch`, { photo_ids: photoIds });
}

// Submit a name for this photo -- typed by hand, or accepted from an
// unconstrained AI guess. The backend resolves it (checklist's own
// species -> eBird's full taxonomy -> plain note) rather than trusting
// a scientific_name/species_code from here, so this only ever sends the
// text itself plus an optional confidence carried over from an AI guess
// being accepted as-is (a human typing a name has no confidence to
// report, so it's omitted and defaults to certain on the backend).
// aiSuggestedCommonName is set only when this save follows an AI
// fallback guess (single or batched) -- passed through unchanged so the
// backend can log whether the final answer matches it (accepted) or was
// edited (corrected) for AI accuracy tracking. Omitted for a from-scratch
// typed note, which isn't an AI accuracy data point.
export function acceptFallback(
  checklistId: number,
  photoId: number,
  commonName: string,
  confidence?: number,
  aiSuggestedCommonName?: string | null
): Promise<MatchEntry> {
  return postJson(`/match/${checklistId}/accept-fallback/${photoId}`, {
    common_name: commonName,
    ...(confidence !== undefined ? { confidence } : {}),
    ...(aiSuggestedCommonName ? { ai_suggested_common_name: aiSuggestedCommonName } : {}),
  });
}

export interface SyncStatus {
  used: number;
  limit: number;
  remaining: number;
  last_synced_at: string | null;
}

export function fetchSyncStatus(): Promise<SyncStatus> {
  return request("/sync/status");
}

export function runSync(): Promise<{ remaining: number }> {
  return request("/sync/run", { method: "POST" });
}

export interface EbirdSyncResult {
  checklists_created: number;
  observations_created: number;
  rows_skipped: number;
}

// File upload -- not JSON, so this bypasses request()/postJson() and sets
// its own multipart body (the browser sets the correct Content-Type,
// including the boundary, when given a FormData with no explicit header).
// Not gated by the Flickr sync's daily limit -- see app/routers/sync.py,
// only /sync/run writes a SyncLog.
export async function syncEbirdCsv(file: File): Promise<EbirdSyncResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/sync/ebird`, { method: "POST", body: formData });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

// Re-run matching after an eBird import so newly-added checklists match
// against photos already synced, without waiting for the next Flickr
// sync (which is the only other thing that currently triggers this).
export function runMatch(): Promise<{
  checklist_photo_matches: number;
  species_level_matches: number;
  same_day_fallback_matches: number;
}> {
  return request("/sync/match", { method: "POST" });
}

export function adjustTimezone(checklistId: number, photoId: number): Promise<void> {
  return request(`/match/${checklistId}/adjust-timezone/${photoId}`, { method: "POST" });
}

// Checklist-less photo clusters (issue #35) -- photos with no eBird
// checklist at all, either permanently (never a countable sighting) or
// not yet (checklist not uploaded). See app/services/photo_clusters.py.
export interface ClusterSummary {
  id: string;
  date: string;
  photo_count: number;
}

export interface ClusterDetail {
  id: string;
  date: string;
  matches: MatchEntry[];
}

export function fetchUnassignedClusters(): Promise<ClusterSummary[]> {
  return request("/unassigned");
}

export function fetchUnassignedCluster(clusterId: string): Promise<ClusterDetail> {
  return request(`/unassigned/${clusterId}`);
}

export function suggestUnassignedFallback(
  clusterId: string,
  photoId: number
): Promise<FallbackSuggestion> {
  return request(`/unassigned/${clusterId}/suggest/${photoId}`, { method: "POST" });
}

// Batch version (issue #5) -- see suggestFallbackBatch's comment.
export function suggestUnassignedFallbackBatch(
  clusterId: string,
  photoIds: number[]
): Promise<FallbackSuggestion[]> {
  return postJson(`/unassigned/${clusterId}/suggest-batch`, { photo_ids: photoIds });
}

// aiSuggestedCommonName mirrors acceptFallback's -- set only when this
// save follows the unconstrained guess, so the backend can log
// accepted/corrected for AI accuracy tracking; omitted for a
// from-scratch typed note.
export function identifyUnassignedPhoto(
  clusterId: string,
  photoId: number,
  commonName: string,
  confidence?: number,
  aiSuggestedCommonName?: string | null
): Promise<MatchEntry> {
  return postJson(`/unassigned/${clusterId}/identify/${photoId}`, {
    common_name: commonName,
    ...(confidence !== undefined ? { confidence } : {}),
    ...(aiSuggestedCommonName ? { ai_suggested_common_name: aiSuggestedCommonName } : {}),
  });
}

export function moveToCluster(
  fromClusterId: string,
  photoId: number,
  toClusterId: string
): Promise<void> {
  return postJson(`/unassigned/${fromClusterId}/move/${photoId}`, { to_cluster_id: toClusterId });
}
