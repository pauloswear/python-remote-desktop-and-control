"""
High-performance socket-based transport for ultra-low latency
"""
import socket
import threading
import struct
import time
from typing import Callable, Optional
import queue

NUM_FORMAT = '<Q'

class RawSocketProtocol:
    """Base class for raw socket protocols - much faster than Twisted"""
    
    def __init__(self):
        self.socket = None
        self.running = False
        self.send_queue = queue.Queue()
        self.receive_buffer = b''
        self.message_handler: Optional[Callable] = None
        self.is_udp = True  # Use UDP for maximum speed
        self.remote_addr = None
        
    def set_message_handler(self, handler: Callable):
        """Set function to handle received messages"""
        self.message_handler = handler
        
    def write_message(self, data: bytes):
        """Queue message for sending - ultra fast"""
        if self.running:
            self.send_queue.put(data, block=False)
    
    def _send_worker(self):
        """High-performance send worker thread"""
        while self.running:
            try:
                # Get message with ultra-minimal timeout for maximum responsiveness  
                data = self.send_queue.get(timeout=0.0001)  # 0.1ms timeout
                if data is None:  # Shutdown signal
                    break
                    
                if self.is_udp and self.remote_addr:
                    # UDP send
                    self.socket.sendto(data, self.remote_addr)
                else:
                    # TCP send with length prefix
                    message_length = struct.pack(NUM_FORMAT, len(data))
                    self.socket.sendall(message_length + data)
                
            except queue.Empty:
                continue
            except Exception as e:
                if self.running:
                    print(f"Send error: {e}")
                break
    
    def _receive_worker(self):
        """High-performance receive worker thread"""
        while self.running:
            try:
                if self.is_udp:
                    # UDP receive
                    data, addr = self.socket.recvfrom(131072)  # 128KB chunks
                    if self.remote_addr is None:
                        self.remote_addr = addr  # Set remote address on first receive
                    # For UDP, each recv is a complete message (no length prefix needed)
                    if self.message_handler:
                        try:
                            self.message_handler(data)
                        except Exception as e:
                            print(f"Message handler error: {e}")
                else:
                    # TCP receive
                    data = self.socket.recv(131072)  # 128KB chunks for better throughput
                    if not data:
                        break
                        
                    self.receive_buffer += data
                    self._process_messages()
                
            except Exception as e:
                if self.running:
                    print(f"Receive error: {e}")
                break
    
    def _process_messages(self):
        """Process complete messages from buffer"""
        header_size = struct.calcsize(NUM_FORMAT)
        
        while len(self.receive_buffer) >= header_size:
            # Get message length
            message_length = struct.unpack(NUM_FORMAT, self.receive_buffer[:header_size])[0]
            total_length = header_size + message_length
            
            # Check if we have complete message
            if len(self.receive_buffer) >= total_length:
                # Extract message
                message_data = self.receive_buffer[header_size:total_length]
                self.receive_buffer = self.receive_buffer[total_length:]
                
                # Handle message
                if self.message_handler:
                    try:
                        self.message_handler(message_data)
                    except Exception as e:
                        print(f"Message handler error: {e}")
            else:
                break
    
    def stop(self):
        """Stop the protocol"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass

class RawSocketServer(RawSocketProtocol):
    """High-performance server using raw sockets"""
    
    def __init__(self, port: int, protocol_class, protocol_args=None):
        super().__init__()
        self.port = port
        self.protocol_class = protocol_class
        self.protocol_args = protocol_args or []
        self.server_socket = None
        self.client_protocol = None
        
    def start(self):
        """Start the server"""
        if self.is_udp:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.bind(('0.0.0.0', self.port))
            print(f"UDP server listening on port {self.port}")
            
            # Start receive thread
            threading.Thread(target=self._udp_receive_loop, daemon=True).start()
        else:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Ultra-low latency socket options
            self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(1)
            
            print(f"TCP server listening on port {self.port}")
            
            # Accept connections in a thread
            threading.Thread(target=self._accept_connections, daemon=True).start()
    
    def _udp_receive_loop(self):
        """UDP receive loop for server"""
        while True:
            try:
                data, addr = self.server_socket.recvfrom(131072)
                if self.client_protocol is None:
                    # Create protocol on first message
                    if callable(self.protocol_class):
                        if self.protocol_args:
                            self.client_protocol = self.protocol_class(*self.protocol_args)
                        else:
                            self.client_protocol = self.protocol_class()
                    else:
                        self.client_protocol = self.protocol_class()
                    
                    self.client_protocol.socket = self.server_socket
                    self.client_protocol.remote_addr = addr
                    self.client_protocol.running = True
                    
                    # Start send worker
                    threading.Thread(target=self.client_protocol._send_worker, daemon=True).start()
                    
                    # Protocol-specific initialization
                    if hasattr(self.client_protocol, 'connection_made'):
                        self.client_protocol.connection_made()
                
                # Handle message
                if self.client_protocol and self.client_protocol.message_handler:
                    try:
                        self.client_protocol.message_handler(data)
                    except Exception as e:
                        print(f"Message handler error: {e}")
                        
            except Exception as e:
                print(f"UDP receive error: {e}")
                break
    
    def _accept_connections(self):
        """Accept client connections"""
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"Raw socket client connected: {addr}")
                
                # Ultra-aggressive socket optimization for minimum latency
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # No Nagle
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 524288)  # 512KB send buffer
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)  # 512KB receive buffer
                
                # Additional low-latency optimizations
                try:
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)  # Quick ACK
                except (AttributeError, OSError):
                    pass  # Not available on all platforms
                
                # Set socket to non-blocking for faster operations
                client_socket.setblocking(True)  # Keep blocking for simplicity but optimize
                
                # Create protocol instance
                if callable(self.protocol_class):
                    if self.protocol_args:
                        self.client_protocol = self.protocol_class(*self.protocol_args)
                    else:
                        self.client_protocol = self.protocol_class()
                else:
                    # It's a factory function
                    self.client_protocol = self.protocol_class()
                
                self.client_protocol.socket = client_socket
                self.client_protocol.running = True
                
                # Start worker threads
                threading.Thread(target=self.client_protocol._send_worker, daemon=True).start()
                threading.Thread(target=self.client_protocol._receive_worker, daemon=True).start()
                
                # Protocol-specific initialization
                if hasattr(self.client_protocol, 'connection_made'):
                    self.client_protocol.connection_made()
                
                break  # Only handle one client for simplicity
                
            except Exception as e:
                print(f"Accept error: {e}")
                break

class RawSocketClient(RawSocketProtocol):
    """High-performance client using raw sockets"""
    
    def __init__(self, host: str, port: int, protocol_class, protocol_args=None):
        super().__init__()
        self.host = host
        self.port = port
        self.protocol_class = protocol_class
        self.protocol_args = protocol_args or []
        self.protocol_instance = None
        
    def connect(self):
        """Connect to server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Ultra-aggressive client socket optimization
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # No Nagle
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 524288)  # 512KB send buffer  
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)  # 512KB receive buffer
        
        # Additional low-latency optimizations
        try:
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)  # Quick ACK
        except (AttributeError, OSError):
            pass  # Not available on all platforms
        
        try:
            self.socket.connect((self.host, self.port))
            print(f"Raw socket connected to {self.host}:{self.port}")
            
            # Create protocol instance
            if callable(self.protocol_class):
                if self.protocol_args:
                    self.protocol_instance = self.protocol_class(*self.protocol_args)
                else:
                    self.protocol_instance = self.protocol_class()
            else:
                # It's a factory function
                self.protocol_instance = self.protocol_class()
                
            self.protocol_instance.socket = self.socket
            self.protocol_instance.running = True
            
            # Start worker threads
            threading.Thread(target=self.protocol_instance._send_worker, daemon=True).start()
            threading.Thread(target=self.protocol_instance._receive_worker, daemon=True).start()
            
            # Protocol-specific initialization
            if hasattr(self.protocol_instance, 'connection_made'):
                self.protocol_instance.connection_made()
                
            return self.protocol_instance
            
        except Exception as e:
            print(f"Connection error: {e}")
            return None

# Factory functions to match the existing interface
def create_raw_socket_server(port: int, protocol_class, protocol_args=None):
    """Create a raw socket server"""
    server = RawSocketServer(port, protocol_class, protocol_args)
    server.start()
    return server

def create_raw_socket_client(host: str, port: int, protocol_class, protocol_args=None):
    """Create a raw socket client"""
    client = RawSocketClient(host, port, protocol_class, protocol_args)
    protocol_instance = client.connect()
    
    # Expose protocol instance through client for access
    client.protocol_instance = protocol_instance
    
    # If protocol has tkinter root, expose it
    if protocol_instance and hasattr(protocol_instance, 'tk_root'):
        client.tk_root = protocol_instance.tk_root
    
    return client