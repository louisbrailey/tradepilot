# Resume TradePilot

Read LATEST-STATUS.md first. Source archive is TradePilot-source.zip in the parent outputs folder. Private credentials and live runtime are outside the archive.

Already installed: app in Apple’s iPhone17Pro simulator, working local Ollama provider, and per-user private gateway. Physical phone is not installed. The operating gateway uses Application Support; do not start a second instance from Documents or replace the current durable broker ledger with the older source snapshot.

Run scripts/check.sh with the Xcode developer directory for verification. Build into /private/tmp to avoid iCloud code-signing metadata. Use scripts/manage-local-service.py status for the per-user service; private deployment location is recorded in work/INSTALL-STATUS.md outside the deliverable.

Do not enable live trading or count unsupported broker/strategy features as complete. Latest backtest showed no live adoption candidate; final periods are now observed.
