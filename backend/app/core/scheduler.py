"""
Background task scheduler for periodic jobs

Uses APScheduler for scheduling background tasks like LDAP sync.
"""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.logger import logger
from app.db.session import get_session
from app.services.ldap_sync_service import LdapSyncService


# Global scheduler instance
scheduler = AsyncIOScheduler()


def ldap_sync_job():
    """
    LDAP synchronization job

    Runs periodically to sync users and groups from LDAP server.
    """
    logger.info("Starting scheduled LDAP sync...")

    try:
        # Get a new database session
        session = next(get_session())

        try:
            result = LdapSyncService.sync(session)
            logger.info(
                f"Scheduled LDAP sync completed: "
                f"created={result.get('users_created', 0)}, "
                f"updated={result.get('users_updated', 0)}, "
                f"disabled={result.get('users_disabled', 0)}"
            )
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Scheduled LDAP sync failed: {str(e)}")


def init_scheduler():
    """
    Initialize and start the background scheduler

    Configures all periodic jobs:
    - LDAP sync: Every 15 minutes
    """
    # LDAP sync job - every 15 minutes
    # 无密码模式（单机/离线部署）没有目录服务可同步，注册了只会每 15 分钟
    # 刷一条连接失败的 ERROR 日志，把真正的问题淹掉。
    if settings.AUTH_DISABLED:
        logger.info("Scheduler jobs configured: LDAP sync skipped (AUTH_DISABLED)")
    else:
        scheduler.add_job(
            ldap_sync_job,
            trigger=IntervalTrigger(minutes=15),
            id="ldap_sync",
            name="LDAP User Sync",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
            coalesce=True     # Combine missed runs
        )
        logger.info("Scheduler jobs configured:")
        logger.info("  - LDAP sync: every 15 minutes")

    # Start the scheduler
    scheduler.start()
    logger.info("Background scheduler started")


def shutdown_scheduler():
    """
    Shutdown the background scheduler gracefully
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")


def get_scheduler_jobs():
    """
    Get list of scheduled jobs

    Returns:
        List of job info dicts
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    return jobs


def get_next_ldap_sync_time() -> datetime:
    """
    Get the next scheduled LDAP sync time

    Returns:
        datetime of next run, or None if not scheduled
    """
    job = scheduler.get_job("ldap_sync")
    if job and job.next_run_time:
        return job.next_run_time
    return None
