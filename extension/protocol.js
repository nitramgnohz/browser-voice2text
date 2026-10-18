export function createTranscript(sessionId) {
  return {sessionId, rows: [], clearThrough: -1, maxSegment: -1, dropped: 0};
}

export function reduceTranscript(state, event) {
  if (event.type !== 'transcript' || event.session_id !== state.sessionId ||
      !Number.isInteger(event.segment_id) || !Number.isInteger(event.revision) ||
      typeof event.text !== 'string' || event.segment_id <= state.clearThrough) return state;
  const index = state.rows.findIndex(row => row.segment_id === event.segment_id);
  if (index >= 0 && (state.rows[index].revision >= event.revision || state.rows[index].final)) return state;
  const rows = state.rows.slice();
  if (index >= 0) rows[index] = event;
  else rows.push(event);
  rows.sort((a,b) => a.segment_id - b.segment_id);
  const excess = Math.max(0, rows.length - 2000);
  return {...state, rows: rows.slice(excess), maxSegment: Math.max(state.maxSegment,event.segment_id), dropped:state.dropped + excess};
}

export function clearTranscript(state) {
  return {...state, rows:[], clearThrough:state.maxSegment, dropped:0};
}

export function transcriptText(state) {
  return state.rows.map(row => row.text).filter(Boolean).join('\n');
}
