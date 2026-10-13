EXTRACT_DUE_DATE_TOOL = {
    "name": "extract_task",
    "description": (
        "Extract the task description and, if the user mentioned one, the "
        "deadline/due date as an ISO 8601 datetime. Call this every time, "
        "even if no deadline was mentioned (leave due_at null)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "due_at": {
                "type": ["string", "null"],
                "description": (
                    "ISO 8601 datetime (e.g. 2026-10-14T15:00:00) the user wants "
                    "to be reminded by, resolved against the current date/time "
                    "given below. Null if no deadline was mentioned."
                ),
            },
        },
        "required": ["due_at"],
    },
}


def build_system_prompt(now_iso: str) -> str:
    return (
        "You extract a deadline from a short task message a person sends to "
        "their personal reminder bot. The message itself is kept verbatim as "
        "the task title -- you only need to resolve any date/time mentioned "
        "in it into an absolute ISO 8601 datetime, relative to the current "
        f"date and time: {now_iso}. "
        "Examples: 'tomorrow 3pm' -> tomorrow's date at 15:00; 'in 2 hours' -> "
        "now + 2 hours; 'Friday' -> the next upcoming Friday, at 09:00 if no "
        "time given. If the message mentions no deadline at all, call the "
        "tool with due_at set to null. Always call the extract_task tool "
        "exactly once."
    )
