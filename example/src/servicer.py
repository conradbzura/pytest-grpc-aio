import threading

from stub.test_pb2 import EchoRequest
from stub.test_pb2 import EchoResponse
from stub.test_pb2 import Empty
from stub.test_pb2_grpc import EchoServiceServicer


class Servicer(EchoServiceServicer):
    def __init__(self):
        self.barrier = threading.Barrier(2)

    def handler(self, request: EchoRequest, context) -> EchoResponse:
        return EchoResponse(name=f"test-{request.name}")

    def error_handler(self, request: EchoRequest, context) -> EchoResponse:
        raise RuntimeError("Some error")

    def blocking(self, request_stream, context):
        for i in range(2):
            yield EchoResponse(name=str(i))
            self.barrier.wait()

    def unblock(self, _, context):
        self.barrier.wait()
        return Empty()
