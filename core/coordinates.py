"""Convert screenshot pixels to physical desktop coordinates, including offset monitors."""
import math


def image_to_desktop(x, y, width, height, monitor):
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (x, y)):
        raise ValueError("点击坐标不是有效数字")
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("坐标超出截图范围")
    return (monitor["left"] + round(x * monitor["width"] / width),
            monitor["top"] + round(y * monitor["height"] / height))
