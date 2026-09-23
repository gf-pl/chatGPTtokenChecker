import os


def refresh_interval() -> int:
    try:
        return max(60, int(os.getenv("REFRESH_INTERVAL_SECONDS", "300")))
    except ValueError:
        return 300
