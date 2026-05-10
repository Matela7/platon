Task: choose ONE route for the user's query.

Return EXACTLY two lines:
route: <collections|web|hybrid|direct|clarify>
reason: <max 12 words, user's language>

Route definitions:
1) collections -> answer should be based on local document collections.
	Use when the user expects you to search uploaded/internal docs.
2) web -> question needs up-to-date information (news, prices, current events).
	Use when user asks for "latest", "today", "now", or a recent year.
3) hybrid -> needs both local docs AND web freshness/verification.
4) direct -> can be answered from general knowledge without tools.
5) clarify -> request is ambiguous; missing entity, timeframe, or required source.

Tie-breakers:
- If unsure between collections and hybrid, choose hybrid.
- If unsure overall, choose hybrid.
