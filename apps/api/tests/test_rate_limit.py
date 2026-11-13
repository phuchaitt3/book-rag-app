from book_rag_api.rate_limit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_says_how_long_to_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(2, window=60, clock=clock)

    assert limiter.check("a") is None
    clock.now = 10
    assert limiter.check("a") is None
    assert limiter.check("a") == 50


def test_window_slides() -> None:
    clock = Clock()
    limiter = RateLimiter(1, window=60, clock=clock)
    limiter.check("a")
    clock.now = 61

    assert limiter.check("a") is None


def test_keys_are_counted_separately() -> None:
    limiter = RateLimiter(1, window=60)
    limiter.check("a")

    assert limiter.check("b") is None


def test_limit_zero_turns_it_off() -> None:
    limiter = RateLimiter(0, window=60)

    assert all(limiter.check("a") is None for _ in range(100))
