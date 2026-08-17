from __future__ import annotations

from queue import Queue
from threading import Event, Lock, Thread
from typing import Any

from .database import Database
from .transcriber import TranscriptionError, save_transcript_result, transcribe_video


JOB_TYPE = "transcript"
PROVIDER = "faster_whisper"


class TranscriptQueue:
    """Background worker that batch-generates Whisper transcripts for videos."""

    def __init__(self, database: Database):
        self.database = database
        self._jobs: Queue[int | None] = Queue()
        self._stop = Event()
        self._lock = Lock()
        self._paused = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._paused = False
            self.database.requeue_interrupted_analysis_jobs(analysis_type=JOB_TYPE)
            for job_id in self.database.list_queued_analysis_job_ids(analysis_type=JOB_TYPE):
                self._jobs.put(job_id)
            self._thread = Thread(
                target=self._run,
                name="transcript-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    def enqueue_pending(
        self,
        channel_id: str | None = None,
        limit: int = 10,
        force: bool = False,
        video_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if video_ids:
            target_ids = video_ids
        elif force:
            target_ids = self._list_video_ids(channel_id, limit)
        else:
            target_ids = self.database.list_videos_without_transcript(channel_id, limit)
        jobs = self.database.queue_analysis_jobs(
            target_ids,
            analysis_type=JOB_TYPE,
            provider=PROVIDER,
            force=force,
        )
        for job in jobs:
            self._jobs.put(int(job["job_id"]))
        return {
            "queued": len(jobs),
            "video_ids": [job["video_id"] for job in jobs],
            "channel_id": channel_id,
            "limit": limit,
            "force": force,
        }

    def cancel_queued(self, job_id: int) -> dict[str, Any] | None:
        return self.database.cancel_queued_analysis_job(job_id)

    def retry(self, job_id: int) -> dict[str, Any] | None:
        job = self.database.retry_analysis_job(job_id)
        if job:
            self._jobs.put(job_id)
        return job

    def set_paused(self, paused: bool) -> dict[str, Any]:
        with self._lock:
            self._paused = paused
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            paused = self._paused
        status = self.database.analysis_queue_status(analysis_type=JOB_TYPE)
        return {
            **status,
            "paused": paused,
            "worker_running": bool(self._thread and self._thread.is_alive()),
        }

    def _list_video_ids(self, channel_id: str | None, limit: int) -> list[str]:
        videos = self.database.list_videos(channel_id=channel_id, limit=limit)
        return [str(video["youtube_video_id"]) for video in videos]

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._jobs.get()
            try:
                if job_id is None:
                    return
                while not self._stop.is_set():
                    with self._lock:
                        paused = self._paused
                    if not paused:
                        break
                    self._stop.wait(timeout=0.25)
                if self._stop.is_set():
                    continue
                self._process(job_id)
            finally:
                self._jobs.task_done()

    def _process(self, job_id: int) -> None:
        job = self.database.claim_analysis_job(job_id)
        if not job:
            return
        video_id = str(job["youtube_video_id"])
        try:
            video = self.database.get_video(video_id)
            if not video:
                raise ValueError(f"Video không tồn tại: {video_id}")

            result = transcribe_video(video["video_url"], video_id, language=None)
            if not result["text"]:
                raise TranscriptionError("Whisper không nhận diện được nội dung thoại nào trong audio")

            save_transcript_result(self.database, video_id, result)
            self.database.finish_analysis_job(job_id, "completed")
        except Exception as exc:
            self.database.finish_analysis_job(job_id, "error", str(exc))
