import numpy as np

from core.screen_watcher import ScreenWatcher


def test_screen_diff_ignores_small_pixel_changes():
    first = np.zeros((10, 10, 3), dtype=np.uint8)
    second = np.full((10, 10, 3), 20, dtype=np.uint8)
    assert ScreenWatcher._diff_ratio(first, second) == 0.0


def test_screen_diff_detects_large_changes():
    first = np.zeros((10, 10, 3), dtype=np.uint8)
    second = np.full((10, 10, 3), 255, dtype=np.uint8)
    assert ScreenWatcher._diff_ratio(first, second) == 1.0
