interface Props {
  total: number;
  matched: number;
  regressed: number;
  errored: number;
}

export function SummaryPills({ total, matched, regressed, errored }: Props) {
  return (
    <div className="summary-pills" aria-label="Run summary">
      <span className="pill">{total} total</span>
      <span className="pill pill-ok">{matched} matched</span>
      <span className={`pill ${regressed ? "pill-bad" : ""}`}>{regressed} regressed</span>
      <span className={`pill ${errored ? "pill-warn" : ""}`}>{errored} errored</span>
    </div>
  );
}
