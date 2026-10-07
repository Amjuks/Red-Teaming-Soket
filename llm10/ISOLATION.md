# Runtime isolation

LLM10 owns its configuration, Python environment, dataset cache, journals, results,
reports, supervisor lock and logs under this directory. No LLM02 run is resumed,
stopped, overwritten or included in LLM10 statistics.

Configuration loading rejects output/cache paths that escape its own directory
(including via symlinks), coincide, or overlap. Each run has a fingerprint and its
own exclusive journal lock. Different settings cannot silently mix results.

The LLM10 native bridge is a separate binary. It reuses Loop's existing provider
connection and dependency build cache; it does not replace the LLM02 bridge.
Both projects can still call the same model server: filesystem/process isolation
does not provide dedicated endpoint capacity. Coordinate stress runs to avoid
affecting another benchmark's latency. No external dataset credentials are used.
