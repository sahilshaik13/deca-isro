/** Single source of truth for offline ML cite-board numbers (guide v2). */
export const DECA_CITE_BOARD = {
  /** GNS3 transfer / holdout-style board line */
  gns3_transfer: 0.884,
  chaos_f1: 0.815,
  q1_mae: 0.655,
  q2_holdout: 0.992,
  q1_lead_s: 7.1,
  checkpoint: 'infer_q1_q2_live · sealed q2_severity.joblib',
  line: '0.884 / 0.815 / 0.655 / 0.992 / 7.1s',
} as const
