from sqlalchemy.orm import Session

from app.models import LogEntry


def add_log(db: Session, task_id: str, level: str, module: str, message: str) -> None:
    db.add(LogEntry(task_id=task_id, level=level, module=module, message=message[:12000]))
    db.commit()

