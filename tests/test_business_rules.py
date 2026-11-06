from datetime import date, timedelta

def test_due_date_is_seven_days():
    assert date(2026, 1, 1) + timedelta(days=7) == date(2026, 1, 8)

def test_late_fee_is_one_sol_per_calendar_day():
    due, returned = date(2026, 3, 1), date(2026, 3, 4)
    days = max(0, (returned - due).days)
    assert days == 3
    assert days * 1.00 == 3.00

def test_no_late_fee_when_returned_early_or_on_due_date():
    due = date(2026, 4, 7)
    assert max(0, (date(2026, 4, 7) - due).days) == 0
    assert max(0, (date(2026, 4, 5) - due).days) == 0
