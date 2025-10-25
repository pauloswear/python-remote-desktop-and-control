from twisted.internet import reactor
from twisted.internet.protocol import Protocol
import struct

NUM_FORMAT = '<Q'

class ProtocolBase(Protocol):
    def __init__(self):
        self.buffer = bytes([])
        self.receiveBuffer = bytes([])
        self.receiveMessageLength = -1
        self.flush_scheduled = False
        # Ultra-aggressive flushing for maximum FPS
        reactor.callLater(0.0001, self.flush)

    def writeMessage(self, newBytes):
        self.buffer += struct.pack(NUM_FORMAT, len(newBytes))
        self.buffer += newBytes
        
        # Immediate flush for any message to minimize latency
        if not self.flush_scheduled:
            self.flush_scheduled = True
            reactor.callLater(0, self.flush_immediate)

    def flush_immediate(self):
        self.flush_scheduled = False
        if len(self.buffer) > 0:
            try:
                # Send everything immediately for ultra-low latency
                self.transport.write(self.buffer)
                self.buffer = bytes([])
            except:
                pass  # Ignore errors during immediate flush

    def flush(self):
        if len(self.buffer) > 0 and not self.flush_scheduled:
            try:
                # Send large chunks efficiently
                chunk_size = min(len(self.buffer), 262144)  # 256KB chunks for better throughput
                self.transport.write(self.buffer[:chunk_size])
                self.buffer = self.buffer[chunk_size:]
            except:
                pass
        
        # Extremely frequent flushing for ultra-high FPS
        reactor.callLater(0.0001, self.flush)

    def dataReceived(self, data: bytes):
        self.receiveBuffer += data
        self.processMessage()

    def processMessage(self):
        if self.receiveMessageLength == -1:
            size = struct.calcsize(NUM_FORMAT)
            if len(self.receiveBuffer) < size:
                return
            self.receiveMessageLength = struct.unpack(NUM_FORMAT, self.receiveBuffer[:size])[0]
            self.receiveBuffer = self.receiveBuffer[size:]
            self.processMessage()
        else:
            if self.receiveMessageLength <= len(self.receiveBuffer):
                bufferCopy = self.receiveBuffer[:self.receiveMessageLength]
                self.receiveBuffer = self.receiveBuffer[self.receiveMessageLength:]
                self.receiveMessageLength = -1
                self.messageReceived(bufferCopy)
                self.processMessage()

    def messageReceived(self, message: bytes):
        pass