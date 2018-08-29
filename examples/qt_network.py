"""
This examples shows how Asynker can be used in a more complex setting.

This is a graphical tool which can fetch a website and show the size of
embedded resources (such as scripts, stylesheets and images) -- it's almost
bordering on being useful for something.

PyQt5 and lxml are required.
"""

import sys

from PyQt5.QtCore import QObject, pyqtSlot, QEventLoop, QUrl, QThread, pyqtSignal, Q_ARG, Qt
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QLineEdit, QPushButton, \
    QApplication, QWidget, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest

import asynker
import lxml.html


class NetworkRequestFailed(RuntimeError):
    error: int
    error_string: str

    def __init__(self, error, error_string):
        self.error = error
        self.error_string = error_string
        super().__init__('%s (%d)' % (error_string, error))


class Network(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.network_access = QNetworkAccessManager(parent=self)
        self.in_flight = {}  # QNetworkReply -> asynker.Future

    @pyqtSlot()
    def run(self):
        self.sched = asynker.Scheduler()
        self.run_event_loop()

        print('Shutting event loop down.')
        for reply in list(self.in_flight):
            reply.abort()  # This will trigger the respective finished() signals, which will cancel related futures
        self.sched.cancel_all_tasks()
        self.sched.run_until_all_tasks_finished()
        print('Event loop shut down.')

    def run_event_loop(self):
        """
        Runs the event loop. Will only complete if the thread receives an interruption request
        (QThread.requestInterruption()).

        Qt manages this thread's event loop, meanwhile asynker will dispatch completed futures to their
        respective coroutines.
        """
        thread = self.thread()
        while not thread.isInterruptionRequested():
            self.sched.tick()
            thread.eventDispatcher().processEvents(QEventLoop.AllEvents|QEventLoop.WaitForMoreEvents)

    def get(self, url: QUrl) -> asynker.Future:
        future = asynker.Future()
        request = QNetworkRequest(url)
        reply = self.network_access.get(request)
        reply.finished.connect(self.network_request_finished)
        self.in_flight[reply] = future
        return future

    @pyqtSlot()
    def network_request_finished(self):
        reply = self.sender()
        future = self.in_flight.pop(reply)

        if reply.error():
            exc = NetworkRequestFailed(reply.error(), reply.errorString())
            future.set_exception(exc)
        else:
            future.set_result(reply)


class PageStats(QObject):
    done = pyqtSignal()
    result = pyqtSignal(dict)
    summary = pyqtSignal(dict)

    def __init__(self, network, parent=None):
        super().__init__(parent)
        self.network = network
        self.future = None

    @pyqtSlot(QUrl)
    def fetch_stats(self, url):
        if not self.future or self.future.done():
            self.future = self.network.sched.run(self._fetch_stats(url))
            self.future.add_done_callback(self._done)
        else:
            print('Still working.')

    async def _fetch_stats(self, url):
        def emit_result(result):
            summary['requests'] += 1
            summary['size'] += result['size']
            self.result.emit(result)

        summary = dict(requests=0, size=0)
        reply = await self.network.get(url)
        body = reply.readAll().data()
        emit_result(dict(type='page', path='.', url=url, size=len(body)))

        # For simplicity, assume UTF-8.
        tree = lxml.html.document_fromstring(body.decode())
        ext_resources = self._extract_resources(tree, url)

        async for resource in asynker.as_completed(*[self._get_resource_size(r) for r in ext_resources], scheduler=self.network.sched):
            emit_result(resource)

        self.summary.emit(summary)

    async def _get_resource_size(self, resource):
        reply = await self.network.get(resource['url'])
        resource['size'] = len(reply.readAll().data())
        return resource

    def _extract_resources(self, etree, base_url):
        def get_elements_with_tag(tag):
            return etree.xpath('.//' + tag)

        def add_resource(type, path):
            resources.append(dict(type=type, path=path, url=base_url.resolved(QUrl(path))))

        resources = []

        for element in get_elements_with_tag('link'):
            if element.attrib.get('rel', None) == 'stylesheet' and 'href' in element.attrib:
                add_resource('stylesheet', element.attrib['href'])
        for element in get_elements_with_tag('script'):
            if 'src' in element.attrib:
                add_resource('script', element.attrib['src'])
        for element in get_elements_with_tag('img'):
            if element.attrib.get('src'):
                add_resource('image', element.attrib['src'])

        return resources

    def _done(self, future):
        if future.exception():
            print('Exception in fetch_stats:', future.exception())
        self.done.emit()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        self.workerthread = QThread(self)
        self.network = Network()
        self.network.moveToThread(self.workerthread)
        self.pagestats = PageStats(self.network)
        self.pagestats.moveToThread(self.workerthread)
        self.workerthread.started.connect(self.network.run)
        self.workerthread.start()

        self.setCentralWidget(QWidget())
        self.centralWidget().setLayout(QVBoxLayout())
        layout = self.centralWidget().layout()

        self.urlinput = QLineEdit()
        self.urlinput.setPlaceholderText('Enter URL of web page here')
        self.dobutton = QPushButton('Fetch stats')
        self.dobutton.clicked.connect(self.do)
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(['Type', 'Path', 'Size'])
        self.results.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)

        self.pagestats.result.connect(self.show_result)
        self.pagestats.done.connect(self.done)
        self.pagestats.summary.connect(self.show_summary)

        layout.addWidget(self.urlinput)
        layout.addWidget(self.dobutton)
        layout.addWidget(self.results)

    def closeEvent(self, e):
        self.workerthread.requestInterruption()
        self.workerthread.eventDispatcher().wakeUp()
        self.workerthread.quit()
        self.workerthread.wait()
        super().closeEvent(e)

    @pyqtSlot()
    def do(self):
        url = QUrl.fromUserInput(self.urlinput.text())
        if url.isValid():
            self.metaObject().invokeMethod(self.pagestats, 'fetch_stats', Qt.QueuedConnection, Q_ARG(QUrl, url))
            self.dobutton.setEnabled(False)
            self.results.clearContents()
            self.results.setRowCount(0)
        else:
            self.statusBar().showMessage('Invalid url.')

    @pyqtSlot(dict)
    def show_result(self, result):
        row = self.results.rowCount()
        item1 = QTableWidgetItem(result['type'])
        item2 = QTableWidgetItem(result['path'])
        item3 = QTableWidgetItem(self.locale().formattedDataSize(result['size']))
        self.results.insertRow(row)
        self.results.setItem(row, 0, item1)
        self.results.setItem(row, 1, item2)
        self.results.setItem(row, 2, item3)

    @pyqtSlot(dict)
    def show_summary(self, summary):
        msg = '%s in %d requests' % (self.locale().formattedDataSize(summary['size']), summary['requests'])
        self.statusBar().showMessage(msg)

    @pyqtSlot()
    def done(self):
        self.dobutton.setEnabled(True)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    app.exec()
