// Chat + reads ramp step (#227). One step per run: -e VUS=N. Thresholds are the SLOs in
// docs/benchmarks/load-test.md section 2, fixed before any run.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const API = __ENV.API || 'http://api:8080';
const N = parseInt(__ENV.VUS || '5');
const HOLD = __ENV.HOLD || '60s';
const books = JSON.parse(open('/load/.data/books.json'));
const H = { headers: { 'X-Dev-User': 'load-user', 'Content-Type': 'application/json' } };
const QUESTIONS = ['Người dân sống bằng nghề gì?', 'Mùa màng phụ thuộc vào đâu?',
  'Đê điều được xây để làm gì?', 'Thương mại ở làng xã ra sao?', 'Chữ Nôm là gì?'];
const chatStart = new Trend('chat_start', true);
const chatTotal = new Trend('chat_total', true);
const readDur = new Trend('read_dur', true);

export const options = {
  scenarios: {
    chat: { executor: 'ramping-vus', exec: 'chat', startVUs: 0,
      stages: [{ duration: '15s', target: N }, { duration: HOLD, target: N }] },
    reads: { executor: 'ramping-vus', exec: 'reads', startVUs: 0,
      stages: [{ duration: '15s', target: N }, { duration: HOLD, target: N }] },
  },
  thresholds: {
    'chat_start{phase:hold}': ['p(95)<=1000'],
    'chat_total{phase:hold}': ['p(95)<=6000'],
    'read_dur{phase:hold}': ['p(95)<=300'],
    'checks{kind:chat,phase:hold}': ['rate>=0.99'],
    'checks{kind:read,phase:hold}': ['rate>=0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};
const t0 = Date.now();
const phase = () => (Date.now() - t0 > 15000 ? 'hold' : 'ramp');
const pick = (a) => a[Math.floor(Math.random() * a.length)];

export function chat() {
  const ph = phase();
  const r = http.post(`${API}/books/${pick(books)}/chat`,
    JSON.stringify({ question: pick(QUESTIONS), top_k: 6 }), { ...H, tags: { phase: ph } });
  chatStart.add(r.timings.waiting, { phase: ph });
  chatTotal.add(r.timings.duration, { phase: ph });
  check(r, { 'chat ok': (x) => x.status === 200 && String(x.body).includes('event: done') },
    { kind: 'chat', phase: ph });
  sleep(10);
}

export function reads() {
  const ph = phase();
  let r = http.get(`${API}/books`, { ...H, tags: { phase: ph } });
  readDur.add(r.timings.duration, { phase: ph });
  check(r, { 'list ok': (x) => x.status === 200 }, { kind: 'read', phase: ph });
  r = http.get(`${API}/books/${pick(books)}`, { ...H, tags: { phase: ph } });
  readDur.add(r.timings.duration, { phase: ph });
  check(r, { 'get ok': (x) => x.status === 200 }, { kind: 'read', phase: ph });
  sleep(3);
}
