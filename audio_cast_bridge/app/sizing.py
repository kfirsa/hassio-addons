"""Configure-time RAM provisioning estimates."""

from __future__ import annotations


def suggested_ram_mb(n_selected: int, max_concurrent_streams: int) -> int:
    """Estimate RAM to provision for a committed bridge set.

    Formula (documented in README / Ingress UI):
      128 + (N_selected × 12) + (max_concurrent_streams × 48)
    """
    n = max(0, int(n_selected))
    streams = max(1, int(max_concurrent_streams))
    return 128 + (n * 12) + (streams * 48)


def recommended_host_free_mb(suggested: int) -> int:
    """Round up suggested RSS to a comfortable host free-RAM guidance."""
    for step in (256, 384, 512, 768, 1024, 1536, 2048):
        if suggested <= step:
            return step
    return ((suggested + 255) // 256) * 256
