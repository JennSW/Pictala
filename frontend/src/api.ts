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
}

export interface MatchEntry {
  photo: Photo;
  observation: Observation | null;
  method: string;
  confidence: number;
  fallback_common_name: string | null;
  fallback_scientific_name: string | null;
  ebird_checklist_url: string | null;
  reviewed_at: string | null;
}

export interface PhotoWithLink extends Photo {
  flickr_url: string | null;
}

export interface SearchResult {
  checklist_id: number;
  location_name: string;
  date: string;
  common_name: string;
  photo: PhotoWithLink;
}

export interface OutingDetail {
  id: number;
  location_name: string;
  date: string;
  latitude: number | null;
  longitude: number | null;
  observations: Observation[];
  matches: MatchEntry[];
}

export async function fetchOutings(): Promise<OutingSummary[]> {
  const res = await fetch(`${API_BASE}/outings`);
  if (!res.ok) throw new Error(`Failed to load outings: ${res.status}`);
  return res.json();
}

export async function fetchOuting(id: number): Promise<OutingDetail> {
  const res = await fetch(`${API_BASE}/outings/${id}`);
  if (!res.ok) throw new Error(`Failed to load outing ${id}: ${res.status}`);
  return res.json();
}

// Search by species (see docs/USER_STORIES.md, "Story: Search by
// species"). Only confirmed matches are searchable -- see search.py.
export async function searchBySpecies(query: string): Promise<SearchResult[]> {
  const res = await fetch(`${API_BASE}/search?species=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(`Search failed: ${res.status}`);
  return res.json();
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

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // response wasn't JSON -- fall through to the generic message
  }
  return `Request failed: ${res.status}`;
}

// Strategy B (see DESIGN.md section 4): ask the model for a suggestion.
// Nothing is saved on the backend yet -- this is just the guess.
export async function suggestSpecies(
  checklistId: number,
  photoId: number
): Promise<SpeciesSuggestion> {
  const res = await fetch(`${API_BASE}/match/${checklistId}/suggest/${photoId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

// The user looked at a SpeciesSuggestion and chose to keep it.
export async function acceptSuggestion(
  checklistId: number,
  photoId: number,
  observationId: number,
  confidence: number
): Promise<MatchEntry> {
  const res = await fetch(`${API_BASE}/match/${checklistId}/accept/${photoId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ observation_id: observationId, confidence }),
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

// Manual override -- the user picks one of the outing's own reported
// species themselves, no AI suggestion behind it. For correcting a
// false-negative "no confident match" result.
export async function assignSpecies(
  checklistId: number,
  photoId: number,
  observationId: number
): Promise<MatchEntry> {
  const res = await fetch(`${API_BASE}/match/${checklistId}/assign/${photoId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ observation_id: observationId }),
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

export interface FallbackSuggestion {
  photo_id: number;
  checklist_id: number;
  is_bird: boolean;
  common_name: string | null;
  scientific_name: string | null;
  species_code: string | null;
  confidence: number;
  reasoning: string;
  ebird_checklist_url: string;
  is_other: boolean;
}

// Broader, unconstrained guess for a photo that doesn't match any of the
// outing's reported species (see docs/USER_STORIES.md, "Species ID
// fallback for eBird gaps"). Nothing saved yet.
export async function suggestFallback(
  checklistId: number,
  photoId: number
): Promise<FallbackSuggestion> {
  const res = await fetch(`${API_BASE}/match/${checklistId}/suggest-fallback/${photoId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

// Submit a name for this photo -- typed by hand, or accepted from an
// unconstrained AI guess. The backend resolves it (checklist's own
// species -> eBird's full taxonomy -> plain note) rather than trusting
// a scientific_name/species_code from here, so this only ever sends the
// text itself plus an optional confidence carried over from an AI guess
// being accepted as-is (a human typing a name has no confidence to
// report, so it's omitted and defaults to certain on the backend).
export async function acceptFallback(
  checklistId: number,
  photoId: number,
  commonName: string,
  confidence?: number
): Promise<MatchEntry> {
  const res = await fetch(`${API_BASE}/match/${checklistId}/accept-fallback/${photoId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      common_name: commonName,
      ...(confidence !== undefined ? { confidence } : {}),
    }),
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

export interface SyncStatus {
  used: number;
  limit: number;
  remaining: number;
  last_synced_at: string | null;
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const res = await fetch(`${API_BASE}/sync/status`);
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

export async function runSync(): Promise<{ remaining: number }> {
  const res = await fetch(`${API_BASE}/sync/run`, { method: "POST" });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}
