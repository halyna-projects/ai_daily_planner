EXTRACT_DUE_DATE_TOOL = {
    "name": "extract_task",
    "description": (
        "Extract the task description and, if the user mentioned one, the "
        "deadline/due date as an ISO 8601 datetime, plus any explicit repeat "
        "cadence the user asked for. Call this every time, even if nothing "
        "was mentioned (leave due_at and recurrence_days null)."
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
            "recurrence_days": {
                "type": ["integer", "null"],
                "description": (
                    "If the user explicitly asked to be reminded on a repeating "
                    "cadence (e.g. 'remind me daily', 'every day', 'нагадувати "
                    "щодня', 'every week', 'every 3 days'), the number of days "
                    "between repeats -- 1 for daily, 7 for weekly, N for 'every "
                    "N days'. Null if the task is a one-off with no repeating "
                    "cadence mentioned."
                ),
            },
        },
        "required": ["due_at", "recurrence_days"],
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
        "time given. If the message mentions no deadline at all, use due_at "
        "null. Separately, if the message also asks for a repeating cadence "
        "(daily, weekly, every N days -- this can appear together with a "
        "one-time deadline, e.g. 'do this by Nov 11, remind me daily'), set "
        "recurrence_days to the number of days between repeats; otherwise "
        "leave it null. Always call the extract_task tool exactly once."
    )
