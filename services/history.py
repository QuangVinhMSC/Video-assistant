from sqlmodel import Session, select
from db import engine
from models.conversation import ConversationTurn


def save_turn(job_id: str, question: str, answer: str, confidence: str = None) -> None:
    with Session(engine) as session:
        count = session.exec(
            select(ConversationTurn).where(ConversationTurn.job_id == job_id)
        ).all()
        turn_num = len(count) + 1
        turn = ConversationTurn(
            job_id=job_id,
            turn=turn_num,
            question=question,
            answer=answer,
            confidence=confidence,
        )
        session.add(turn)
        session.commit()


def get_conversation_history(job_id: str, last_n: int = 5) -> list[dict]:
    with Session(engine) as session:
        turns = session.exec(
            select(ConversationTurn)
            .where(ConversationTurn.job_id == job_id)
            .order_by(ConversationTurn.turn)
        ).all()
        recent = turns[-last_n:] if len(turns) > last_n else turns
        return [{"turn": t.turn, "question": t.question, "answer": t.answer} for t in recent]


def clear_history(job_id: str) -> None:
    with Session(engine) as session:
        turns = session.exec(
            select(ConversationTurn).where(ConversationTurn.job_id == job_id)
        ).all()
        for t in turns:
            session.delete(t)
        session.commit()


def get_turn_count(job_id: str) -> int:
    with Session(engine) as session:
        turns = session.exec(
            select(ConversationTurn).where(ConversationTurn.job_id == job_id)
        ).all()
        return len(turns)
