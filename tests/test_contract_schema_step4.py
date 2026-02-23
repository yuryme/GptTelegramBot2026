from app.schemas.commands import DeleteRemindersCommand, ListRemindersCommand


def test_list_status_accepts_deleted() -> None:
    cmd = ListRemindersCommand.model_validate(
        {"command": "list_reminders", "mode": "status", "status": "deleted"}
    )
    assert cmd.status == "deleted"


def test_delete_status_accepts_deleted() -> None:
    cmd = DeleteRemindersCommand.model_validate(
        {"command": "delete_reminders", "mode": "filter", "status": "deleted"}
    )
    assert cmd.status == "deleted"
