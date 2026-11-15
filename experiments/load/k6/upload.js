// Upload + ingestion ramp step (#227). -e RATE=<uploads per second>. Thresholds: SLO table in
// docs/benchmarks/load-test.md. Ingestion time is measured by polling each job to the end.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const API = __ENV.API || 'http://api:8080';
const RATE = parseFloat(__ENV.RATE || '0.1');
const pdf = open('/load/.data/upload.pdf', 'b');
const H = { 'X-Dev-User': 'load-user' };
const upDur = new Trend('upload_dur', true);
const ingest = new Trend('ingest_s');
const failed = new Counter('ingest_failed');
const timedOut = new Counter('ingest_timeout');

export const options = {
  scenarios: { up: { executor: 'constant-arrival-rate', rate: Math.round(RATE * 100), timeUnit: '100s',
    duration: '60s', preAllocatedVUs: 50, maxVUs: 400 } },
  thresholds: { upload_dur: ['p(95)<=3000'], ingest_s: ['p(95)<=90'],
    ingest_failed: ['count==0'], ingest_timeout: ['count==0'], 'checks{kind:upload}': ['rate>=0.99'] },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};

export default function () {
  const start = Date.now();
  const r = http.post(`${API}/books`, { file: http.file(pdf, 'u.pdf', 'application/pdf'), title: 'u' },
    { headers: H });
  upDur.add(r.timings.duration);
  if (!check(r, { 'upload 201': (x) => x.status === 201 }, { kind: 'upload' })) return;
  const job = r.json('job_id');
  for (let i = 0; i < 90; i++) { // poll up to ~180 s
    sleep(2);
    const s = http.get(`${API}/ingestion-jobs/${job}`, { headers: H }).json('status');
    if (s === 'succeeded') { ingest.add((Date.now() - start) / 1000); return; }
    if (s === 'failed') { failed.add(1); return; }
  }
  timedOut.add(1);
}
