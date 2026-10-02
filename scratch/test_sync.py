import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.services.yahoo_service import YahooService
from app.services.sync_service import SyncService
from app.services.market_data_service import MarketDataService

def test():
    db_path = Path("data/test_run.db")
    db = Database(db_path)
    repo = MarketDataRepository(db)
    yahoo = YahooService()
    sync = SyncService(yahoo, repo)
    market_svc = MarketDataService(repo)

    print("Testing sync for AAPL...")
    ok, msg, count = sync.sync_ticker("AAPL")
    print(f"Sync result: ok={ok}, msg='{msg}', count={count}")

    points = repo.get_prices("AAPL")
    print(f"Retrieved {len(points)} price points from SQLite.")
    if points:
        print(f"First point: {points[0].timestamp} - ${points[0].close:.2f}")
        print(f"Latest point: {points[-1].timestamp} - ${points[-1].close:.2f}")

    if db_path.exists():
        import os
        try:
            os.remove(db_path)
        except Exception:
            pass

if __name__ == "__main__":
    test()
