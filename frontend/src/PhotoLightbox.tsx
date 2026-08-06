import { useEffect } from "react";
import { Photo } from "./api";

// Larger inline view of a single photo (issue #44) -- deliberately a
// modal, not a new-tab navigation to Flickr, so looking at a photo
// closer never leaves the page (no navigation means no state loss, see
// #45). No prev/next between photos: this is read-only (no action to
// take here), and navigating away from the specific card you clicked
// just to look at another one made it harder to find your way back to
// what you actually wanted to act on -- one photo in, one photo out.
//
// Flickr's medium URL (no size suffix) can be upgraded to "large"
// (1024px, no extra API call) just by inserting "_b" before the file
// extension -- a documented quirk of Flickr's URL scheme, verified live
// against a real photo before relying on it. True original resolution
// needs a separate API call with a different secret Flickr doesn't hand
// out via the extras used here, so 1024px is the practical ceiling
// without more plumbing.
function largeFlickrUrl(urlMedium: string | null): string | null {
  if (!urlMedium) return null;
  return urlMedium.replace(/(\.[a-zA-Z]+)$/, "_b$1");
}

// Read-only context shown alongside the image -- current status and
// species/label, if any. Deliberately no actions here (confirm, assign,
// ask Claude, etc.) -- this is a bigger look at the photo plus "what do
// we already know," not a second place to do the review workflow.
export interface LightboxEntry {
  photo: Photo;
  statusLabel: string;
  speciesLabel: string | null;
  scientificName: string | null;
}

interface PhotoLightboxProps {
  entry: LightboxEntry;
  onClose: () => void;
}

export default function PhotoLightbox({ entry, onClose }: PhotoLightboxProps) {
  const photo = entry.photo;

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={photo.title ?? "Photo"}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.85)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <button
        aria-label="Close"
        onClick={onClose}
        className="btn"
        style={{
          position: "absolute",
          top: "var(--space-4)",
          right: "var(--space-4)",
          fontSize: "var(--text-lg)",
          lineHeight: 1,
          padding: "var(--space-2) var(--space-3)",
        }}
      >
        ✕
      </button>

      <div
        onClick={(e) => e.stopPropagation()}
        style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "var(--space-3)", maxWidth: "90vw", maxHeight: "90vh" }}
      >
        {largeFlickrUrl(photo.url_medium) ? (
          <img
            src={largeFlickrUrl(photo.url_medium) ?? undefined}
            alt={photo.title ?? ""}
            style={{ maxWidth: "90vw", maxHeight: "80vh", objectFit: "contain", borderRadius: "var(--radius-md)" }}
          />
        ) : (
          <div style={{ color: "white" }}>No image available</div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", color: "white" }}>
          <span className="badge badge-neutral">{entry.statusLabel}</span>
          {entry.speciesLabel && (
            <span>
              {entry.speciesLabel}
              {entry.scientificName && (
                <span style={{ fontStyle: "italic", color: "var(--text-faint)" }}> — {entry.scientificName}</span>
              )}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)", color: "white" }}>
          {photo.title && <span>{photo.title}</span>}
          {photo.flickr_url && (
            <a href={photo.flickr_url} target="_blank" rel="noreferrer" style={{ color: "white", textDecoration: "underline" }}>
              View on Flickr ↗
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
