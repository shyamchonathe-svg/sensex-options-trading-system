import logging
from datetime import date, datetime
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

class HolidayChecker:
    def __init__(self, config: dict):
        logger.info("Initializing HolidayChecker")
        holidays = config.get('trading_holidays', [])
        self.holidays = []
        
        for h in holidays:
            try:
                if isinstance(h, str) and len(h) == 10 and h[4] == '-' and h[7] == '-':
                    self.holidays.append(datetime.strptime(h, "%Y-%m-%d").date())
                else:
                    logger.warning(f"Invalid holiday format skipped: {h}")
            except ValueError as e:
                logger.warning(f"Failed to parse holiday '{h}': {e}")
                continue
        
        if not self.holidays:
            logger.warning("No valid holidays loaded; assuming no holidays")
        
        self.weekend_days = {5, 6}  # Saturday (5), Sunday (6)
        logger.info(f"HolidayChecker initialized with holidays: {self.holidays}")

    def is_trading_day(self, check_date: Optional[Union[str, date]] = None) -> bool:
        """Check if the given date (or today) is a trading day."""
        if check_date is None:
            check_date = date.today()
        elif isinstance(check_date, str):
            try:
                check_date = datetime.strptime(check_date, "%Y-%m-%d").date()
            except ValueError as e:
                logger.error(f"Invalid date format for check_date: {e}")
                return False
        
        # Check if it's a weekend
        if check_date.weekday() in self.weekend_days:
            logger.info(f"{check_date} is a weekend (non-trading day)")
            return False
        
        # Check if it's a holiday
        if check_date in self.holidays:
            logger.info(f"{check_date} is a holiday (non-trading day)")
            return False
        
        logger.info(f"{check_date} is a trading day")
        return True
