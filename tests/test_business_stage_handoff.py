"""Staging windows and background profile writers must not invalidate each other.

A wrapped node snapshots the business DB, does LLM/tool work, then publishes only
its changed rows optimistically. The memory summary worker writes the same
profile row in the background; if it commits inside that window the apply fails
closed and the user sees ``E_NODE_FAILED``. Reproduced with real requests
(1 in 5 temple turns); these tests pin the hand-off that prevents it.
"""

import threading
import time

from app import business_stage


def _reset():
    business_stage._STAGING_DEPTH = 0
    business_stage._BACKGROUND_WRITERS = 0


def test_staging_waits_for_an_in_flight_background_commit():
    _reset()
    business_stage._BACKGROUND_WRITERS = 1
    entered: list[float] = []

    def worker():
        with business_stage.background_write_window(0.0):
            pass

    def staging():
        start = time.monotonic()
        business_stage._enter_staging(timeout=1.0)
        entered.append(time.monotonic() - start)
        business_stage._leave_staging()

    t = threading.Thread(target=staging)
    t.start()
    time.sleep(0.05)
    assert not entered, "staging must wait while a background writer holds the window"
    business_stage._BACKGROUND_WRITERS = 0
    with business_stage._STAGING_CV:
        business_stage._STAGING_CV.notify_all()
    t.join(2.0)
    assert entered and entered[0] >= 0.05


def test_background_writer_waits_for_staging_to_close():
    _reset()
    business_stage._enter_staging(timeout=1.0)
    done: list[bool] = []

    def writer():
        with business_stage.background_write_window(2.0):
            done.append(True)

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.05)
    assert not done, "background writes must not commit inside a staging window"
    business_stage._leave_staging()
    t.join(2.0)
    assert done == [True]
    assert business_stage._BACKGROUND_WRITERS == 0
    assert business_stage.staging_active() == 0


def test_background_writer_still_proceeds_after_timeout():
    _reset()
    business_stage._enter_staging(timeout=1.0)
    started = time.monotonic()
    with business_stage.background_write_window(0.1):
        pass
    assert time.monotonic() - started >= 0.05
    business_stage._leave_staging()
    assert business_stage._BACKGROUND_WRITERS == 0


def test_nested_staging_does_not_deadlock_against_itself():
    _reset()
    business_stage._enter_staging(timeout=0.1)
    try:
        business_stage._enter_staging(timeout=0.1)  # nested node call
        assert business_stage.staging_active() == 2
        business_stage._leave_staging()
    finally:
        business_stage._leave_staging()
    assert business_stage.staging_active() == 0
