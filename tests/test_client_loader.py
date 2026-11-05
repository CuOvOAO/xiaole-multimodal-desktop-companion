import threading
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication
from ui.workers import ClientLoader


def test_client_initializes_in_worker_and_delivers_through_queued_signal():
    app = QApplication.instance() or QApplication([])
    main_id = threading.get_ident()
    ids, clients = [], []
    class Client:
        def close(self):
            pass
    def factory(use_memory):
        ids.append(threading.get_ident())
        return Client()
    worker = ClientLoader(factory=factory)
    loop = QEventLoop()
    worker.client_ready.connect(clients.append, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(loop.quit, Qt.ConnectionType.QueuedConnection)
    QTimer.singleShot(1500, loop.quit)
    worker.start()
    loop.exec()
    assert worker.wait(1500)
    app.processEvents()
    assert ids and ids[0] != main_id
    assert len(clients) == 1
