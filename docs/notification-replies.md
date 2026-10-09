# Replying to task notifications

Native Companion opens Details in the original task conversation and sends Reply
through its paired, stable-ID continuation endpoint. Offline drafts preserve the
same follow-up ID on retries. The recorded worker session resumes; replying does
not blindly replay prior side effects or change the original task's terminal state.

Browser task pages use standalone owner login. Signed view/follow-up links remain
scoped to their original task and do not authorize unrelated queue actions.
See [task access](phone-task-status.md) and [native delivery](native-companion.md).
