import { Badge } from "../../components";
import type { CacheVerdict, Dns } from "./types";

// DNS panel: A/AAAA, CNAME chain with a data-driven provider signature label
// (vendor from the LLM verdict, rendered as real DOM on its own line — never CSS
// content, never overlaid on the hostname), TTL and authoritative NS.
interface DnsPanelProps {
  dns: Dns | null;
  verdict: CacheVerdict | null;
}

export function DnsPanel({ dns, verdict }: DnsPanelProps) {
  if (!dns || dns.error) {
    return (
      <div className="panel dns">
        <h3>DNS resolution</h3>
        <div className="empty-state">DNS not collected for this analysis.</div>
      </div>
    );
  }

  const provider = verdict?.provider && verdict.provider !== "UNKNOWN" ? verdict.provider : null;
  const evidence = verdict?.provider_evidence ?? [];
  // Hostname sequence: query name, then each CNAME target.
  const chain = dns.cname_chain ?? [];
  const hostnames = chain.length > 0 ? [chain[0].name, ...chain.map((c) => c.cname)] : [];

  function isSignature(hostname: string): boolean {
    if (!provider) return false;
    return evidence.some((e) => {
      const token = e.replace(/^CNAME\s+/i, "").split(/→|->/).pop()?.trim().toLowerCase() ?? "";
      return token.length >= 4 && (hostname.toLowerCase().includes(token) || token.includes(hostname.toLowerCase()));
    });
  }

  const addresses = [...(dns.a ?? []), ...(dns.aaaa ?? [])];

  return (
    <div className="panel dns">
      <h3>
        DNS resolution
        {provider && <Badge variant="badge">CDN detected</Badge>}
      </h3>
      <div className="kv">
        <div className="item">
          <div className="kl">A / AAAA record</div>
          <div className="kvval">
            {addresses.length > 0
              ? addresses.map((addr, i) => (
                  <span key={i}>
                    {addr}
                    {i < addresses.length - 1 && <br />}
                  </span>
                ))
              : "—"}
          </div>
        </div>
        {hostnames.length > 0 && (
          <div className="item">
            <div className="kl">CNAME chain</div>
            <div className="cname">
              {hostnames.map((host, i) => {
                const sig = isSignature(host);
                return (
                  <div key={i} className={sig ? "seg sig" : "seg"}>
                    {host}
                    {i < hostnames.length - 1 && !sig && <b className="arr">→</b>}
                    {sig && provider && <span className="siglabel">{provider} signature</span>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <div className="ttl-row">
          <div className="item">
            <div className="kl">Record TTL</div>
            <div className="kvval">{dns.ttl != null ? `${dns.ttl}s` : "—"}</div>
          </div>
          <div className="item">
            <div className="kl">Authoritative NS</div>
            <div className="kvval">{dns.ns?.length ? dns.ns.join(", ") : "—"}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
