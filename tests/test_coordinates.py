import pytest
from core.coordinates import image_to_desktop


def test_offset_monitor_and_resized_image_map_to_physical_pixels():
    assert image_to_desktop(480, 270, 960, 540,
                            {"left": -1920, "top": 100, "width": 1920, "height": 1080}) == (-960, 640)


def test_zero_is_a_valid_image_coordinate():
    assert image_to_desktop(0, 0, 960, 540,
                            {"left": 100, "top": 100, "width": 1920, "height": 1080}) == (100, 100)


def test_outside_and_non_numeric_coordinates_are_rejected():
    for x in (True, "100", float("nan"), float("inf"), -1, 960):
        with pytest.raises(ValueError):
            image_to_desktop(x, 0, 960, 540, {"left": 0, "top": 0, "width": 1920, "height": 1080})
