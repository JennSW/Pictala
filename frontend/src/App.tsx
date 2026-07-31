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

// Per-photo state for the "Suggest species" flow (Strategy B). Keyed by
// photo id. Nothing here is persisted until the user clicks Accept --
// see DESIGN.md section 4.
// "rejected" -- the user rejected a positive suggestion (it named the
// wrong species). Shares its follow-up panel (manual dropdown, broader
// ID, a plain note) with the "no confident match" case, since both mean
// "this proposed answer isn't right."
type SuggestionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: SpeciesSuggestion }
  | { status: "accepting" }
  | { status: "rejected" };

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
    // confident match" (manual dropdown, broader ID, a plain note) plus
    // a Try Again option, since a wrong suggestion and no suggestion both
    // mean "this proposed answer isn't right."
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
    <div style={{ fontFamily: "sans-serif", maxWidth: 900, margin: "2rem auto" }}>
      <h1>BirdTrip</h1>
      <p style={{ color: "#555" }}>
        Your eBird outings, matched with your Flickr photos.
      </p>

      {error && (
        <p style={{ color: "crimson" }}>
          {error} — is the backend running at localhost:8000? (`uvicorn app.main:app --reload`)
        </p>
      )}

      <form onSubmit={handleSearch} role="search" style={{ marginBottom: "1.5rem" }}>
        <label htmlFor="species-search" style={{ display: "block", marginBottom: "0.25rem" }}>
          Search by species
        </label>
        <input
          id="species-search"
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="e.g. Bald Eagle"
          style={{ padding: "0.4rem", width: 220 }}
        />
        <button type="submit" disabled={!searchQuery.trim() || searching} style={{ marginLeft: "0.5rem", cursor: "pointer" }}>
          {searching ? "Searching…" : "Search"}
        </button>
        {searchResults !== null && (
          <button type="button" onClick={clearSearch} style={{ marginLeft: "0.5rem", cursor: "pointer" }}>
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
              {searchResults.map((r) => (
                <figure key={r.photo.id} style={{ margin: 0, width: 200 }}>
                  {r.photo.url_medium ? (
                    <img src={r.photo.url_medium} alt={r.photo.title ?? r.common_name} width={200} />
                  ) : (
                    <div style={{ width: 200, height: 140, background: "#eee" }} />
                  )}
                  <figcaption style={{ fontSize: "0.85rem" }}>
                    <strong>{r.common_name}</strong>
                    <br />
                    {r.location_name} · {r.date}
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
      <div style={{ display: "flex", gap: "2rem" }}>
        <div style={{ minWidth: 260 }}>
          <DatePicker
            availableDates={availableDates}
            selected={selectedDate}
            onSelect={setSelectedDate}
          />
          {selectedDate && (
            <button
              onClick={() => setSelectedDate(null)}
              style={{ marginBottom: "0.75rem", cursor: "pointer" }}
            >
              Clear date — show all outings
            </button>
          )}

          <ul style={{ listStyle: "none", padding: 0 }}>
            {visibleOutings.map((o) => (
              <li key={o.id} style={{ marginBottom: "0.75rem" }}>
                <button
                  onClick={() => openOuting(o.id)}
                  style={{ width: "100%", textAlign: "left", padding: "0.5rem", cursor: "pointer" }}
                >
                  <strong>{o.location_name}</strong>
                  <br />
                  {o.date} · {o.species_count} species · {o.photo_count} photos
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
            <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
              {selected.matches.map((m) => {
                const suggestion = suggestions[m.photo.id];
                const fallback = fallbacks[m.photo.id];
                const resolved = m.observation || m.fallback_common_name;
                return (
                  <figure key={m.photo.id} style={{ margin: 0, width: 180 }}>
                    {m.photo.url_medium ? (
                      <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                    ) : (
                      <div style={{ width: 180, height: 120, background: "#eee" }} />
                    )}
                    <figcaption style={{ fontSize: "0.8rem" }}>
                      {m.observation ? (
                        m.observation.common_name
                      ) : m.fallback_common_name ? (
                        m.fallback_scientific_name ? (
                          <>
                            {m.fallback_common_name}{" "}
                            <em style={{ color: "#a60" }}>(not on this checklist)</em>
                            {m.ebird_checklist_url && (
                              <>
                                {" — "}
                                <a href={m.ebird_checklist_url} target="_blank" rel="noreferrer">
                                  add to eBird
                                </a>
                              </>
                            )}
                          </>
                        ) : (
                          // Not a real eBird species (e.g. "Dragonfly") --
                          // eBird checklists only track birds, so there's
                          // nothing sensible to "add to eBird" here. Just
                          // confirmed in BirdTrip's own data.
                          <>
                            {m.fallback_common_name}{" "}
                            <em style={{ color: "#a60" }}>(Other — saved in BirdTrip only)</em>
                          </>
                        )
                      ) : (
                        "(unmatched species)"
                      )}
                      <br />
                      <em>{m.method}</em>
                      {m.method !== "rule_based" && ` (${Math.round(m.confidence * 100)}%)`}
                    </figcaption>

                    {!resolved && !suggestion && (
                      <button
                        onClick={() => handleSuggest(selected.id, m.photo.id)}
                        style={{ width: "100%", fontSize: "0.75rem", padding: "0.25rem", cursor: "pointer" }}
                      >
                        Suggest species ✨
                      </button>
                    )}

                    {suggestion?.status === "loading" && (
                      <p style={{ fontSize: "0.75rem", color: "#555" }}>Thinking…</p>
                    )}

                    {suggestion?.status === "accepting" && (
                      <p style={{ fontSize: "0.75rem", color: "#555" }}>Saving…</p>
                    )}

                    {suggestion?.status === "error" && (
                      <p style={{ fontSize: "0.75rem", color: "crimson" }}>{suggestion.message}</p>
                    )}

                    {suggestion?.status === "ready" && (
                      <div style={{ fontSize: "0.75rem", border: "1px solid #ddd", padding: "0.4rem", marginTop: "0.25rem" }}>
                        {suggestion.data.suggested_observation_id != null ? (
                          <>
                            <div>
                              AI suggests: <strong>{suggestion.data.suggested_common_name}</strong>{" "}
                              ({Math.round(suggestion.data.confidence * 100)}%)
                            </div>
                            <div style={{ color: "#666", margin: "0.25rem 0" }}>{suggestion.data.reasoning}</div>
                            <div style={{ display: "flex", gap: "0.25rem" }}>
                              <button
                                style={{ cursor: "pointer" }}
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
                              <button style={{ cursor: "pointer" }} onClick={() => handleReject(m.photo.id)}>
                                Reject
                              </button>
                            </div>
                          </>
                        ) : (
                          <>
                            <div>No confident match among this outing's species.</div>
                            <div style={{ color: "#666", margin: "0.25rem 0" }}>{suggestion.data.reasoning}</div>

                            <div style={{ marginTop: "0.4rem" }}>
                              <select
                                value={manualPick[m.photo.id] ?? ""}
                                onChange={(e) =>
                                  setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                                }
                                style={{ fontSize: "0.75rem", maxWidth: "100%" }}
                              >
                                <option value="">It's actually…</option>
                                {selected.observations.map((obs) => (
                                  <option key={obs.id} value={obs.id}>
                                    {obs.common_name}
                                  </option>
                                ))}
                              </select>{" "}
                              <button
                                disabled={!manualPick[m.photo.id]}
                                style={{ cursor: "pointer" }}
                                onClick={() => handleAssign(selected.id, m.photo.id)}
                              >
                                Assign
                              </button>
                            </div>

                            <div style={{ display: "flex", gap: "0.25rem", marginTop: "0.4rem" }}>
                              <button style={{ cursor: "pointer" }} onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                                Try broader ID
                              </button>
                              <button style={{ cursor: "pointer" }} onClick={() => handleDismissRejected(m.photo.id)}>
                                Dismiss
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    )}

                    {suggestion?.status === "rejected" && (
                      <div style={{ fontSize: "0.75rem", border: "1px solid #ddd", padding: "0.4rem", marginTop: "0.25rem" }}>
                        <div>Rejected — what should this be instead?</div>

                        <div style={{ marginTop: "0.4rem" }}>
                          <select
                            value={manualPick[m.photo.id] ?? ""}
                            onChange={(e) =>
                              setManualPick((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                            }
                            style={{ fontSize: "0.75rem", maxWidth: "100%" }}
                          >
                            <option value="">It's actually…</option>
                            {selected.observations.map((obs) => (
                              <option key={obs.id} value={obs.id}>
                                {obs.common_name}
                              </option>
                            ))}
                          </select>{" "}
                          <button
                            disabled={!manualPick[m.photo.id]}
                            style={{ cursor: "pointer" }}
                            onClick={() => handleAssign(selected.id, m.photo.id)}
                          >
                            Assign
                          </button>
                        </div>

                        <div style={{ marginTop: "0.4rem" }}>
                          <input
                            type="text"
                            value={noteText[m.photo.id] ?? ""}
                            onChange={(e) =>
                              setNoteText((prev) => ({ ...prev, [m.photo.id]: e.target.value }))
                            }
                            placeholder="Or write a note"
                            style={{
                              width: "100%",
                              fontSize: "0.75rem",
                              padding: "0.25rem",
                              boxSizing: "border-box",
                            }}
                          />
                          <button
                            disabled={!(noteText[m.photo.id] ?? "").trim() || savingNote[m.photo.id]}
                            style={{ cursor: "pointer", marginTop: "0.25rem" }}
                            onClick={() => handleSaveNote(selected.id, m.photo.id)}
                          >
                            {savingNote[m.photo.id] ? "Saving…" : "Save note"}
                          </button>
                        </div>

                        <div style={{ display: "flex", gap: "0.25rem", marginTop: "0.4rem" }}>
                          <button style={{ cursor: "pointer" }} onClick={() => handleSuggest(selected.id, m.photo.id)}>
                            Try Again
                          </button>
                          <button style={{ cursor: "pointer" }} onClick={() => handleSuggestFallback(selected.id, m.photo.id)}>
                            Try broader ID
                          </button>
                          <button style={{ cursor: "pointer" }} onClick={() => handleDismissRejected(m.photo.id)}>
                            Dismiss
                          </button>
                        </div>
                      </div>
                    )}

                    {fallback?.status === "loading" && (
                      <p style={{ fontSize: "0.75rem", color: "#555" }}>Thinking…</p>
                    )}

                    {fallback?.status === "accepting" && (
                      <p style={{ fontSize: "0.75rem", color: "#555" }}>Saving…</p>
                    )}

                    {fallback?.status === "error" && (
                      <p style={{ fontSize: "0.75rem", color: "crimson" }}>{fallback.message}</p>
                    )}

                    {fallback?.status === "ready" && (
                      <div style={{ fontSize: "0.75rem", border: "1px solid #ddd", padding: "0.4rem", marginTop: "0.25rem" }}>
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
                        <div style={{ color: "#666", margin: "0.25rem 0" }}>{fallback.data.reasoning}</div>
                        {fallback.data.species_code && (
                          <div style={{ color: "#a60", marginBottom: "0.25rem" }}>
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
                          style={{
                            width: "100%",
                            fontSize: "0.75rem",
                            padding: "0.25rem",
                            boxSizing: "border-box",
                            marginBottom: "0.25rem",
                          }}
                        />
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          <button
                            disabled={!(fallbackText[m.photo.id] ?? "").trim()}
                            style={{ cursor: "pointer" }}
                            onClick={() => handleAcceptFallback(selected.id, m.photo.id, fallback.data)}
                          >
                            Save
                          </button>
                          <button style={{ cursor: "pointer" }} onClick={() => handleDismissFallback(m.photo.id)}>
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
  );
}
