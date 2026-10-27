from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from graph_upload_tasks import UploadTasks, UploadAdmissionError


def test_four_visual_requests_overlap_and_capacity_is_released_on_failure():
    tasks = UploadTasks()
    entered = threading.Barrier(5)
    release = threading.Event()

    def request(index):
        with tasks.admit('browser', str(index)):
            entered.wait(timeout=5)
            assert release.wait(timeout=5)
            if index == 0:
                raise RuntimeError('isolated model failure')
            return index

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(request, index) for index in range(4)]
        try:
            entered.wait(timeout=5)
            assert tasks.active_count() == 4
            with pytest.raises(UploadAdmissionError, match='recognition_capacity'):
                with tasks.admit('another-browser', 'fifth'):
                    pytest.fail('A fifth request must not start a visual model')
        finally:
            release.set()
        with pytest.raises(RuntimeError, match='isolated model failure'):
            futures[0].result()
        assert [future.result() for future in futures[1:]] == [1, 2, 3]
    assert tasks.active_count() == 0
    with tasks.admit('browser', 'next'):
        assert tasks.active_count() == 1


def test_same_task_cannot_run_twice_but_browser_task_ids_are_independent():
    tasks = UploadTasks()
    with tasks.admit('one', 'image'):
        with pytest.raises(UploadAdmissionError, match='duplicate_active_task'):
            with tasks.admit('one', 'image'):
                pytest.fail('Duplicate model request')
        with tasks.admit('two', 'image'):
            assert tasks.active_count() == 2
    assert tasks.active_count() == 0
