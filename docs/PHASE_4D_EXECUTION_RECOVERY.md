# Phase 4D — execution recovery, attempt history, and bounded retries

Phase 4D improves worker reliability while keeping retry decisions under founder control.

## Worker lease recovery

- When a worker claims an execution, it writes a lease expiry and heartbeat timestamp.
- While the model is working, AgentHQ refreshes the lease periodically.
- The worker periodically detects running attempts whose lease expired.
- Expired attempts are marked failed with a clear interruption reason; their parent task moves to `needs_attention`.
- Legacy running attempts are backfilled as immediately expired during migration so they can be surfaced rather than remaining stuck indefinitely.

## Founder retry

- Only failed or rejected attempts can be retried.
- A retry creates a new execution record and preserves the previous attempt in history.
- New attempts carry `attempt_number` and `retry_of_execution_id`.
- Existing instructions are reused by default; prior failure or rejection feedback is added to the new instructions.
- The maximum is five total attempts per task. After that, the founder must create a new task.
- A duplicate active attempt for the same task is rejected.

## Safety

- No automatic model retries are performed. The founder explicitly requests another attempt, limiting surprise AI usage.
- Retry never clears the previous failure record or prior deliverables.
- Worker leases prevent an execution from remaining in `running` after a process crash.
