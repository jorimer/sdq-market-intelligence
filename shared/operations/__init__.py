"""Operation console — platform-wide recurring-operation framework.

Modules register their operations with :func:`register_operation`; the console
(status + history + scheduler) is generic and cross-module.
"""
from shared.operations.models import OperationRun, OperationSchedule
from shared.operations.service import (
    OPERATIONS,
    Operation,
    all_status,
    get_schedules,
    get_status,
    recent_runs,
    register_operation,
    run_due_schedules,
    seed_default_schedules,
    set_schedule,
    start_scheduler,
    trigger,
    write_status,
)

__all__ = [
    "OperationRun", "OperationSchedule", "OPERATIONS", "Operation",
    "register_operation", "trigger", "all_status", "get_status", "write_status",
    "get_schedules", "set_schedule", "run_due_schedules", "seed_default_schedules",
    "start_scheduler", "recent_runs",
]
