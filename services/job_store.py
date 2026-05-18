from models.job import JobState, JobStatus

_jobs: dict[str, JobState] = {}


def create_job(job_id: str, video_path: str) -> JobState:
    job = JobState(job_id=job_id, video_path=video_path)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> JobState | None:
    return _jobs.get(job_id)


def update_job(job_id: str, **kwargs) -> JobState:
    job = _jobs[job_id]
    updated = job.model_copy(update=kwargs)
    _jobs[job_id] = updated
    return updated


def fail_job(job_id: str, step: str, error: str) -> JobState:
    return update_job(job_id, status=JobStatus.failed, step=step, error=error)
