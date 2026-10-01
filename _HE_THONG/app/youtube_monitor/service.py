from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .database import Database, utc_now
from .youtube_client import YouTubeClient, YouTubeApiError, parse_duration, parse_video_reference, thumbnail_url


YT_NS = "http://www.youtube.com/xml/schemas/2015"
ATOM_NS = "http://www.w3.org/2005/Atom"


def _metadata_hash(title: str, description: str, tags: list[str], thumbnail: str) -> str:
    value = json.dumps(
        {"title": title, "description": description, "tags": tags, "thumbnail": thumbnail},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _video_from_api(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    content = item.get("contentDetails", {})
    statistics = item.get("statistics", {})
    status = item.get("status", {})
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    tags = snippet.get("tags", []) or []
    thumbnail = thumbnail_url(snippet.get("thumbnails"))
    video_id = item["id"]
    return {
        "youtube_video_id": video_id,
        "youtube_channel_id": snippet.get("channelId", ""),
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "description": description,
        "published_at": snippet.get("publishedAt"),
        "thumbnail_url": thumbnail,
        "duration_seconds": parse_duration(content.get("duration")),
        "category_id": snippet.get("categoryId", ""),
        "default_language": snippet.get("defaultLanguage", ""),
        "caption_available": 1 if content.get("caption") == "true" else 0,
        "live_broadcast_status": snippet.get("liveBroadcastContent", "none"),
        "privacy_status": status.get("privacyStatus", ""),
        "license": status.get("license", ""),
        "tags": tags,
        "view_count": _int_or_none(statistics.get("viewCount")),
        "like_count": _int_or_none(statistics.get("likeCount")),
        "comment_count": _int_or_none(statistics.get("commentCount")),
        "metadata_hash": _metadata_hash(title, description, tags, thumbnail),
        # The Data API only ever returns videos (source_kinds).
        "source_kind": "video",
        "raw_payload": item,
        "analysis_status": "pending",
        "media_status": "not_downloaded",
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_push_feed(body: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(body)
    events: list[dict[str, str]] = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        video_node = entry.find(f"{{{YT_NS}}}videoId")
        channel_node = entry.find(f"{{{YT_NS}}}channelId")
        title_node = entry.find(f"{{{ATOM_NS}}}title")
        published_node = entry.find(f"{{{ATOM_NS}}}published")
        if video_node is None or channel_node is None:
            continue
        events.append(
            {
                "video_id": video_node.text or "",
                "channel_id": channel_node.text or "",
                "title": title_node.text if title_node is not None else "",
                "published_at": published_node.text if published_node is not None else "",
            }
        )
    return events


class SyncService:
    def __init__(self, database: Database, youtube: YouTubeClient, max_initial_videos: int = 100):
        self.database = database
        self.youtube = youtube
        self.max_initial_videos = max_initial_videos

    def add_channel(self, reference: str, group_name: str = "", max_videos: int | None = None) -> dict[str, Any]:
        channel = self.youtube.get_channel(reference)
        channel["group_name"] = group_name
        self.database.upsert_channel(channel)
        return self.sync_channel(channel["youtube_channel_id"], max_videos=max_videos, trigger="initial")

    def add_video(self, reference: str, group_name: str = "") -> dict[str, Any]:
        """Import one reference video without enumerating the channel uploads playlist."""
        video_id = parse_video_reference(reference)
        items = self.youtube.get_videos([video_id])
        if not items:
            raise YouTubeApiError("Không tìm thấy video công khai hoặc video không khả dụng", status_code=404)
        video = _video_from_api(items[0])
        if not video["youtube_channel_id"]:
            raise YouTubeApiError("Video không trả về thông tin kênh nguồn", status_code=422)
        channel = self.youtube.get_channel_by_id(video["youtube_channel_id"])
        channel["group_name"] = group_name
        self.database.upsert_channel(channel)
        saved = self.database.upsert_video(video)
        return {
            "channel_id": channel["youtube_channel_id"],
            "channel": self.database.get_channel(channel["youtube_channel_id"]),
            "video": self.database.get_video(video_id),
            "videos_seen": 1,
            "videos_new": int(saved["is_new"]),
            "videos_updated": int(not saved["is_new"] and saved["metadata_changed"]),
            "import_mode": "single_video",
        }

    def sync_channel(
        self,
        channel_id: str,
        max_videos: int | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        channel = self.database.get_channel(channel_id)
        if not channel:
            raise YouTubeApiError(f"Kênh chưa được quản lý: {channel_id}", status_code=404)
        if not channel["tracking_enabled"]:
            raise YouTubeApiError("Kênh đang tạm dừng theo dõi", status_code=409)

        run_id = self.database.start_sync_run(channel_id, trigger)
        limit = self.max_initial_videos if max_videos is None else max_videos
        try:
            refreshed_channel = self.youtube.get_channel_by_id(channel_id)
            refreshed_channel["group_name"] = channel.get("group_name", "")
            self.database.upsert_channel(refreshed_channel)
            video_ids = self.youtube.list_upload_video_ids(
                refreshed_channel["uploads_playlist_id"],
                max_videos=limit,
            )
            api_items = self.youtube.get_videos(video_ids)
            new_count = 0
            updated_count = 0
            for item in api_items:
                video = _video_from_api(item)
                if video["youtube_channel_id"] != channel_id:
                    continue
                result = self.database.upsert_video(video)
                new_count += int(result["is_new"])
                updated_count += int(not result["is_new"] and result["metadata_changed"])

            self.database.mark_channel_sync(channel_id, "ok")
            self.database.finish_sync_run(
                run_id,
                "ok",
                videos_seen=len(api_items),
                videos_new=new_count,
                videos_updated=updated_count,
            )
            return {
                "channel_id": channel_id,
                "videos_seen": len(api_items),
                "videos_new": new_count,
                "videos_updated": updated_count,
                "downloaded": 0,
                "run_id": run_id,
            }
        except Exception as exc:
            message = str(exc)
            self.database.mark_channel_sync(channel_id, "error", message)
            self.database.finish_sync_run(run_id, "error", error=message)
            raise

    def handle_push_events(self, events: list[dict[str, str]]) -> dict[str, int]:
        accepted = 0
        ignored = 0
        enriched = 0
        for event in events:
            channel = self.database.get_channel(event["channel_id"])
            if not channel or not channel["tracking_enabled"]:
                ignored += 1
                continue

            accepted += 1
            self.database.mark_channel_push(event["channel_id"])
            details = self.youtube.get_videos([event["video_id"]]) if self.youtube.api_key else []
            if details:
                video = _video_from_api(details[0])
                self.database.upsert_video(video)
                enriched += 1
            else:
                title = event.get("title", "")
                partial = {
                    "youtube_video_id": event["video_id"],
                    "youtube_channel_id": event["channel_id"],
                    "video_url": f"https://www.youtube.com/watch?v={event['video_id']}",
                    "title": title,
                    "description": "",
                    "published_at": event.get("published_at"),
                    "metadata_hash": _metadata_hash(title, "", [], ""),
                    "source_kind": "video",
                    "raw_payload": event,
                }
                self.database.upsert_video(partial)
        return {"accepted": accepted, "ignored": ignored, "enriched": enriched}
