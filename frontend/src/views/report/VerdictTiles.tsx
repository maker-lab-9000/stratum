import { Badge, ConfBar, DegradedBanner, Tile } from "../../components";
import type { Report } from "../../api/client";
import type { CacheVerdict } from "./types";
import { flagsFor, isDegraded } from "./types";

// The four verdict tiles, in the user→origin axis used everywhere:
// Cached? → CDN cache → Served from → Hosting/CDN (§8.1.3).
const CONF_PERCENT: Record<string, number> = { high: 92, medium: 66, low: 33 };

const CDN_ROLES = new Set(["edge", "shield"]);

interface VerdictTilesProps {
  report: Report;
  onRerun?: () => void;
}

export function VerdictTiles({ report, onRerun }: VerdictTilesProps) {
  if (isDegraded(report.verdict_json)) {
    return (
      <>
        <div className="verdict">
          {["Cached", "CDN cache", "Served from", "Hosting / CDN"].map((k) => (
            <Tile key={k} label={k} value="—" status="unknown" foot="verdict unavailable" />
          ))}
        </div>
        <DegradedBanner onRerun={onRerun} />
      </>
    );
  }

  const verdict = report.verdict_json as unknown as CacheVerdict | null;
  if (!verdict) return null;

  const providerFlagged = flagsFor(verdict, "cache_verdict.provider").length > 0;
  const servingFlagged = flagsFor(verdict, "cache_verdict.serving_layer").length > 0;

  // CDN cache tile: does any CDN-tier layer HIT?
  const cdnLayers = verdict.layers.filter((l) => CDN_ROLES.has(l.role));
  const cdnLayerIndexes = verdict.layers
    .map((l, i) => (CDN_ROLES.has(l.role) ? i : -1))
    .filter((i) => i >= 0);
  const cdnUnverified = cdnLayerIndexes.some(
    (i) => flagsFor(verdict, `cache_verdict.layers[${i}].state`).length > 0,
  );
  let cdn: { value: string; status: "hit" | "warn" | "unknown"; foot: string };
  if (cdnLayers.some((l) => l.state === "HIT")) {
    cdn = { value: "Hit", status: "hit", foot: "served at the CDN edge" };
  } else if (cdnLayers.some((l) => l.state === "UNKNOWN") || cdnLayers.length === 0) {
    cdn = { value: "Unknown", status: "unknown", foot: "evidence ambiguous" };
  } else {
    cdn = { value: "Bypassed", status: "warn", foot: `${cdnLayers.length} CDN tier(s) MISS every request` };
  }

  const cachedStatus = verdict.cached ? "hit" : "accent";
  const providerUnknown = verdict.provider === "UNKNOWN";
  const confPct = CONF_PERCENT[verdict.confidence] ?? 33;

  return (
    <div className="verdict">
      <Tile
        label="Cached"
        value={verdict.cached ? "Yes" : "No"}
        status={cachedStatus}
        foot={verdict.cached ? `at ${verdict.serving_layer}` : "no layer holds the object"}
      >
        <ConfBar percent={confPct} label={`LLM verdict · ${verdict.confidence}`} />
      </Tile>

      <Tile
        label="CDN cache"
        value={cdn.value}
        status={cdn.status}
        foot={
          <>
            {cdn.foot}
            {cdnUnverified && <Badge variant="unverified" />}
          </>
        }
      />

      <Tile
        label="Served from"
        value={verdict.serving_layer || "—"}
        status={verdict.cached ? "hit" : "accent"}
        foot={
          <>
            layer {verdict.layer_count_to_origin} of {verdict.layer_count_to_origin}
            {servingFlagged && <Badge variant="unverified" />}
          </>
        }
      />

      <Tile
        label="Hosting / CDN"
        value={verdict.provider}
        status={providerUnknown ? "unknown" : "accent"}
        foot={
          <>
            {providerEvidenceFoot(verdict)}
            {providerFlagged && <Badge variant="unverified" />}
          </>
        }
      />
    </div>
  );
}

function providerEvidenceFoot(verdict: CacheVerdict): string {
  const ev = verdict.provider_evidence?.find((e) => /^AS\d+/i.test(e));
  return ev ?? verdict.provider_evidence?.[0] ?? "provider identity";
}
