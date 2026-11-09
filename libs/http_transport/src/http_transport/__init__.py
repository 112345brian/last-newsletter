"""The workspace's single stdlib HTTP transport."""

__arbor__ = {"ring": "libs"}

from http_transport.transport import Getter, HttpResponse, Poster, UrllibTransport

__all__ = ["Getter", "HttpResponse", "Poster", "UrllibTransport"]
