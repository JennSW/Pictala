import { useState } from "react";
import { runSync, fetchSyncStatus, fetchOutings, OutingSummary, SyncStatus } from "./api";

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
    </div>
  );
}
