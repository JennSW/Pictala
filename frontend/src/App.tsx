import { FormEvent, useEffect, useState } from "react";
import {
  fetchOutings,
  fetchOuting,
  suggestSpecies,
  acceptSuggestion,
  assignSpecies,
  suggestFallback,
  acceptFallback,
  searchBySpecies,
  OutingSummary,
  OutingDetail,
  SpeciesSuggestion,
  FallbackSuggestion,
  SearchResult,
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
  }, []);

  const availableDates = new Set(outings.map((o) => o.date));
  const visibleOutings = selectedDate ? outings.filter((o) => o.date === selectedDate) : outings;

  async function openOuting(id: number) {
    try {
      setSelected(await fetchOuting(id));
      setSuggestions({});
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

  // Single text box standing in for the dropdown (issue: "the dropdown
  // options are bulky" -- a 35+ species list is unwieldy to scroll).
  // Matches what's typed against the outing's own species case-
  // insensitively so it still lands as a proper linked assignment when
  // it's actually one of the reported species; anything that doesn't
  // match (a note, an off-checklist species, a typo) falls back to a
  // plain note, same as before.
  async function handleSaveOrMatch(checklistId: number, photoId: number) {
    const text = (noteText[photoId] ?? "").trim();
    if (!text) return;
    const match = selected?.observations.find(
      (obs) => obs.common_name.toLowerCase() === text.toLowerCase()
    );
    setSuggestions((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      if (match) {
        await assignSpecies(checklistId, photoId, match.id);
      } else {
        await acceptFallback(checklistId, photoId, text);
      }
      setSelected(await fetchOuting(checklistId));
      handleDismissRejected(photoId);
    } catch (e) {
      setSuggestions((prev) => ({ ...prev, [photoId]: { status: "error", message: String(e) } }));
    }
  }

  // Plain freeform note, no AI guess involved -- reuses the fallback
  // accept endpoint (an arbitrary common_name with no species metadata
  // is exactly what an "Other" entry already is), just reached directly
  // instead of via a suggestion first.
  async function handleSaveNote(checklistId: number, photoId: number) {
    const text = (noteText[photoId] ?? "").trim();
    if (!text) return;
    setSavingNote((prev) => ({ ...prev, [photoId]: true }));
    try {
      await acceptFallback(checklistId, photoId, text);
      setSelected(await fetchOuting(checklistId));
      handleDismissRejected(photoId);
    } catch (e) {
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

  async function handleAcceptFallback(checklistId: number, photoId: number, suggestion: FallbackSuggestion) {
    const text = (fallbackText[photoId] ?? "").trim();
    if (!text) return;
    setFallbacks((prev) => ({ ...prev, [photoId]: { status: "accepting" } }));
    try {
      await acceptFallback(checklistId, photoId, text, suggestion);
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
              <li>No outings on this date.</li>
            )}
          </ul>
        </div>

        {selected && (
          <div style={{ flex: 1 }}>
            <h2>
              {selected.location_name} — {selected.date}
            </h2>
            <h3>Species seen</h3>
            <ul>
              {selected.observations.map((obs) => (
                <li key={obs.id}>
                  {obs.common_name}
                  {obs.count ? ` (${obs.count})` : ""}
                </li>
              ))}
            </ul>

            <h3>Matched photos</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)" }}>
              {selected.matches.map((m) => {
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
                return (
                  <figure key={m.photo.id} className="card photo-card" style={{ margin: 0, overflow: "hidden" }}>
                    {m.photo.url_medium ? (
                      <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                    ) : (
                      <div className="photo-placeholder" />
                    )}
                    <figcaption style={{ padding: "var(--space-2) var(--space-3) var(--space-3)" }}>
                      <div style={{ marginBottom: "var(--space-1)" }}>
                        {m.observation ? (
                          needsReview ? (
                            <>
                              <span className="badge badge-warning">Needs review</span>
                              <div style={{ marginTop: "var(--space-1)" }}>{m.observation.common_name}</div>
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
                          ) : (
                            // Not a real eBird species (e.g. "Dragonfly") --
                            // eBird checklists only track birds, so there's
                            // nothing sensible to "add to eBird" here. Just
                            // confirmed in BirdTrip's own data.
                            <>
                              <span className="badge badge-neutral">Other</span>
                              <div style={{ marginTop: "var(--space-1)" }}>{m.fallback_common_name}</div>
                            </>
                          )
                        ) : (
                          <span className="badge badge-neutral">Unmatched</span>
                        )}
                      </div>
                      {/* Method/confidence is diagnostic detail. Hidden once
                          plainly confirmed (assumed correct, just noise) and
                          for unmatched (nothing to have confidence about
                          yet -- rule_based_same_day/50% means nothing to a
                          user). Still shown for needs-review/off-checklist/
                          other, where it's the whole point. */}
                      {resolved && !(m.observation && !needsReview) && (
                        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)" }}>
                          {m.method}
                          {m.method !== "rule_based" && ` · ${Math.round(m.confidence * 100)}%`}
                        </div>
                      )}
                    </figcaption>

                    {!resolved && !suggestion && (
                      <div style={{ padding: "0 var(--space-3) var(--space-2)" }}>
                        <select
                          value={manualPick[m.photo.id] ?? "other"}
                          onChange={(e) =>
                            setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                          }
                          style={{ width: "100%", marginBottom: "var(--space-2)" }}
                        >
                          {/* "Other" pinned first -- most unmatched photos
                              here are non-birds or off-checklist, so
                              defaulting to the no-AI-cost path beats
                              defaulting to a real species nobody picked. */}
                          <option value="other">Other</option>
                          {selected.observations.map((obs) => (
                            <option key={obs.id} value={obs.id}>
                              {obs.common_name}
                            </option>
                          ))}
                        </select>

                        {(manualPick[m.photo.id] ?? "other") === "other" ? (
                          <>
                            <input
                              type="text"
                              value={noteText[m.photo.id] ?? ""}
                              onChange={(e) =>
                                setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                              }
                              placeholder="Write a note (optional)"
                            />
                            <div className="panel-actions" style={{ marginTop: "var(--space-2)" }}>
                              <button
                                className="btn btn-primary"
                                disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                                onClick={() => handleSaveNote(selected.id, m.photo.id)}
                              >
                                {savingNote[m.photo.id] ? "Saving…" : "Save note"}
                              </button>
                              <button className="btn" onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                                Ask Claude
                              </button>
                            </div>
                          </>
                        ) : (
                          <button
                            className="btn btn-primary btn-block"
                            onClick={() => handleAssign(selected.id, m.photo.id)}
                          >
                            Assign
                          </button>
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
                            disabled={!(noteText[m.photo.id] ?? "").trim()}
                            onClick={() => handleSaveOrMatch(selected.id, m.photo.id)}
                          >
                            Save
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
                            Not on this checklist — saving labels the photo only, and won't be
                            written back to eBird.
                          </div>
                        )}
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
          </div>
        )}
      </div>
      )}
      </div>
    </div>
  );
}
