from datetime import UTC, datetime

import pytest

from web.parsing import parse_retry_duration


@pytest.mark.parametrize(
    "retry_after, expected_duration",
    [
        ("5", 5),
        ("5.4", 6),
        (
            "Fri, 2 Jan 1970 03:04 -0500",
            (24 * 60 * 60) + (3 * 60 * 60) + (4 * 60) + (5 * 60 * 60),
        ),
        (
            "Fri, 2 Jan 1970 03:04 -0000",
            (24 * 60 * 60) + (3 * 60 * 60) + (4 * 60),
        ),
    ],
)
def test_parse_retry_duration(retry_after, expected_duration):
    from_moment = datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)

    duration = parse_retry_duration(from_moment, retry_after)

    assert duration == expected_duration
