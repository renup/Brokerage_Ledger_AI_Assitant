from datetime import date, timedelta


# The date that is "business_days" working days after "start". Working days are Monday to Friday.
# Weekends are skipped; market holidays are NOT (we chose weekends-only for now).
# If start is itself on a weekend, counting begins with the next Monday.
def add_business_days(start: date, business_days: int) -> date:
    current = start
    remaining = business_days
    while remaining > 0:
        # Step forward one calendar day
        current += timedelta(days=1)
        # weekday() is 0 for Monday up to 6 for Sunday, so 5 and 6 are the weekend
        if current.weekday() < 5:
            remaining -= 1
    return current
