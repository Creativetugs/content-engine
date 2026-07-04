"""Smoke tests for YouTube download and /repurpose error handling."""

from __future__ import annotations

import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.youtube import download_youtube_audio

VIDEO_IDS = ("pRZrFtp-V-4", "FYUcKJZ2pZs")


def test_youtube_downloads() -> None:
    for video_id in VIDEO_IDS:
        url = f"https://www.youtube.com/watch?v={video_id}"
        result = download_youtube_audio(url)
        assert result["file_path"], f"{video_id}: missing file_path"
        assert result["title"], f"{video_id}: missing title"
        print(f"OK download {video_id}: {result['title']!r}")


def test_repurpose_youtube_end_to_end() -> None:
    video_id = VIDEO_IDS[0]
    with (
        patch("app.main.transcribe_audio", return_value="test transcript"),
        patch("app.main.generate_content", return_value={"blog": {"title": "Test"}}),
    ):
        client = TestClient(app)
        response = client.post(
            "/repurpose",
            data={
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                "generate_visuals": "false",
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"]["type"] == "youtube"
    print(f"OK /repurpose {video_id}: {payload['source']['title']!r}")


def test_value_error_returns_400_not_502() -> None:
    with patch(
        "app.main.download_youtube_audio",
        side_effect=ValueError("This YouTube video could not be downloaded."),
    ):
        client = TestClient(app)
        response = client.post(
            "/repurpose",
            data={"youtube_url": "https://www.youtube.com/watch?v=invalid000"},
        )
    assert response.status_code == 400, response.text
    assert response.status_code != 502
    print("OK ValueError maps to HTTP 400")


def main() -> int:
    tests = (
        test_youtube_downloads,
        test_repurpose_youtube_end_to_end,
        test_value_error_returns_400_not_502,
    )
    for test in tests:
        print(f"\n--- {test.__name__} ---")
        test()
    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
