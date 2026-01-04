# core/streak.py
"""
Streak calculation utilities for DailySelfie.
"""
from datetime import datetime, timedelta
from typing import List, Tuple


def calculate_streaks(date_strings: List[str], today: datetime = None) -> Tuple[int, int, bool]:
    """
    Calculate current streak and best streak from a list of date strings.
    
    Args:
        date_strings: Sorted list of dates in 'YYYY-MM-DD' format
        today: Optional datetime to use as "today" (for testing). Defaults to now.
    
    Returns:
        Tuple of (current_streak, best_streak, has_photo_today)
        
    Behavior:
        - If photo taken today: current streak counts from today backwards
        - If no photo today: current streak counts from yesterday backwards
          (so user sees their "at risk" streak that will break if they don't take photo)
    """
    if today is None:
        today = datetime.now()
    
    today_date = today.date()
    
    # Convert strings to date objects for easier comparison
    dates = set()
    for ds in date_strings:
        try:
            dates.add(datetime.strptime(ds, '%Y-%m-%d').date())
        except ValueError:
            continue  # Skip malformed dates
    
    if not dates:
        return (0, 0, False)
    
    # Check if photo taken today
    has_photo_today = today_date in dates
    
    # Current streak: count consecutive days
    # Start from today if photo exists, otherwise from yesterday
    current_streak = 0
    check_date = today_date if has_photo_today else today_date - timedelta(days=1)
    
    while check_date in dates:
        current_streak += 1
        check_date -= timedelta(days=1)
    
    # Best streak: walk through all dates and find longest run
    sorted_dates = sorted(dates)
    best_streak = 0
    run = 1
    
    for i in range(1, len(sorted_dates)):
        if sorted_dates[i] - sorted_dates[i-1] == timedelta(days=1):
            run += 1
        else:
            best_streak = max(best_streak, run)
            run = 1
    best_streak = max(best_streak, run)  # Don't forget last run
    
    return (current_streak, best_streak, has_photo_today)