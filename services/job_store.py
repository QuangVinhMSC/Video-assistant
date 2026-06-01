from datetime import datetime
from sqlmodel import Session, select
from db import engine
from models.job import JobState, JobStatus


def create_job(job_id: str, video_path: str, job_dir: str = None, **kwargs) -> JobState:
    job = JobState(job_id=job_id, video_path=video_path, job_dir=job_dir, **kwargs)
    with Session(engine) as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.model_copy()


def get_job(job_id: str) -> JobState | None:
    with Session(engine) as session:
        job = session.get(JobState, job_id)
        return job.model_copy() if job else None


def update_job(job_id: str, **kwargs) -> JobState:
    with Session(engine) as session:
        job = session.get(JobState, job_id)
        for k, v in kwargs.items():
            # store enum values as their string equivalent
            setattr(job, k, v.value if isinstance(v, JobStatus) else v)
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.model_copy()


def fail_job(job_id: str, step: str, error: str) -> JobState:
    return update_job(job_id, status=JobStatus.failed, step=step, error=error)
