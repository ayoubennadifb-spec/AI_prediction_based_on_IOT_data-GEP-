"""gep_forecast -- clean rebuild of the GEP indoor-climate forecasting pipeline.

Modules:
    config      shared window contract + constants (single source of truth)
    data        de-dup loader, quality filters, gap-aware segmentation
    windows     window index + boundary-purged chronological splits
    scaling     train-only persisted scaler bundle
    baselines   persistence + seasonal-naive reference forecasters
    evaluation  per-horizon metrics in physical units + skill scores
"""
