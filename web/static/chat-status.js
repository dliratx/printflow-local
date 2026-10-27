'use strict';

// One presentation model for live events, state polling and page reloads.
// Elapsed time is not a percentage or evidence that a model is still running.
const chatStatusView = (state = {}, options = {}) => {
  const now = options.now ?? Date.now(), p = state.progress || {};
  const timestamp = value => { const n = Date.parse(value); return Number.isFinite(n) ? n : null; };
  const started = timestamp(p.started_at), updated = timestamp(p.last_event_at), finished = timestamp(p.finished_at);
  const age = updated === null ? null : Math.max(0, Math.floor((now - updated) / 1000));
  const duration = started === null ? null : Math.max(0, Math.floor(((state.busy ? now : finished ?? now) - started) / 1000));
  const format = n => n === null ? '—' : n < 60 ? `${n}s` : `${Math.floor(n / 60)}m ${String(n % 60).padStart(2, '0')}s`;
  let phase = p.phase || (state.busy ? 'thinking' : 'idle');
  let label = p.label || (state.busy ? 'Waiting for an activity update' : 'Ready for your next idea');
  let detail = state.busy ? 'Live updates from this request' : 'Your conversation is saved locally';
  const offline = options.transportOffline || state.connected === false;
  if (!state.busy && phase === 'completed' && (p.failed_actions || p.steps?.some(s => s.status === 'failed'))) {
    phase = 'partial'; label = 'Response finished with issues';
  }
  if (offline) { phase = 'disconnected'; label = 'Connection interrupted'; detail = 'Request status is unavailable. Reconnecting to live updates.'; }
  else if (phase === 'waiting') detail = 'Your response is needed to continue';
  else if (state.busy && age !== null && age >= 45) {
    phase = 'quiet'; label = 'Waiting for an update';
    detail = `Last activity ${format(age)} ago. The request has not reported completion.`;
  } else if (state.busy && age !== null) detail = age < 5 ? 'Activity received just now' : `Last activity ${format(age)} ago`;
  else if (phase === 'error') detail = 'The request ended with an error. Check the response above.';
  else if (phase === 'partial') detail = 'Some actions failed. Review the response and any prepared results below.';
  else if (phase === 'stopped') detail = 'The request was interrupted';
  const active = Boolean(state.busy) && !offline;
  return {phase, label, detail, elapsed: duration === null ? '' : `${format(duration)} elapsed`,
    visible: Boolean(state.busy) || Boolean(p.finished_at) || ['error', 'disconnected', 'waiting'].includes(phase),
    animate: active && !['waiting', 'quiet', 'error', 'disconnected'].includes(phase),
    canStop: active, steps: p.steps || [],
    header: offline ? 'Connection interrupted' : state.busy ? (phase === 'quiet' ? 'Waiting for an update' : phase === 'waiting' ? 'Needs your input' : 'Working on your request') : state.authenticated ? 'Ready for your next idea' : 'Sign in to Codex'};
};
