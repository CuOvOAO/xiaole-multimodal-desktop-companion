from core.desktop import HumanLikeController


def test_search_url_is_encoded(monkeypatch):
    opened = []
    controller = HumanLikeController()
    monkeypatch.setattr("core.desktop.webbrowser.open", lambda url: opened.append(url) or True)
    monkeypatch.setattr("core.desktop.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        controller, "click_first_result", lambda: "跳过真实点击"
    )

    result = controller.search_web("蕾缪乐 & 明日方舟", "wikipedia")

    assert "%26" in opened[0]
    assert "+" in opened[0]
    assert "wikipedia" in result


def test_search_coordinates_are_mapped_and_rejected_outside_image(monkeypatch):
    from types import SimpleNamespace
    import base64
    import io
    from PIL import Image
    import core.screen
    buf = io.BytesIO()
    Image.new("RGB", (960, 540)).save(buf, "JPEG")
    image = base64.b64encode(buf.getvalue()).decode()
    monkeypatch.setattr(core.screen, "get_screen_capture", lambda: SimpleNamespace(
        _capture_b64=lambda: image, monitor={"left": -1920, "top": 0, "width": 1920, "height": 1080}))
    controller = HumanLikeController()
    calls = []
    monkeypatch.setattr(controller, "click", lambda x, y: calls.append((x, y)))
    controller.llm_client = SimpleNamespace(vision_chat_local=lambda *args: '{"x":480,"y":270}')
    assert "已点击" in controller.click_first_result()
    assert calls == [(-960, 540)]
    controller.llm_client.vision_chat_local = lambda *args: '{"x":961,"y":100}'
    assert "超出" in controller.click_first_result()
    assert len(calls) == 1
