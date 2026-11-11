from dagster import (
    AssetExecutionContext,
    DefaultScheduleStatus,
    Definitions,
    Failure,
    ScheduleDefinition,
    asset,
    define_asset_job,
)

from data.pipelines import runner


@asset
def warehouse(context: AssetExecutionContext) -> None:
    """Sync every source into raw, then build and test the warehouse with dbt."""
    synced, built = runner.refresh()
    for source, outcome in synced.items():
        context.log.info(f"{source}: {outcome}")
    failed = runner.failed_sources(synced)
    if failed or not built:
        raise Failure(
            f"sources that failed: {failed or 'none'}; warehouse build passed: {built}. "
            "See meta.sync_runs and meta.check_results."
        )


refresh_job = define_asset_job("refresh", selection=[warehouse])

defs = Definitions(
    assets=[warehouse],
    jobs=[refresh_job],
    schedules=[
        # Hourly, matching the expected intervals in data.landing.EXPECTED_EVERY.
        ScheduleDefinition(
            job=refresh_job,
            cron_schedule="0 * * * *",
            default_status=DefaultScheduleStatus.RUNNING,
        )
    ],
)
