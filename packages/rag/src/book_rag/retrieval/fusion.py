from collections.abc import Hashable, Sequence

# 60 is the constant from the original RRF paper (Cormack et al., 2009) and the usual default.
RRF_K = 60


def reciprocal_rank_fusion[T: Hashable](
    rankings: Sequence[Sequence[T]], k: int = RRF_K
) -> list[tuple[T, float]]:
    """Merge ranked lists: each item scores the sum of 1 / (k + rank) over the lists it is in.

    Ties keep the order in which items first appeared.
    """
    scores: dict[T, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
