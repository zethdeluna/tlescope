"""
APScheduler integration for the Satellite Tracker API.

This file owns the application lifecycle: 
	- start the scheduler when the application starts 
	- stop it cleanly when the application exits
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from app.tle_fetcher import refresh_tle_cache

_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
	"""
	FastAPI lifespan context manager.

	Everything before 'yield' runs at startup; everything after runs at 
	shutdown.
	"""

	_scheduler.add_job(
		refresh_tle_cache,
		trigger="interval",
		hours=4,
		next_run_time=datetime.now(tz=timezone.utc),
		id="tle_refresh",
		max_instances=1,
		coalesce=True
	)

	_scheduler.start()
	print("[scheduler] started — TLE refresh every 4 hours (running now)")

	try:
		yield
	finally:
		_scheduler.shutdown(wait=False)
		print("[scheduler] stopped")