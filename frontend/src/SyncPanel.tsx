import { ChangeEvent, useRef, useState } from "react";
import {
  runSync,
  fetchSyncStatus,
  fetchOutings,
  syncEbirdCsv,
  runMatch,
  EbirdSyncResult,
  OutingSummary,
  SyncStatus,
} from "./api";

// Manual "Sync now" button (docs/USER_STORIES.md, "Story: Manual
// sync") -- capped server-side at 4/day. confirmLastSync gates the
// last available sync of the day behind an explicit "sync anyway"
// step, so a click doesn't silently burn the last one.
interface SyncPanelProps {
  syncStatus: SyncStatus | null;
  onSynced: (status: SyncStatus, outings: OutingSummary[]) => void;
  onError: (message: string) => void;
}

export default function SyncPanel({ syncStatus, onSynced, onError }: SyncPanelProps) {
  const [syncing, setSyncing] = useState(false);
  const [confirmLastSync, setConfirmLastSync] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<EbirdSyncResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function performSync() {
    setSyncing(true);
    setConfirmLastSync(false);
    try {
      await runSync();
      const [status, freshOutings] = await Promise.all([fetchSyncStatus(), fetchOutings()]);
      onSynced(status, freshOutings);
    } catch (e) {
      onError(String(e));
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

  // In-app eBird CSV upload (issue #49) -- previously only reachable via
  // the /docs Swagger page or curl, despite CSV ingestion being core v1
  // sync scope. Not gated by the Flickr sync's daily limit (see
  // api.ts's syncEbirdCsv). Runs the matcher right after so newly
  // imported checklists match against photos already synced, instead of
  // silently sitting unmatched until the next Flickr sync happens to
  // trigger one.
  async function handleFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // reset so picking the same file again still fires onChange
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const result = await syncEbirdCsv(file);
      await runMatch();
      const [status, freshOutings] = await Promise.all([fetchSyncStatus(), fetchOutings()]);
      onSynced(status, freshOutings);
      setUploadResult(result);
    } catch (err) {
      onError(String(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: "var(--space-4)", padding: "var(--space-3)" }}>
      {syncStatus && (
        <div style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)", marginBottom: "var(--space-2)" }}>
          {syncStatus.remaining > 0
            ? `${syncStatus.remaining} of ${syncStatus.limit} syncs left today`
            : "No syncs left today — resets at midnight"}
          {syncStatus.last_synced_at && (
            <>
              <br />
              Last synced{" "}
              {new Date(syncStatus.last_synced_at).toLocaleString([], {
                dateStyle: "medium",
                timeStyle: "short",
              })}
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
      {/* eBird has no personal-data API/OAuth (see app/services/
          ebird_import.py's docstring) -- CSV download is the only way to
          get a checklist out, so "sync" for eBird just means opening this
          page and uploading what it gives you, not something this app can
          do on your behalf (issue #49). */}
      <div style={{ marginTop: "var(--space-3)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--border)" }}>
        <a
          href="https://ebird.org/downloadMyData"
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: "var(--text-sm)" }}
        >
          Get eBird checklist CSV ↗
        </a>
        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-faint)", marginTop: 2, marginBottom: "var(--space-2)" }}>
          eBird emails this to you rather than downloading it instantly —
          submit the request there, then come back once it's arrived. (A
          single checklist's own "Download" button, on that checklist's
          page on eBird, is immediate instead, if that's all you need.)
        </div>
        <input
          type="file"
          accept=".csv"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileSelected}
        />
        <button className="btn" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? "Importing…" : "Upload eBird CSV"}
        </button>
        {uploadResult && (
          <div style={{ fontSize: "var(--text-xs)", color: "var(--success)", marginTop: "var(--space-2)" }}>
            Imported {uploadResult.checklists_created} checklist{uploadResult.checklists_created === 1 ? "" : "s"},{" "}
            {uploadResult.observations_created} observation{uploadResult.observations_created === 1 ? "" : "s"}
            {uploadResult.rows_skipped > 0 &&
              ` (${uploadResult.rows_skipped} row${uploadResult.rows_skipped === 1 ? "" : "s"} skipped — unrecognized format?)`}
            .
          </div>
        )}
      </div>
    </div>
  );
}
