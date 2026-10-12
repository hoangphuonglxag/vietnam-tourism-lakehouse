from __future__ import annotations

import pandas as pd

from script.crawl_data.jobs.youtube_comments import _select_videos


def test_plan_selection_does_not_recrawl_successful_videos_without_force_refresh() -> None:
    videos = pd.DataFrame(
        [
            {"video_id": "successful-video", "place_id": "place-1"},
            {"video_id": "pending-video", "place_id": "place-1"},
        ]
    )
    decision = {
        "item_ids": ["successful-video", "pending-video"],
        "existing_video_ids": ["successful-video", "pending-video"],
        "place_ids": [],
        "include_new_videos": False,
    }

    selected = _select_videos(
        videos,
        decision,
        {"successful-video"},
        force_refresh=False,
    )
    forced = _select_videos(
        videos,
        decision,
        {"successful-video"},
        force_refresh=True,
    )

    assert selected["video_id"].tolist() == ["pending-video"]
    assert forced["video_id"].tolist() == ["successful-video", "pending-video"]
