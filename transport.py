from twisted.internet.protocol import *
from twisted.internet.endpoints import *
from twisted.internet import reactor
from controller import ControllerProtocol, FactoryControllerBase
from controllee import ControlleeProtocol
from constants import VAR_USE_RAW_SOCKETS_DEFAULT
from raw_transport import create_raw_socket_server, create_raw_socket_client
from raw_protocols import RawControlleeProtocol, RawControllerProtocol, create_raw_controller_protocol

class OurClientFactory(ReconnectingClientFactory):
    maxDelay = 5
    factor = 1
    def buildProtocol(self, addr):
        print("Build protocol called")
        self.resetDelay()
        return ReconnectingClientFactory.buildProtocol(self, addr)

class ControllerFactoryServer(FactoryControllerBase, Factory):
    pass

class ControllerFactoryClient(FactoryControllerBase, OurClientFactory):
    pass

class ControlleeFactoryServer(Factory):
    protocol = ControlleeProtocol

class ControlleeFactoryClient(OurClientFactory):
    protocol = ControlleeProtocol

def get_transport(ip: str, isController: bool, port: int, use_raw_sockets: bool = VAR_USE_RAW_SOCKETS_DEFAULT):
    """
    Get transport layer - supports both Twisted and Raw Sockets
    
    Args:
        ip: IP address (None for server mode)
        isController: True for controller, False for controllee
        port: Port number
        use_raw_sockets: True for raw sockets (higher performance), False for Twisted
    """
    
    if use_raw_sockets:
        print(f"Using RAW SOCKETS for {'controller' if isController else 'controllee'}")
        return get_raw_socket_transport(ip, isController, port)
    else:
        print(f"Using TWISTED REACTOR for {'controller' if isController else 'controllee'}")
        return get_twisted_transport(ip, isController, port)

def get_raw_socket_transport(ip: str, isController: bool, port: int):
    """High-performance raw socket transport"""
    if ip is None:
        # Server mode
        if isController:
            return create_raw_socket_server(port, create_raw_controller_protocol)
        else:
            return create_raw_socket_server(port, RawControlleeProtocol)
    else:
        # Client mode
        if isController:
            return create_raw_socket_client(ip, port, create_raw_controller_protocol)
        else:
            return create_raw_socket_client(ip, port, RawControlleeProtocol)

def get_twisted_transport(ip: str, isController: bool, port: int):
    """Original Twisted-based transport"""
    if ip is None:
        factory = ControllerFactoryServer() if isController else ControlleeFactoryServer()
        reactor.listenTCP(port, factory)
        return factory
    else:
        factory = ControllerFactoryClient() if isController else ControlleeFactoryClient()
        reactor.connectTCP(ip, port, factory)
        return factory