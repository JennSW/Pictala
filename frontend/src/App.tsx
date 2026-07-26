import { useEffect, useState } from "react";
import {
  fetchOutings,
  fetchOuting,
  suggestSpecies,
  acceptSuggestion,
  OutingSummary,
  OutingDetail,
  SpeciesSuggestion,
} from "./api";

// Per-photo state for the "Suggest species" flow (Strategy B). Keyed by
// photo id. Nothing here is persisted until the user clicks Accept --
// see DESIGN.md section 4.
type SuggestionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: SpeciesSuggestion }
  | { status: "accepting" };

export default function App() {
  const [outings, setOutings] = useState<OutingSummary[]>([]);
  const [selected, setSelected] = useState<OutingDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Record<number, SuggestionState>>({});

  useEffect(() => {
    fetchOutings().then(setOutings).catch((e) => setError(String(e)));
  }, []);

  async function openOuting(id: number) {
    try {
      setSelected(await fetchOuting(id));
      setSuggestions({});
    } catch (e) {
      setError(String(e));
    }
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
    // Nothing was ever saved -- rejecting just clears the on-screen guess.
    setSuggestions((prev) => {
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

      <div style={{ display: "flex", gap: "2rem" }}>
        <ul style={{ listStyle: "none", padding: 0, minWidth: 260 }}>
          {outings.map((o) => (
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
        </ul>

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
                return (
                  <figure key={m.photo.id} style={{ margin: 0, width: 180 }}>
                    {m.photo.url_medium ? (
                      <img src={m.photo.url_medium} alt={m.photo.title ?? ""} width={180} />
                    ) : (
                      <div style={{ width: 180, height: 120, background: "#eee" }} />
                    )}
                    <figcaption style={{ fontSize: "0.8rem" }}>
                      {m.observation ? m.observation.common_name : "(unmatched species)"}
                      <br />
                      <em>{m.method}</em>
                      {m.method !== "rule_based" && ` (${Math.round(m.confidence * 100)}%)`}
                    </figcaption>

                    {!m.observation && !suggestion && (
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
                            <button style={{ cursor: "pointer" }} onClick={() => handleReject(m.photo.id)}>
                              Dismiss
                            </button>
                          </>
                        )}
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
    </div>
  );
}
