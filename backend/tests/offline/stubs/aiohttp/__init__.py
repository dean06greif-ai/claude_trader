"""Minimal-Stub NUR für die Offline-Analyse (kein Netzwerk in der Sandbox).
Erlaubt den Import der reinen Rechenmodule (Backtester/Optimizer), ohne dass
aiohttp installiert ist. Jeder echte Netzwerkzugriff schlägt bewusst fehl."""
class _Dummy:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): return self
    def __getattr__(self, name): return _Dummy()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
class ClientSession(_Dummy):
    def get(self, *a, **k): raise RuntimeError("offline stub: kein Netzwerk")
    def post(self, *a, **k): raise RuntimeError("offline stub: kein Netzwerk")
class ClientTimeout(_Dummy): pass
class TCPConnector(_Dummy): pass
class ClientError(Exception): pass
class ClientResponseError(ClientError): pass
class ClientConnectorError(ClientError): pass
class WSMsgType:
    TEXT = 1; BINARY = 2; CLOSED = 3; ERROR = 4; CLOSE = 5; CLOSING = 6
def __getattr__(name):
    return _Dummy
