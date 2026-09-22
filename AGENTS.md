# TradePilot working instructions

Read: README.md, LATEST-STATUS.md, TRADE-INTEGRITY-REVIEW.md.

Core/ is deterministic Swift logic; iOS/ is the app; server/ is the gateway. Use fake broker responses in tests. Preserve separate per-order confirmation, duplicate prevention, account binding and live-disabled defaults. Do not submit orders, access real accounts or modify deployed gateway files as a test. Python stdlib tests do not require broker SDK credentials. Native checks require macOS/Xcode; Linux CI verifies the Python suites.

Start with the listed entry points and `devkit context` if available (or read .toolkit.json).
Use rg for scoped text searches and ast-grep for code structure. Read matching sections,
not whole trees. Run focused tests after edits; use full gates for broad changes.
`devkit run -- <command>` keeps complete local logs and prints a bounded tail, preserving
exit status. Read full failures when needed. Do not hide a failed check or claim token
savings without measurement. Keep generated outputs, private state, credentials and
.toolkit-runs out of commits. Shared tools: https://github.com/louisbrailey/developer-toolkit.
