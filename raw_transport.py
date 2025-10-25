"""
High-performance socket-based transport for ultra-low latency
Uses TCP for reliability with optimized settings for low latency
"""
import socket
import threading
import struct
import time
from typing import Callable, Optional
import queue

NUM_FORMAT = '<Q'
UDP_MAX_SIZE = 8192  # Maximum safe UDP datagram size

class RawSocketProtocol:
    """Base class for raw socket protocols - much faster than Twisted"""
    
    def __init__(self):
        self.socket = None
        self.running = False
        self.send_queue = queue.Queue()
        self.receive_buffer = b''
        self.message_handler: Optional[Callable] = None
        self.is_udp = False  # Use TCP for reliability - UDP fragmentation is complex
        self.remote_addr = None
        
        # UDP fragmentation support (kept for future use)
        self._udp_reassembly_buffer = None
        self._udp_received_fragments = None
        self._udp_expected_fragments = None
        
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
                    # UDP send with fragmentation for large messages
                    self._send_udp_fragmented(data, self.remote_addr)
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
    
    def _send_udp_fragmented(self, data: bytes, addr):
        """Send large data via UDP with fragmentation"""
        total_size = len(data)
        
        if total_size <= UDP_MAX_SIZE:
            # Small message, send directly
            try:
                self.socket.sendto(data, addr)
            except Exception as e:
                print(f"UDP send error: {e}")
            return
        
        # Large message, fragment it
        # Send header with total size first
        header = struct.pack('<Q', total_size)
        try:
            self.socket.sendto(header, addr)
        except Exception as e:
            print(f"UDP header send error: {e}")
            return
        
        # Send data in chunks
        offset = 0
        fragment_id = 0
        while offset < total_size:
            chunk_size = min(UDP_MAX_SIZE - 8, total_size - offset)  # 8 bytes for fragment header
            chunk = data[offset:offset + chunk_size]
            
            # Add fragment header: fragment_id (4 bytes) + offset (4 bytes)
            fragment_header = struct.pack('<II', fragment_id, offset)
            fragment_data = fragment_header + chunk
            
            try:
                self.socket.sendto(fragment_data, addr)
            except Exception as e:
                print(f"UDP fragment send error: {e}")
                return
            
            offset += chunk_size
            fragment_id += 1
    
    def _receive_worker(self):
        """High-performance receive worker thread"""
        while self.running:
            try:
                if self.is_udp:
                    # UDP receive with fragmentation support
                    self._receive_udp_fragmented()
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
    
    def _receive_udp_fragmented(self):
        """Receive UDP data with fragmentation reassembly"""
        try:
            data, addr = self.socket.recvfrom(131072)
            
            if self.remote_addr is None:
                self.remote_addr = addr
            
            # Check if this is a header message (total size)
            if len(data) == 8:  # Size of uint64_t
                try:
                    expected_size = struct.unpack('<Q', data)[0]
                    self._udp_reassembly_buffer = bytearray(expected_size)
                    self._udp_received_fragments = set()
                    self._udp_expected_fragments = None
                    return
                except:
                    pass  # Not a header, treat as regular message
            
            # Check if this is a fragment
            if len(data) >= 8:
                try:
                    fragment_id, offset = struct.unpack('<II', data[:8])
                    chunk_data = data[8:]
                    
                    if hasattr(self, '_udp_reassembly_buffer') and self._udp_reassembly_buffer is not None:
                        # Store fragment
                        self._udp_reassembly_buffer[offset:offset + len(chunk_data)] = chunk_data
                        self._udp_received_fragments.add(fragment_id)
                        
                        # Check if we have all fragments
                        if self._udp_expected_fragments is None:
                            # Estimate number of fragments based on first fragment
                            chunk_size = len(chunk_data)
                            total_size = len(self._udp_reassembly_buffer)
                            self._udp_expected_fragments = (total_size + chunk_size - 1) // chunk_size
                        
                        if len(self._udp_received_fragments) == self._udp_expected_fragments:
                            # All fragments received, reassemble message
                            complete_data = bytes(self._udp_reassembly_buffer)
                            self._udp_reassembly_buffer = None
                            self._udp_received_fragments = None
                            self._udp_expected_fragments = None
                            
                            # Process complete message
                            if self.message_handler:
                                try:
                                    self.message_handler(complete_data)
                                except Exception as e:
                                    print(f"Message handler error: {e}")
                        return
                except:
                    pass  # Not a fragment, treat as regular message
            
            # Regular small message
            if self.message_handler:
                try:
                    self.message_handler(data)
                except Exception as e:
                    print(f"Message handler error: {e}")
                    
        except Exception as e:
            if self.running:
                print(f"UDP receive error: {e}")
    
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
        self.is_udp = False  # Use TCP for reliability
        
    def start(self):
        """Start the server"""
        if self.is_udp:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.bind(('0.0.0.0', self.port))
            print(f"UDP server listening on port {self.port}")
            
            # Start receive thread
            threading.Thread(target=self._udp_receive_loop, daemon=True).start()
        else:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Ultra-low latency socket options
            try:
                self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass  # May not be supported on all systems
            
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
                
                # Handle handshake messages
                if data == b'HANDSHAKE':
                    print(f"UDP handshake received from {addr}")
                    if self.client_protocol is None:
                        # Create protocol on handshake
                        if callable(self.protocol_class):
                            if self.protocol_args:
                                self.client_protocol = self.protocol_class(*self.protocol_args)
                            else:
                                self.client_protocol = self.protocol_class()
                        else:
                            self.client_protocol = self.protocol_class()
                        
                        self.client_protocol.socket = self.server_socket
                        self.client_protocol.remote_addr = addr
                        # If protocol has delegated protocol
                        if hasattr(self.client_protocol, 'protocol'):
                            self.client_protocol.protocol.remote_addr = addr
                        self.client_protocol.running = True
                        
                        # Start send worker
                        threading.Thread(target=self.client_protocol._send_worker, daemon=True).start()
                        
                        # Protocol-specific initialization
                        if hasattr(self.client_protocol, 'connection_made'):
                            self.client_protocol.connection_made()
                    continue  # Don't pass handshake to message handler
                
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
                    # If protocol has delegated protocol
                    if hasattr(self.client_protocol, 'protocol'):
                        self.client_protocol.protocol.remote_addr = addr
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
                try:
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # No Nagle
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB send buffer
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB receive buffer
                    # Additional low-latency TCP options
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)  # Quick ACK
                    # Disable TCP slow start and congestion control for local networks
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, b'reno')  # Use Reno for lower latency
                except OSError as e:
                    print(f"Socket optimization warning: {e}")
                
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
        self.is_udp = False  # Use TCP for reliability
        
    def connect(self):
        """Connect to server"""
        if self.is_udp:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(('0.0.0.0', 0))  # Bind to random port for receiving
            self.remote_addr = (self.host, self.port)
            print(f"UDP client bound to random port, ready to connect to {self.host}:{self.port}")
            
            # For UDP, send initial handshake message to establish connection
            # This allows the server to know our address and start responding
            try:
                self.socket.sendto(b'HANDSHAKE', self.remote_addr)
                print("UDP handshake sent")
            except Exception as e:
                print(f"UDP handshake failed: {e}")
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB send buffer
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB receive buffer
                # Low-latency TCP options
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, b'reno')
            except OSError as e:
                print(f"Client socket optimization warning: {e}")
            self.socket.connect((self.host, self.port))
            print(f"TCP client connected to {self.host}:{self.port}")
        
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
        self.protocol_instance.remote_addr = self.remote_addr
        # If protocol has delegated protocol (like PyQt5), set there too
        if hasattr(self.protocol_instance, 'protocol'):
            self.protocol_instance.protocol.remote_addr = self.remote_addr
        self.protocol_instance.running = True
        
        # Start worker threads
        threading.Thread(target=self.protocol_instance._send_worker, daemon=True).start()
        threading.Thread(target=self.protocol_instance._receive_worker, daemon=True).start()
        
        # Protocol-specific initialization
        if hasattr(self.protocol_instance, 'connection_made'):
            self.protocol_instance.connection_made()
            
        return self.protocol_instance

# Factory functions to match the existing interface
def create_raw_socket_server(port: int, protocol_class, protocol_args=None, use_udp=False):
    """Create a raw socket server"""
    server = RawSocketServer(port, protocol_class, protocol_args)
    server.is_udp = use_udp
    server.start()
    return server

def create_raw_socket_client(host: str, port: int, protocol_class, protocol_args=None, use_udp=False):
    """Create a raw socket client"""
    client = RawSocketClient(host, port, protocol_class, protocol_args)
    client.is_udp = use_udp
    protocol_instance = client.connect()
    
    # Expose protocol instance through client for access
    client.protocol_instance = protocol_instance
    
    # If protocol has tkinter root, expose it
    if protocol_instance and hasattr(protocol_instance, 'tk_root'):
        client.tk_root = protocol_instance.tk_root
    
    return client