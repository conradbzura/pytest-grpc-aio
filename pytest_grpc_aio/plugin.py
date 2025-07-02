import socket
from concurrent import futures
from contextlib import asynccontextmanager
from contextlib import contextmanager

import grpc
import grpc.aio
import pytest
import pytest_asyncio
from grpc._cython.cygrpc import CompositeChannelCredentials
from grpc._cython.cygrpc import _Metadatum


def pytest_addoption(parser):
    parser.addoption("--grpc-fake-server", action="store_true", dest="grpc-fake")
    parser.addoption("--grpc-max-workers", type=int, dest="grpc-max-workers", default=1)


class FakeServer(object):
    def __init__(self, pool):
        self.handlers = {}
        self.pool = pool

    def add_generic_rpc_handlers(self, generic_rpc_handlers):
        from grpc._server import _validate_generic_rpc_handlers

        _validate_generic_rpc_handlers(generic_rpc_handlers)

        self.handlers.update(generic_rpc_handlers[0]._method_handlers)

    def start(self):
        pass

    def stop(self, grace=None):
        pass

    def add_secure_port(self, target, server_credentials):
        pass

    def add_insecure_port(self, target):
        pass


class FakeRpcError(RuntimeError, grpc.RpcError):
    def __init__(self, code, details):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


class FakeContext(object):
    def __init__(self):
        self._invocation_metadata = []

    def abort(self, code, details):
        raise FakeRpcError(code, details)

    def invocation_metadata(self):
        return self._invocation_metadata


class FakeChannel:
    def __init__(self, fake_server, credentials):
        self.server = fake_server
        self._credentials = credentials

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def fake_method(self, method_name, uri, *args, **kwargs):
        handler = self.server.handlers[uri]
        real_method = getattr(handler, method_name)

        def fake_handler(request):
            context = FakeContext()

            def metadata_callbak(metadata, error):
                context._invocation_metadata.extend(
                    (_Metadatum(k, v) for k, v in metadata)
                )

            if self._credentials and isinstance(
                self._credentials._credentials, CompositeChannelCredentials
            ):
                for call_cred in self._credentials._credentials._call_credentialses:
                    call_cred._metadata_plugin._metadata_plugin(
                        context, metadata_callbak
                    )
            future = self.server.pool.submit(real_method, request, context)
            return future.result()

        return fake_handler

    def unary_unary(self, *args, **kwargs):
        return self.fake_method("unary_unary", *args, **kwargs)

    def unary_stream(self, *args, **kwargs):
        return self.fake_method("unary_stream", *args, **kwargs)

    def stream_unary(self, *args, **kwargs):
        return self.fake_method("stream_unary", *args, **kwargs)

    def stream_stream(self, *args, **kwargs):
        return self.fake_method("stream_stream", *args, **kwargs)


@pytest.fixture(scope="function")
def grpc_addr():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("localhost", 0))
    return "localhost:{}".format(sock.getsockname()[1])


@pytest.fixture(scope="function")
def grpc_interceptors():
    return


@pytest.fixture(scope="function")
def grpc_server(
    request, grpc_addr, grpc_add_to_server, grpc_servicer, grpc_interceptors
):
    @contextmanager
    def _grpc_server():
        max_workers = request.config.getoption("grpc-max-workers")
        try:
            max_workers = max(request.module.grpc_max_workers, max_workers)
        except AttributeError:
            pass
        pool = futures.ThreadPoolExecutor(max_workers=max_workers)
        if request.config.getoption("grpc-fake"):
            server = FakeServer(pool)
        else:
            server = grpc.server(pool, interceptors=grpc_interceptors)
        grpc_add_to_server(grpc_servicer, server)
        server.add_insecure_port(grpc_addr)
        server.start()
        yield server
        server.stop(grace=None)
        pool.shutdown(wait=False)

    return _grpc_server


@pytest.fixture(scope="function")
def grpc_channel(request, grpc_addr, grpc_server):
    @contextmanager
    def _grpc_channel(credentials=None, options=None):
        with grpc_server() as server:
            if request.config.getoption("grpc-fake"):
                yield FakeChannel(server, credentials)
            elif credentials is not None:
                yield grpc.secure_channel(grpc_addr, credentials, options)
            else:
                yield grpc.insecure_channel(grpc_addr, options)

    return _grpc_channel


@pytest.fixture(scope="function")
def grpc_stub(grpc_stub_cls, grpc_channel):
    @contextmanager
    def _grpc_stub():
        with grpc_channel() as channel:
            yield grpc_stub_cls(channel)

    return _grpc_stub


class FakeAIOServer(object):
    def __init__(self, pool):
        self.handlers = {}
        self.pool = pool

    def add_generic_rpc_handlers(self, generic_rpc_handlers):
        from grpc._server import _validate_generic_rpc_handlers

        _validate_generic_rpc_handlers(generic_rpc_handlers)

        self.handlers.update(generic_rpc_handlers[0]._method_handlers)

    async def start(self):
        pass

    async def stop(self, grace=None):
        pass

    def add_secure_port(self, target, server_credentials):
        pass

    def add_insecure_port(self, target):
        pass


class FakeAIOChannel:
    def __init__(self, fake_server, credentials):
        self.server = fake_server
        self._credentials = credentials

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def fake_method(self, method_name, uri, *args, **kwargs):
        handler = self.server.handlers[uri]
        real_method = getattr(handler, method_name)

        def fake_handler(request):
            context = FakeContext()

            def metadata_callbak(metadata, error):
                context._invocation_metadata.extend(
                    (_Metadatum(k, v) for k, v in metadata)
                )

            if self._credentials and isinstance(
                self._credentials._credentials, CompositeChannelCredentials
            ):
                for call_cred in self._credentials._credentials._call_credentialses:
                    call_cred._metadata_plugin._metadata_plugin(
                        context, metadata_callbak
                    )
            future = self.server.pool.submit(real_method, request, context)
            return future.result()

        return fake_handler

    def unary_unary(self, *args, **kwargs):
        return self.fake_method("unary_unary", *args, **kwargs)

    def unary_stream(self, *args, **kwargs):
        return self.fake_method("unary_stream", *args, **kwargs)

    def stream_unary(self, *args, **kwargs):
        return self.fake_method("stream_unary", *args, **kwargs)

    def stream_stream(self, *args, **kwargs):
        return self.fake_method("stream_stream", *args, **kwargs)


@pytest.fixture(scope="function")
def grpc_aio_server(
    request, grpc_addr, grpc_add_to_server, grpc_servicer, grpc_interceptors
):
    @asynccontextmanager
    async def _grpc_aio_server():
        max_workers = request.config.getoption("grpc-max-workers")
        try:
            max_workers = max(request.module.grpc_max_workers, max_workers)
        except AttributeError:
            pass
        pool = futures.ThreadPoolExecutor(max_workers=max_workers)
        if request.config.getoption("grpc-fake"):
            server = FakeAIOServer(pool)
        else:
            server = grpc.aio.server(pool, interceptors=grpc_interceptors)
        grpc_add_to_server(grpc_servicer, server)
        server.add_insecure_port(grpc_addr)
        await server.start()
        yield server
        await server.stop(grace=None)
        pool.shutdown(wait=False)

    return _grpc_aio_server


@pytest.fixture(scope="function")
def grpc_aio_channel(request, grpc_addr, grpc_aio_server):
    @asynccontextmanager
    async def _grpc_aio_channel(credentials=None, options=None):
        async with grpc_aio_server() as server:
            if request.config.getoption("grpc-fake"):
                yield FakeAIOChannel(server, credentials)
            elif credentials is not None:
                yield grpc.aio.secure_channel(grpc_addr, credentials, options)
            else:
                yield grpc.aio.insecure_channel(grpc_addr, options)

    return _grpc_aio_channel


@pytest.fixture(scope="function")
def grpc_aio_stub(grpc_stub_cls, grpc_aio_channel):
    @asynccontextmanager
    async def _grpc_aio_stub():
        async with grpc_aio_channel() as channel:
            yield grpc_stub_cls(channel)

    return _grpc_aio_stub
